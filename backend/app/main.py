from datetime import date, datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from app import seed
from app.db import connect
from app.engines.borrow_rules import annotate_item, can_lend, classify_loans
from app.engines import board_eligibility as be

app = FastAPI(title="Borrowboard", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def _startup(): seed.init_db()

@app.get("/api/health")
def health(): return {"ok": True, "project": "borrowboard"}

@app.get("/api/items")
def items():
    c = connect()
    counts = active_loan_counts(c)
    rows = [annotate_item(dict(r), counts.get(r["id"], 0))
            for r in c.execute("SELECT * FROM items ORDER BY id")]
    c.close()
    return rows


def active_loan_counts(c) -> dict:
    """每个物品当前的 active 借单数——互斥闸与各栏展示共用同一份计数。"""
    return {r["item_id"]: r["c"]
            for r in c.execute(
                "SELECT item_id, COUNT(*) c FROM loans WHERE status='active' GROUP BY item_id")}


@app.get("/api/board")
def board():
    c = connect()
    counts = active_loan_counts(c)
    # status=available 的物品再过一遍资格闸，资格世界与 /api/items、lend 端点
    # 完全同源：合格且无在借的进可借栏，脏物/无主/已有在借的落 blocked 分区，
    # 三处（可借栏/物主栏/顶细条）只认这一种分法。
    pool = [annotate_item(dict(r), counts.get(r["id"], 0))
            for r in c.execute("SELECT * FROM items WHERE status='available'")]
    available, blocked = be.partition_available(pool)
    loans = [dict(r) for r in c.execute(
        """SELECT loans.*, items.title FROM loans JOIN items ON items.id=loans.item_id
           WHERE loans.status='active'""")]
    c.close()
    cls = classify_loans(loans, date.today().isoformat())
    return {
        "available": available,
        "blocked": blocked,
        "active": cls["active"],
        "overdue": cls["overdue"],
        "counts": {
            "available": len(available),
            "blocked": len(blocked),
            "active": len(cls["active"]),
            "overdue": len(cls["overdue"]),
        },
    }

class ItemIn(BaseModel):
    title: str
    owner: str

@app.post("/api/items")
def add_item(body: ItemIn):
    c = connect()
    cur = c.execute("INSERT INTO items(title,owner,status,data_quality) VALUES (?,?,?,?)",
                    (body.title, body.owner, "available", "clean"))
    c.commit(); iid = cur.lastrowid; c.close(); return {"id": iid}

class LendIn(BaseModel):
    borrower: str
    due_date: str

@app.post("/api/items/{iid}/lend")
def lend(iid: int, body: LendIn):
    c = connect()
    # 整个"判资格 → 写借单 → 翻状态"在一个事务里：要么完整成功，要么零写入，
    # 不可能留下"可借栏已空 / items 已翻转而 loans 零行"的半状态。
    c.execute("BEGIN IMMEDIATE")
    try:
        item = c.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
        if not item:
            c.execute("ROLLBACK"); c.close(); raise HTTPException(404, "item")
        active = c.execute(
            "SELECT COUNT(*) c FROM loans WHERE item_id=? AND status='active'",
            (iid,)).fetchone()["c"]
        # 资格闸（脏物/无主）先于互斥闸；拒绝时回滚，下面的 INSERT/UPDATE
        # 一条都不执行——不会把 data_quality 改成 clean，也不会补写 owner。
        check = can_lend(item["status"], active, item=be.lend_gate_item(dict(item)))
        if not check["ok"]:
            c.execute("ROLLBACK"); c.close(); raise HTTPException(409, check["reason"])
        cur = c.execute(
            "INSERT INTO loans(item_id,borrower,status,due_date,lent_at) VALUES (?,?,?,?,?)",
            (iid, body.borrower, "active", body.due_date,
             datetime.now(timezone.utc).isoformat()))
        c.execute("UPDATE items SET status='on_loan' WHERE id=?", (iid,))
        c.execute("COMMIT")
    except HTTPException:
        raise
    except Exception:
        c.execute("ROLLBACK")
        raise
    finally:
        c.close()
    return {"loan_id": cur.lastrowid}

@app.post("/api/loans/{lid}/return")
def return_loan(lid: int):
    c = connect()
    loan = c.execute("SELECT * FROM loans WHERE id=?", (lid,)).fetchone()
    if not loan: c.close(); raise HTTPException(404, "loan")
    if loan["status"] != "active":
        c.close(); raise HTTPException(400, "not_active")
    c.execute("UPDATE loans SET status='returned', returned_at=? WHERE id=?",
              (datetime.now(timezone.utc).isoformat(), lid))
    c.execute("UPDATE items SET status='available' WHERE id=?", (loan["item_id"],))
    c.commit(); c.close(); return {"ok": True}

@app.get("/api/loans")
def loans():
    c = connect()
    rows = [dict(r) for r in c.execute(
        "SELECT loans.*, items.title FROM loans JOIN items ON items.id=loans.item_id ORDER BY loans.id DESC")]
    c.close()
    return classify_loans(rows, date.today().isoformat())

@app.get("/api/settings")
def settings():
    c = connect(); rows = {r["key"]: r["value"] for r in c.execute("SELECT * FROM settings")}; c.close(); return rows
