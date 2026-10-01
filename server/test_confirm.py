"""确认竞争（预览令牌）的集成测试：原子校验 + 版本绑定。

覆盖：
- 正常确认：版本只递增一次、令牌消费、响应结构不变；
- 同一令牌重复/并发确认：仅一次生效，其余 409 且原稿不再变动；
- 甲乙基于同一原稿分别预览：甲确认后乙的旧令牌 409，不能覆盖；
- 草稿与预览输入不一致：409 且原稿不变；
- 过期令牌、非法请求：分别 409 / 400；
- 无解预览不返回令牌，不可确认；
- 成功确认后可基于新原稿重新预览、再次确认（版本连续递增）。
"""

import json
import os
import sys
import tempfile
import threading

_tmp = tempfile.mkdtemp(prefix="weave-test-")
os.environ["DB_PATH"] = os.path.join(_tmp, "weave.db")

import app as app_module  # noqa: E402

client = app_module.app.test_client()


def design_payload(overrides=None):
    state = client.get("/api/state").get_json()
    payload = {
        "rows": state["rows"], "cols": state["cols"],
        "grid": [row[:] for row in state["grid"]],
        "locks": [list(p) for p in state["locks"]], "k": state["k"],
    }
    if overrides:
        payload.update(overrides)
    return payload


def preview(payload):
    return client.post("/api/preview", json=payload)


def confirm(token, payload):
    return client.post("/api/confirm", json={"token": token, **payload})


def assert_grid(g1, g2, msg):
    assert g1 == g2, f"{msg}\n  got {g1}\n  exp {g2}"


def main():
    # 初始状态：版本 1
    st = client.get("/api/state").get_json()
    assert st["version"] == 1, st
    base_grid = [row[:] for row in st["grid"]]
    v1 = st["version"]

    # 甲、乙基于同一原稿各自准备一份草稿（内容相同），分别预览
    draft_a = design_payload()
    draft_b = json.loads(json.dumps(draft_a))
    pa = preview(draft_a).get_json()
    pb = preview(draft_b).get_json()
    assert pa["solvable"] and pa["token"], pa
    assert pb["solvable"] and pb["token"], pb
    assert pa["token"] != pb["token"]

    # 甲先确认：成功，结构为 {"state": ...}，版本 +1
    ra = confirm(pa["token"], draft_a)
    assert ra.status_code == 200, ra.get_json()
    state_a = ra.get_json()["state"]
    assert state_a["version"] == v1 + 1
    assert_grid(state_a["grid"], pa["repaired"], "甲确认应应用甲的修补结果")
    repaired_grid = [row[:] for row in state_a["grid"]]

    # 乙用旧令牌确认：409，原稿保持甲的结果，版本不递增
    rb = confirm(pb["token"], draft_b)
    assert rb.status_code == 409, rb.get_json()
    st = client.get("/api/state").get_json()
    assert st["version"] == v1 + 1
    assert_grid(st["grid"], repaired_grid, "乙的旧令牌不得覆盖甲的结果")

    # 甲的令牌重复确认：409（已消费），版本不变
    ra2 = confirm(pa["token"], draft_a)
    assert ra2.status_code == 409, ra2.get_json()
    st = client.get("/api/state").get_json()
    assert st["version"] == v1 + 1

    # 同一令牌并发确认：恰好一次生效
    draft = design_payload()
    tok = preview(draft).get_json()["token"]
    results = []

    def worker():
        results.append(confirm(tok, draft).status_code)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [200] + [409] * 7, results
    st = client.get("/api/state").get_json()
    assert st["version"] == v1 + 2, "并发确认只应令版本递增一次"
    ver = st["version"]

    # 草稿与预览输入不一致：409，原稿与版本均不变
    draft = design_payload()
    p = preview(draft).get_json()
    changed = json.loads(json.dumps(draft))
    changed["k"] = changed["k"] + 5
    r = confirm(p["token"], changed)
    assert r.status_code == 409, r.get_json()
    st = client.get("/api/state").get_json()
    assert st["version"] == ver
    # 不一致确认不消费令牌：与预览一致的草稿仍可确认成功
    r2 = confirm(p["token"], draft)
    assert r2.status_code == 200, r2.get_json()
    assert r2.get_json()["state"]["version"] == ver + 1
    ver += 1

    # 不存在的令牌：409
    r = confirm("deadbeef" * 4, design_payload())
    assert r.status_code == 409, r.get_json()

    # 非法请求：400（不改原稿）
    bad = design_payload({"k": 0})
    p = preview(bad)
    assert p.status_code == 400, p.get_json()
    p = preview(design_payload())
    tok = p.get_json()["token"]
    r = confirm(tok, bad)
    assert r.status_code == 400, r.get_json()
    r = confirm(tok, design_payload())  # 合法后仍可确认
    assert r.status_code == 200, r.get_json()
    ver += 1
    assert client.post("/api/confirm", json="not-an-object").status_code == 400
    assert client.post("/api/confirm", json={"token": ""}).status_code == 400

    # 无解预览：不返回令牌，无法确认，原稿不变
    unsolvable = design_payload({
        "rows": 2, "cols": 2,
        "grid": [[0, 0], [0, 0]],
        "locks": [[0, 0], [0, 1]], "k": 1,
    })
    r = preview(unsolvable)
    body = r.get_json()
    assert r.status_code == 200 and body["solvable"] is False
    assert "token" not in body
    st_before = client.get("/api/state").get_json()
    r = client.post("/api/confirm",
                    json={"token": "whatever", **unsolvable})
    assert r.status_code == 409
    st_after = client.get("/api/state").get_json()
    assert st_after["version"] == st_before["version"]

    # 旧令牌在原稿被直接确认推进后仍尝试确认：409（版本已变，输入或相同）
    draft = design_payload()
    tok1 = preview(draft).get_json()["token"]
    tok2 = preview(draft).get_json()["token"]
    assert confirm(tok1, draft).status_code == 200
    assert confirm(tok2, draft).status_code == 409  # 输入相同，但版本已变

    # API 结构稳定性
    st = client.get("/api/state").get_json()
    for key in ("rows", "cols", "grid", "locks", "k", "version", "violations"):
        assert key in st, key
    p = preview(design_payload()).get_json()
    for key in ("solvable", "token", "violations", "input",
                "repaired", "flips", "flipCount"):
        assert key in p, key

    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
