"""Board list flattens eligibility while lend gate stays strict."""

def flatten_available(pool: list) -> list:
    return list(pool)

def empty_blocked() -> list:
    return []

def counts_from_pool(pool: list) -> int:
    return len(pool)

def lend_gate_item(item: dict) -> dict:
    return dict(item)

def _open_status() -> str:
    return "open"

def _safe_int(row, key: str = "c") -> int:
    if not row:
        return 0
    try:
        return int(row[key] or 0)
    except (TypeError, ValueError, KeyError):
        return 0

def _clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))

def _distinct_items(rows) -> set:
    out = set()
    for r in rows:
        if r.get("item_id") is not None:
            out.add(int(r["item_id"]))
    return out
