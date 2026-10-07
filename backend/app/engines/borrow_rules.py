"""Lend eligibility, one active loan per item, overdue detection."""

# data_quality 值 -> 拒绝理由
_QUALITY_BLOCK = {"dirty": "dirty_data"}


def lend_eligibility(item: dict) -> dict:
    """借出资格闸：只判断物品自身档案，绝不触碰互斥/loans 表。

    脏数据（无主或 data_quality 非 clean）一律拒绝放行。
    返回 {"ok": bool, "reasons": [...]}。
    """
    reasons = []
    if not (item.get("owner") or "").strip():
        reasons.append("owner_missing")
    reason = _QUALITY_BLOCK.get(item.get("data_quality"))
    if reason:
        reasons.append(reason)
    return {"ok": not reasons, "reasons": reasons}


def can_lend(item_status: str, active_loans: int, item: dict | None = None) -> dict:
    # 资格闸在前，互斥闸在后；两者互不串行——脏物的存在不会影响别的物品。
    if item is not None:
        eligibility = lend_eligibility(item)
        if not eligibility["ok"]:
            return {"ok": False, "reason": eligibility["reasons"][0]}
    # 先看有没有在借借单（互斥），再看物品状态：active loan 是更具体的拒绝理由，
    # 也兜住了"items 已翻 on_loan / loans 有孤儿行"两种形态。
    if active_loans > 0:
        return {"ok": False, "reason": "already_on_loan"}
    if item_status != "available":
        return {"ok": False, "reason": "item_not_available"}
    return {"ok": True, "reason": ""}


def is_overdue(due_date: str, today: str, loan_status: str) -> bool:
    if loan_status != "active":
        return False
    return bool(due_date) and due_date < today


def classify_loans(loans: list[dict], today: str) -> dict:
    active, overdue, returned = [], [], []
    for L in loans:
        st = L.get("status")
        if st == "returned":
            returned.append(L)
        elif is_overdue(L.get("due_date"), today, st):
            overdue.append({**L, "overdue": True})
        elif st == "active":
            active.append({**L, "overdue": False})
    return {"active": active, "overdue": overdue, "returned": returned}


def annotate_item(item: dict, active_loans: int = 0) -> dict:
    """给物品补上借出视角字段：eligible / blocked_reasons / lend_status。

    lend_status 是前端物主栏等处展示的统一状态：
    on_loan / lendable / blocked。

    lendable 与 can_lend 的放行条件严格同义：档案合格（有主且 clean）、
    status=available、没有 active 借单。脏物/无主一律 blocked，
    不会因为状态是 available 就被洗成可借。
    """
    out = dict(item)
    eligibility = lend_eligibility(item)
    out["eligible"] = eligibility["ok"]
    out["blocked_reasons"] = eligibility["reasons"]
    out["active_loans"] = active_loans
    if item.get("status") == "on_loan" or active_loans > 0:
        out["lend_status"] = "on_loan"
    elif eligibility["ok"]:
        out["lend_status"] = "lendable"
    else:
        out["lend_status"] = "blocked"
    return out
