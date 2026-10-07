"""资格/借出回归：可借栏与借出闸同一个资格世界，拒绝零写入，互斥不误伤。"""
import sqlite3

import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.main import app
    with TestClient(app) as c:
        yield c


def _ids(rows):
    return {r["id"] for r in rows}


def _raw_conn():
    from app.db import db_path
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    return conn


def test_board_partitions_dirty_item_out_of_available(client):
    b = client.get("/api/board").json()
    # 种子：电钻(1)、折叠桌(2) 合格可借；脏数据-无主(3) 必须落 blocked。
    assert _ids(b["available"]) == {1, 2}
    assert _ids(b["blocked"]) == {3}
    assert b["counts"]["available"] == 2
    assert b["counts"]["blocked"] == 1
    blocked3 = next(i for i in b["blocked"] if i["id"] == 3)
    assert set(blocked3["blocked_reasons"]) == {"owner_missing", "dirty_data"}


def test_lend_dirty_item_rejected_without_any_write(client):
    r = client.post("/api/items/3/lend", json={"borrower": "邻居乙", "due_date": "2026-12-31"})
    assert r.status_code == 409
    # 无主与 dirty 同时命中，资格闸按 owner_missing、dirty_data 的顺序给第一条理由。
    assert r.json()["detail"] == "owner_missing"

    conn = _raw_conn()
    # 拒绝路径：loans 零新增，物品仍 available、仍 dirty、owner 仍空。
    assert conn.execute("SELECT COUNT(*) c FROM loans WHERE item_id=3").fetchone()["c"] == 0
    it = conn.execute("SELECT * FROM items WHERE id=3").fetchone()
    assert it["status"] == "available"
    assert it["data_quality"] == "dirty"
    assert it["owner"] == ""
    conn.close()

    # 可借栏依旧没有它，顶细条数不漂。
    b = client.get("/api/board").json()
    assert 3 not in _ids(b["available"])
    assert b["counts"]["available"] == 2


def test_successful_lend_is_one_world_not_double_hung(client):
    r = client.post("/api/items/1/lend", json={"borrower": "邻居乙", "due_date": "2026-12-31"})
    assert r.status_code == 200
    loan_id = r.json()["loan_id"]

    b = client.get("/api/board").json()
    # 成功后：可借栏消失、在借栏出现，不得两栏同时挂着。
    assert 1 not in _ids(b["available"])
    assert 1 not in _ids(b["blocked"])
    active_ids = {l["item_id"] for l in b["active"] + b["overdue"]}
    assert 1 in active_ids
    assert b["counts"]["available"] == 1

    # 物主栏同一资格世界：on_loan，而不是仍按 available 标 lendable。
    items = {i["id"]: i for i in client.get("/api/items").json()}
    assert items[1]["lend_status"] == "on_loan"
    assert items[1]["status"] == "on_loan"
    assert loan_id > 0


def test_mutex_blocks_second_lend_but_not_other_items(client):
    assert client.post("/api/items/1/lend",
                       json={"borrower": "邻居乙", "due_date": "2026-12-31"}).status_code == 200
    # 同一物品再借被互斥挡住……
    r = client.post("/api/items/1/lend", json={"borrower": "邻居丙", "due_date": "2026-12-31"})
    assert r.status_code == 409
    assert r.json()["detail"] == "already_on_loan"
    # ……但不挡折叠桌这种别的正常物品。
    assert client.post("/api/items/2/lend",
                       json={"borrower": "邻居丙", "due_date": "2026-12-31"}).status_code == 200


def test_orphan_active_loan_keeps_item_off_available_shelf(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.main import app, connect
    with TestClient(app) as client:
        # 直接构造坏形态：items 仍 available，但已有 active 借单（孤儿借单）。
        c = connect()
        iid = c.execute(
            "INSERT INTO items(title,owner,status,data_quality) VALUES (?,?,?,?)",
            ("梯子", "老吴", "available", "clean")).lastrowid
        c.execute(
            "INSERT INTO loans(item_id,borrower,status,due_date,lent_at) VALUES (?,?,?,?,?)",
            (iid, "邻居丁", "active", "2026-12-31",
             datetime.now(timezone.utc).isoformat()))
        c.commit(); c.close()

        b = client.get("/api/board").json()
        assert iid not in _ids(b["available"])
        assert iid in _ids(b["blocked"])
        assert b["counts"]["available"] == 2  # 不把这种脏形态加数进可借

        r = client.post(f"/api/items/{iid}/lend",
                        json={"borrower": "邻居戊", "due_date": "2026-12-31"})
        assert r.status_code == 409
        assert r.json()["detail"] == "already_on_loan"


def test_owner_missing_clean_is_blocked_and_zero_loan_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.main import app, connect
    with TestClient(app) as client:
        c = connect()
        iid = c.execute(
            "INSERT INTO items(title,owner,status,data_quality) VALUES (?,?,?,?)",
            ("无主锤子", "", "available", "clean")).lastrowid
        c.commit(); c.close()

        b = client.get("/api/board").json()
        assert iid in _ids(b["blocked"])
        assert iid not in _ids(b["available"])

        r = client.post(f"/api/items/{iid}/lend",
                        json={"borrower": "邻居己", "due_date": "2026-12-31"})
        assert r.status_code == 409
        assert r.json()["detail"] == "owner_missing"

        conn = _raw_conn()
        assert conn.execute(
            "SELECT COUNT(*) c FROM loans WHERE item_id=?", (iid,)).fetchone()["c"] == 0
        conn.close()


def test_return_moves_item_back_to_available(client):
    lid = client.post("/api/items/1/lend",
                      json={"borrower": "邻居乙", "due_date": "2026-12-31"}).json()["loan_id"]
    assert client.post(f"/api/loans/{lid}/return", json={}).status_code == 200
    b = client.get("/api/board").json()
    assert 1 in _ids(b["available"])
    assert b["counts"]["available"] == 2
