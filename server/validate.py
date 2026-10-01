"""设计稿（尺寸、格值、锁定格、K）的合法性校验。"""

MAX_ROWS = 16
MAX_COLS = 8


class ValidationError(ValueError):
    """输入不合法，携带面向用户的中文错误信息。"""


def _is_int(v):
    # JSON 里 bool 是 int 的子类，需排除；不接受浮点/字符串
    return isinstance(v, int) and not isinstance(v, bool)


def validate_design(payload):
    """校验并规范化设计稿，返回 (rows, cols, grid, locks, k)。

    不合法时抛出 ValidationError。
    """
    if not isinstance(payload, dict):
        raise ValidationError("请求体必须是 JSON 对象")

    rows, cols, k = payload.get("rows"), payload.get("cols"), payload.get("k")
    if not _is_int(rows) or not 1 <= rows <= MAX_ROWS:
        raise ValidationError(f"行数必须是 1~{MAX_ROWS} 的整数")
    if not _is_int(cols) or not 1 <= cols <= MAX_COLS:
        raise ValidationError(f"列数必须是 1~{MAX_COLS} 的整数")
    if not _is_int(k) or k < 1:
        raise ValidationError("最大浮长 K 必须是正整数")

    grid = payload.get("grid")
    if (not isinstance(grid, list) or len(grid) != rows
            or any(not isinstance(row, list) or len(row) != cols
                   for row in grid)):
        raise ValidationError("交织格必须是与尺寸一致的矩形数组")
    for r in range(rows):
        for c in range(cols):
            v = grid[r][c]
            if not _is_int(v) or v not in (0, 1):
                raise ValidationError(f"格值只能为 0 或 1（第 {r + 1} 行第 {c + 1} 列不合法）")

    locks = payload.get("locks")
    if not isinstance(locks, list):
        raise ValidationError("锁定格必须是坐标数组")
    norm_locks = set()
    for item in locks:
        if (not isinstance(item, list) or len(item) != 2
                or not _is_int(item[0]) or not _is_int(item[1])):
            raise ValidationError("锁定格坐标必须是 [行, 列] 整数对")
        r, c = item
        if not (0 <= r < rows and 0 <= c < cols):
            raise ValidationError(f"锁定格 ({r + 1}, {c + 1}) 越界")
        norm_locks.add((r, c))

    grid = [[int(v) for v in row] for row in grid]
    locks = sorted(norm_locks)
    return rows, cols, grid, locks, k


def canonical(rows, cols, grid, locks, k):
    """规范化后的可哈希表示，用于预览一致性比对。"""
    return {
        "rows": rows,
        "cols": cols,
        "grid": [list(row) for row in grid],
        "locks": [list(p) for p in sorted(map(tuple, locks))],
        "k": k,
    }
