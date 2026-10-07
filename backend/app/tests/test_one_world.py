"""资格世界唯一性回归测试：看板、借出闸、物主栏只读同一份资格。

种子数据：1 电钻(clean) 2 折叠桌(clean) 3 脏数据-无主(dirty,owner='') 4 已外借样例(on_loan)。
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with TestClient(app) as c:
        yield c


def _lend(client, item_id):
    return client.post(f"/api/items/{item_id}/lend",
                       json={"borrower": "邻居", "due_date": "2026-12-31"})


def test_board_splits_by_one_eligibility_world(client):
    b = client.get("/api/board").json()
    assert {i["id"] for i in b["available"]} == {1, 2}
    assert {i["id"] for i in b["blocked"]} == {3}
    reasons = set(b["blocked"][0]["blocked_reasons"])
    assert {"owner_missing", "dirty_data"} <= reasons
    # 顶细条计数必须与分栏结果一致，不能按未过滤的池子加数
    assert b["counts"]["available"] == len(b["available"]) == 2
    assert b["counts"]["blocked"] == len(b["blocked"]) == 1


def test_everything_board_offers_actually_lends(client):
    # 可借栏放出的每一件，借出都必须真的过——不允许"栏里有、loans 零行"
    b = client.get("/api/board").json()
    assert b["available"]
    for item in b["available"]:
        r = _lend(client, item["id"])
        assert r.status_code == 200, (item["id"], r.text)


def test_blocked_item_lend_fails_cleanly(client):
    before = client.get("/api/loans").json()
    r = _lend(client, 3)
    assert r.status_code == 409
    assert r.json()["detail"] == "owner_missing"
    assert client.get("/api/loans").json() == before  # loans 零增长
    # 物品不消失：仍在暂不可借栏挂着，且没被洗成 clean
    b = client.get("/api/board").json()
    assert {i["id"] for i in b["blocked"]} == {3}
    assert 3 not in {i["id"] for i in b["available"]}
    item = next(i for i in client.get("/api/items").json() if i["id"] == 3)
    assert item["data_quality"] == "dirty" and not item["owner"].strip()
    assert item["lend_status"] == "blocked"


def test_loaned_item_leaves_borrow_column(client):
    assert _lend(client, 1).status_code == 200
    b = client.get("/api/board").json()
    listed = {i["id"] for i in b["available"]} | {i["id"] for i in b["blocked"]}
    assert 1 not in listed  # 可借栏与在借栏不同时挂
    assert 1 in {l["item_id"] for l in b["active"] + b["overdue"]}
    assert b["counts"]["available"] == len(b["available"])


def test_drill_mutex_still_blocks_second_lend(client):
    assert _lend(client, 1).status_code == 200
    assert _lend(client, 1).status_code == 409  # 电钻互斥：同时在借只有一单
    loans = client.get("/api/loans").json()
    assert sum(1 for l in loans["active"] if l["item_id"] == 1) == 1


def test_return_restores_to_available(client):
    assert _lend(client, 2).status_code == 200
    loan_id = next(l for l in client.get("/api/loans").json()["active"]
                   if l["item_id"] == 2)["id"]
    assert client.post(f"/api/loans/{loan_id}/return").status_code == 200
    b = client.get("/api/board").json()
    assert 2 in {i["id"] for i in b["available"]}


def test_owners_page_reads_same_world(client):
    items = {i["id"]: i for i in client.get("/api/items").json()}
    assert items[1]["lend_status"] == "lendable"
    assert items[3]["lend_status"] == "blocked"
    assert set(items[3]["blocked_reasons"]) >= {"owner_missing", "dirty_data"}
