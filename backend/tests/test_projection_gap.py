"""投影缺口夹具：齐绿格 / 名册拧花 / 投影戳缺 / 晋升半截 四路分测 + 旁读面。

定臂：
- 齐绿必须能由 名册 ∪ 投影戳 ∪ 四格 ∪ 审计 重放验证；拧花不得维持齐绿。
- 环境分布格允许先行变绿，但名册汇总或投影任务戳不一致时必须挂投影缺口；
  缺口未清，对账不得当已对齐。
- 总览页、名册页、投影旁读、对账、审计共用同一份缺口判定。
"""
from __future__ import annotations

import os
import sqlite3
import threading

import pytest

DB_PATH = "/tmp/sg_pytest_gap.db"
os.environ["SHIPGATE_DB"] = DB_PATH

from fastapi.testclient import TestClient  # noqa: E402

from app.config import DB_PATH as APP_DB_PATH  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed_if_empty  # noqa: E402

# 多测试文件共存时 app.config 只绑定一次：以应用实际库路径为准，避免夹具连错库
DB_PATH = str(APP_DB_PATH)


@pytest.fixture()
def client():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    seed_if_empty()
    with TestClient(app) as c:
        yield c


def raw_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def seed_release_id(client):
    return client.get("/api/发版单").json()[0]["编号"]


def env_id(code):
    with raw_conn() as conn:
        return conn.execute("SELECT id FROM environments WHERE code=?", (code,)).fetchone()["id"]


def app_id(name="结算网关"):
    with raw_conn() as conn:
        return conn.execute("SELECT id FROM apps WHERE name=?", (name,)).fetchone()["id"]


def gaps_everywhere(client):
    """五个读面同一时刻的缺口判定，必须同指。"""
    return {
        "总览": client.get("/api/总览").json(),
        "名册": client.get("/api/应用名册").json(),
        "对账": client.get("/api/对账").json(),
        "投影旁读": client.get("/api/分布事件").json(),
        "审计": client.get("/api/审计").json(),
    }


def assert_aligned_everywhere(views):
    for name, body in views.items():
        assert body["对齐"] is True, f"{name}应对齐"
        assert body["投影缺口"]["有缺口"] is False, f"{name}不应有缺口"
        assert body["投影缺口"]["差额总数"] == 0, f"{name}差额应归零"
        assert body["投影缺口"]["账本位点差"] == 0, f"{name}账本位点应齐"


def assert_gap_everywhere(views):
    for name, body in views.items():
        assert body["对齐"] is False, f"{name}缺口未清不得当已对齐"
        assert body["投影缺口"]["有缺口"] is True, f"{name}必须挂投影缺口"


# 夹具一（齐绿格）：放行后名册∪投影戳∪四格∪审计同指，齐绿可重放
def test_all_green_replayable_across_pages(client):
    rid = seed_release_id(client)
    client.post(f"/api/发版单/{rid}/晋升", json={"目标环境": "预"})
    client.post(f"/api/发版单/{rid}/晋升", json={"目标环境": "产"})

    views = gaps_everywhere(client)
    assert_aligned_everywhere(views)
    # 五面同戳：同一投影任务号/刷新戳/事件位点
    stamps = {name: body["投影"] for name, body in views.items()}
    assert len({json_of(s) for s in stamps.values()}) == 1
    # 四格：该单在产，格数之和恒等于发版单总数（无半截格）
    counts = views["总览"]["环境分布"]["计数"]
    assert counts["产"] == 1 and counts["测"] == 0
    total = len(client.get("/api/发版单").json())
    assert sum(counts.values()) == total
    # 名册汇总与四格同指：产列即放行版本
    roster = {(r["应用"], r["环境"]): r["版本"] for r in views["名册"]["名册"]}
    assert roster[("结算网关", "产")] == "1.3.0"
    # 审计可重放齐绿证据链：入闸→晋升预→晋升产→每次重投影任务留痕
    actions = [row["动作"] for row in views["审计"]["流水"]]
    assert "晋升到产" in actions and "晋升到预" in actions
    assert sum(1 for a in actions if a.startswith("重投影任务")) >= 3


def json_of(d):
    return (d["投影任务号"], d["刷新戳"], d["事件位点"])


# 夹具二（名册拧花）：缓存被拨乱后五面同挂缺口，重放后才准复绿
def test_roster_torn_hangs_gap_until_replay(client):
    rid = seed_release_id(client)
    client.post(f"/api/发版单/{rid}/晋升", json={"目标环境": "预"})
    # 人为拧花：名册预列刷成幽灵版本、发版单缓存环境拨空（无事件支撑）
    with raw_conn() as conn:
        conn.execute(
            "UPDATE app_env_versions SET version='9.9.9' WHERE app_id=? AND env_id=?",
            (app_id(), env_id("预")),
        )
        conn.execute("UPDATE releases SET current_env_id=NULL WHERE id=?", (rid,))

    views = gaps_everywhere(client)
    assert_gap_everywhere(views)
    # 缺口原因须点名名册与发版单两路差额
    reasons = "；".join(views["总览"]["投影缺口"]["原因"])
    assert "名册版本差额" in reasons and "发版单环境差额" in reasons
    # 四格仍由事件真源重放：该单在预，拧花不得把格拨绿到别处
    assert views["总览"]["环境分布"]["计数"]["预"] == 1
    # 缺口未清，对账不得当已对齐
    assert views["对账"]["对账差额"]["差额总数"] >= 2

    client.post("/api/投影/重放", json={})
    assert_aligned_everywhere(gaps_everywhere(client))
    roster = {(r["应用"], r["环境"]): r["版本"] for r in client.get("/api/应用名册").json()["名册"]}
    assert roster[("结算网关", "预")] == "1.3.0"


# 夹具三（投影戳缺）：账本被回拨/缺失时挂缺口，重放重建账本
def test_projection_stamp_missing_hangs_gap(client):
    event_total = client.get("/api/分布事件").json()["差额"]["事件总数"]
    assert event_total > 0
    with raw_conn() as conn:
        conn.execute("DELETE FROM projection_meta")

    views = gaps_everywhere(client)
    assert_gap_everywhere(views)
    gap = views["总览"]["投影缺口"]
    # 账本缺失 => 位点差等于全量事件数，原因须点名账本
    assert gap["账本位点差"] == event_total
    assert any("账本" in r for r in gap["原因"])
    # 名册缓存本身未分叉：缺口只由戳缺引起
    assert views["对账"]["对账差额"]["差额总数"] == 0

    out = client.post("/api/投影/重放", json={}).json()
    assert out["投影"]["事件位点"] == event_total
    assert_aligned_everywhere(gaps_everywhere(client))


# 夹具四（晋升半截/发版环境写口半截）：事件落库但投影未跑，格先行变绿也必须挂缺口
def test_half_write_at_env_write_port_hangs_gap(client):
    rid = seed_release_id(client)
    before = client.get("/api/总览").json()["投影"]
    # 半截写口：只追加晋升事件（真源），不跑重投影——模拟晋升同事务被截断
    with raw_conn() as conn:
        conn.execute(
            """
            INSERT INTO distribution_events(release_id, app_id, from_env_id, to_env_id, kind, version, created_at, note)
            VALUES (?, ?, ?, ?, '晋升', '1.3.0', '2026-01-01 00:00:00', '半截写入')
            """,
            (rid, app_id(), env_id("测"), env_id("预")),
        )

    views = gaps_everywhere(client)
    assert_gap_everywhere(views)
    gap = views["总览"]["投影缺口"]
    # 账本滞后恰好 1 条事件；名册缓存尚未投影新版本
    assert gap["账本位点差"] == 1
    assert gap["差额总数"] >= 1
    # 格允许先行变绿（重放真源已含半截事件），但缺口必须挂着，不得当齐绿
    assert views["总览"]["环境分布"]["计数"]["预"] == 1
    assert views["总览"]["投影"] == before  # 戳不得装前进

    client.post("/api/投影/重放", json={})
    views = gaps_everywhere(client)
    assert_aligned_everywhere(views)
    roster = {(r["应用"], r["环境"]): r["版本"] for r in views["名册"]["名册"]}
    assert roster[("结算网关", "预")] == "1.3.0"
    assert client.get(f"/api/发版单/{rid}").json()["当前环境"] == "预"


# 夹具五（跨环名册旁读）：单环拧花只点名该环，邻环旁读不受污染
def test_cross_env_roster_side_read(client):
    with raw_conn() as conn:
        conn.execute(
            "UPDATE app_env_versions SET version='7.7.7' WHERE app_id=? AND env_id=?",
            (app_id(), env_id("产")),
        )
    views = gaps_everywhere(client)
    assert_gap_everywhere(views)
    diffs = views["对账"]["对账差额"]["名册版本差额"]
    # 差额只落在产列，真源版本为种子基线
    assert [(d["应用"], d["环境"]) for d in diffs] == [("结算网关", "产")]
    assert diffs[0]["真源版本"] == "1.0.0"
    # 邻环（测/预）旁读仍与真源一致
    roster = {(r["应用"], r["环境"]): r["版本"] for r in views["名册"]["名册"]}
    assert roster[("结算网关", "测")] == "1.3.0"
    assert roster[("结算网关", "预")] == "1.1.0"

    client.post("/api/投影/重放", json={})
    assert_aligned_everywhere(gaps_everywhere(client))


# 夹具六（维护时段旁读）：窗关硬拒晋升，不留半截事件、不起缺口、戳不动
def test_maintenance_window_side_read(client):
    rid = seed_release_id(client)
    before = client.get("/api/总览").json()["投影"]
    event_total = client.get("/api/分布事件").json()["差额"]["事件总数"]
    client.post("/api/放行窗/切换", json={"环境": "预", "状态": "窗关"})

    r = client.post(f"/api/发版单/{rid}/晋升", json={"目标环境": "预"})
    assert r.status_code == 400 and "放行窗已关" in r.json()["detail"]
    # 拒绝不留半截：事件总数不变、投影戳不动、五面仍旧对齐
    assert client.get("/api/分布事件").json()["差额"]["事件总数"] == event_total
    views = gaps_everywhere(client)
    assert_aligned_everywhere(views)
    assert views["总览"]["投影"] == before
    assert views["总览"]["环境分布"]["计数"]["测"] == 1


# 夹具七（在途分布格×并发刷新）：晋升与总览刷新交错，任何一次响应缺口判定自洽
def test_concurrent_promote_refresh_gap_consistent(client):
    rid = seed_release_id(client)
    total = len(client.get("/api/发版单").json())
    errors: list[str] = []
    stop = threading.Event()

    def promoter():
        for target in ("预", "产"):
            r = client.post(f"/api/发版单/{rid}/晋升", json={"目标环境": target})
            if r.status_code not in (200, 400):
                errors.append(f"promote {target} -> {r.status_code}")
        stop.set()

    def reader():
        while not stop.is_set():
            ov = client.get("/api/总览")
            if ov.status_code != 200:
                continue
            body = ov.json()
            gap = body["投影缺口"]
            # 不变量：单次响应内 对齐 ⟺ 无缺口；格数之和恒等于发版单总数
            if body["对齐"] != (not gap["有缺口"]):
                errors.append("对齐标志与缺口判定不自洽")
            if sum(body["环境分布"]["计数"].values()) != total:
                errors.append("在途分布格半截")

    t1 = threading.Thread(target=promoter)
    t2 = threading.Thread(target=reader)
    t1.start(); t2.start()
    t1.join(); t2.join()
    assert errors == []
    # 收束：并发写者退场后五面必须收敛对齐，不得长期分叉无缺口
    assert_aligned_everywhere(gaps_everywhere(client))
