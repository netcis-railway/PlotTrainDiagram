"""Train SEQ is an ordered identity sequence, independent of worksheet row order."""


def sequence_problem(values):
    """Return (message, index in sorted values), allowing any positive start."""
    ordered = sorted(values)
    for index, value in enumerate(ordered):
        if type(value) is not int or value < 1 or value > 2147483647:
            return "列车SEQ须为正整数", index
        if not index:
            continue
        previous = ordered[index - 1]
        if value == previous:
            return f"列车SEQ编号重复：{value}；须唯一且连续，起号可为任意正整数", index
        if value != previous + 1:
            missing = str(previous + 1) if value == previous + 2 else f"{previous + 1}至{value - 1}"
            return (
                f"列车SEQ不连续：{previous}之后为{value}，缺少{missing}；不要求从1起号或按表格行序排列",
                index,
            )
    return None
