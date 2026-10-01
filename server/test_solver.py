"""求解器与超限段检测的测试（含暴力枚举对照）。"""

import itertools
import random
import sys
import time

from solver import solve_repair
from weave import find_violations


def brute_force(rows, cols, k, grid, locks):
    """暴力枚举所有未锁定格取值，返回 (最少翻转数, 字典序最小展开序列) 或 None。"""
    locked = set(map(tuple, locks))
    free = [(r, c) for r in range(rows) for c in range(cols)
            if (r, c) not in locked]
    best = None
    for bits in itertools.product((0, 1), repeat=len(free)):
        g = [row[:] for row in grid]
        for (r, c), b in zip(free, bits):
            g[r][c] = b
        if find_violations(g, rows, cols, k):
            continue
        flips = sum(b != grid[r][c] for (r, c), b in zip(free, bits))
        flat = tuple(v for row in g for v in row)
        if best is None or (flips, flat) < (best[0], best[1]):
            best = (flips, flat)
    return best


def flat(grid):
    return tuple(v for row in grid for v in row)


def check_case(rows, cols, k, grid, locks, label):
    expected = brute_force(rows, cols, k, grid, locks)
    got = solve_repair(rows, cols, k, grid, locks)
    if expected is None:
        assert got is None, f"{label}: 应无解但解出 {got}"
        print(f"  [OK] {label}: 无可行修补（与暴力一致）")
        return
    assert got is not None, f"{label}: 应有解但报无解"
    assert len(got["flips"]) == expected[0], (
        f"{label}: 翻转数 {len(got['flips'])} != 最优 {expected[0]}")
    assert flat(got["repaired"]) == expected[1], (
        f"{label}: 字典序不一致\n  got {flat(got['repaired'])}\n  exp {expected[1]}")
    # 解必须合法且尊重锁定
    assert not find_violations(got["repaired"], rows, cols, k)
    for (r, c) in locks:
        assert got["repaired"][r][c] == grid[r][c]
    print(f"  [OK] {label}: 翻转 {expected[0]} 格（与暴力一致）")


def main():
    print("== 固定用例 ==")
    check_case(2, 2, 1, [[0, 0], [0, 0]], [], "2x2 全0 K=1")
    check_case(2, 2, 1, [[0, 0], [0, 0]], [[0, 0], [0, 1]], "2x2 行锁定 -> 无解")
    check_case(4, 4, 1, [[0, 1, 0, 1], [1, 0, 1, 0],
                         [0, 1, 0, 1], [1, 0, 1, 0]], [], "4x4 平纹 K=1 已合法")
    check_case(4, 4, 2, [[0] * 4 for _ in range(4)], [], "4x4 全0 K=2")
    check_case(4, 4, 2, [[0] * 4 for _ in range(4)],
               [[0, 0], [1, 1], [2, 2], [3, 3]], "4x4 全0 K=2 对角锁定")
    check_case(1, 1, 1, [[0]], [], "1x1 必无解")
    check_case(1, 3, 1, [[0, 1, 0]], [], "1x3 必无解（列全同）")
    check_case(3, 1, 1, [[0], [1], [0]], [], "3x1 必无解（行全同）")
    check_case(4, 4, 100, [[0, 1, 0, 1], [1, 0, 1, 0],
                           [0, 1, 0, 1], [1, 0, 1, 0]], [], "K 极大时已合法")
    check_case(3, 3, 1, [[0, 1, 0], [1, 0, 1], [0, 1, 0]], [], "3x3 K=1 奇数环")

    print("== 超限段检测 ==")
    # 环向跨界：0 的段 {2,0} 长度为 2
    v = find_violations([[0, 1, 0]], 1, 3, 1)
    row_segs = [s for s in v if s["kind"] == "row"]
    assert len(row_segs) == 1 and sorted(map(tuple, row_segs[0]["cells"])) == [(0, 0), (0, 2)], v
    assert len([s for s in v if s["kind"] == "col"]) == 3  # 单列全同=无限
    # 全同行 -> 无限
    v = find_violations([[1, 1, 1]], 1, 3, 5)
    assert any(s["length"] is None for s in v if s["kind"] == "row")
    # 合法平纹无超限
    assert not find_violations([[0, 1], [1, 0]], 2, 2, 1)
    print("  [OK] 超限段检测（含跨界、全同、合法）")

    print("== 随机小网格对照暴力 ==")
    rng = random.Random(42)
    for i in range(60):
        rows = rng.randint(2, 5)
        cols = rng.randint(2, 4)
        k = rng.randint(1, 4)
        grid = [[rng.randint(0, 1) for _ in range(cols)] for _ in range(rows)]
        locks = [[r, c] for r in range(rows) for c in range(cols)
                 if rng.random() < 0.25]
        check_case(rows, cols, k, grid, locks,
                   f"随机#{i} {rows}x{cols} K={k} 锁{len(locks)}")

    print("== 大网格性能 ==")
    for k in (1, 2, 3, 5, 8, 16, 1000):
        rows, cols = 16, 8
        grid = [[rng.randint(0, 1) for _ in range(cols)] for _ in range(rows)]
        t0 = time.time()
        got = solve_repair(rows, cols, k, grid, [])
        dt = time.time() - t0
        assert got is not None
        assert not find_violations(got["repaired"], rows, cols, k)
        print(f"  [OK] 16x8 K={k}: 翻转 {len(got['flips'])} 格, {dt:.2f}s")
        assert dt < 10, "求解超时"

    # 大量锁定 + 大网格
    grid = [[rng.randint(0, 1) for _ in range(8)] for _ in range(16)]
    locks = [[r, c] for r in range(16) for c in range(8) if rng.random() < 0.5]
    t0 = time.time()
    got = solve_repair(16, 8, 3, grid, locks)
    dt = time.time() - t0
    if got is not None:
        assert not find_violations(got["repaired"], 16, 8, 3)
        for (r, c) in locks:
            assert got["repaired"][r][c] == grid[r][c]
        print(f"  [OK] 16x8 K=3 半锁定: 翻转 {len(got['flips'])} 格, {dt:.2f}s")
    else:
        print(f"  [OK] 16x8 K=3 半锁定: 无解, {dt:.2f}s")

    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
