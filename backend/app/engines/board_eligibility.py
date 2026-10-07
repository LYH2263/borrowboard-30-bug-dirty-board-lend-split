"""看板分区与借出闸共用 borrow_rules.lend_eligibility，叠读只允许一个资格世界。"""

def partition_available(pool: list) -> tuple:
    """把 status=available 的注解物品分成 (可借, 暂不可借) 两栏。

    可借 = 档案合格（有主且 data_quality=clean）且没有 active 借单；
    其余（脏物/无主/已有在借）一律落 blocked。计数与栏位同源，
    可借栏里不可能再出现"借出通过"会被拒的物品。
    """
    available, blocked = [], []
    for it in pool:
        if (it.get("eligible")
                and it.get("status") == "available"
                and not it.get("active_loans")):
            available.append(it)
        else:
            blocked.append(it)
    return available, blocked


def lend_gate_item(item: dict) -> dict:
    """借出闸入参的拷贝，避免闸内修改污染行数据。"""
    return dict(item)
