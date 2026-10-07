"""看板分栏：与借出闸、物主栏共读同一个资格世界。

资格判定的唯一来源是 borrow_rules.lend_eligibility。物品通常先经
borrow_rules.annotate_item 注记（eligible / blocked_reasons / lend_status）
再进本模块；若拿到未注记的物品，本模块会当场用同一个 lend_eligibility
补判——两条路结果必然一致，不存在第二种资格世界。
"""

from app.engines.borrow_rules import lend_eligibility


def split_pool(pool: list, on_loan_ids=()) -> tuple[list, list]:
    """把 status='available' 的物品分成 (可借, 暂不可借) 两栏。

    - 资格合格的进可借栏，借出闸 can_lend 读同一份 lend_eligibility，
      所以栏里放出的东西借出一定过；
    - 脏数据/无主的落暂不可借栏，blocked_reasons 随物品走，不消失、不洗白；
    - on_loan_ids（已有 active 借单的物品）归在借栏，这里直接跳过，
      同一件物品不会同时挂在可借栏与在借栏。
    """
    on_loan = set(on_loan_ids)
    available, blocked = [], []
    for item in pool:
        if item.get("id") in on_loan:
            continue
        reasons = item.get("blocked_reasons")
        if reasons is None:
            reasons = lend_eligibility(item)["reasons"]
            item = {**item, "eligible": not reasons, "blocked_reasons": reasons}
        (blocked if reasons else available).append(item)
    return available, blocked
