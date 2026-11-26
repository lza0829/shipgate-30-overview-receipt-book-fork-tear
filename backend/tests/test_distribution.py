"""环境分布真源夹具：总览/名册/晋升/发版单/对账/审计同源与纠偏。

定臂：分布事件流 distribution_events 重投影为唯一真源；
名册 app_env_versions 与发版单 current_env_id 仅为投影缓存。
"""
from __future__ import annotations

import os
import sqlite3
import threading

import pytest

# 必须在导入 app 之前指定隔离库
DB_PATH = "/tmp/sg_pytest.db"
os.environ["SHIPGATE_DB"] = DB_PATH

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.seed import seed_if_empty  # noqa: E402


@pytest.fixture()
def client():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    seed_if_empty()  # 重新建表并播种（含首次重投影）
    with TestClient(app) as c:
        yield c


def raw_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def roster_map(client):
    rows = client.get("/api/应用名册").json()["名册"]
    return {(r["应用"], r["环境"]): r["版本"] for r in rows}


def dist_counts(client):
    return client.get("/api/总览").json()["环境分布"]["计数"]


def seed_release_id(client, serial_like="发"):
    rows = client.get("/api/发版单").json()
    return rows[0]["编号"]


# 夹具一：晋升后刷总览——四格、名册三环境列、发版单当前环境、对账、事件流同源
def test_promote_then_all_pages_agree(client):
    rid = seed_release_id(client)
    assert dist_counts(client) == {"未落地": 0, "测": 1, "预": 0, "产": 0}

    client.post(f"/api/发版单/{rid}/晋升", json={"目标环境": "预"})
    ov = client.get("/api/总览").json()
    assert ov["环境分布"]["计数"] == {"未落地": 0, "测": 0, "预": 1, "产": 0}
    assert roster_map(client)[("结算网关", "预")] == "1.3.0"
    rel = client.get(f"/api/发版单/{rid}").json()
    assert rel["当前环境"] == "预"
    recon = client.get("/api/对账").json()
    assert recon["对账差额"]["差额总数"] == 0
    # 四格、名册、对账、审计同一投影任务号/刷新戳
    stamp = ov["投影"]
    assert stamp["事件位点"] == 8
    assert client.get("/api/应用名册").json()["投影"] == stamp
    assert recon["投影"] == stamp
    assert client.get("/api/审计").json()["投影"] == stamp

    client.post(f"/api/发版单/{rid}/晋升", json={"目标环境": "产"})
    ov = client.get("/api/总览").json()
    assert ov["环境分布"]["计数"] == {"未落地": 0, "测": 0, "预": 0, "产": 1}
    assert roster_map(client)[("结算网关", "产")] == "1.3.0"
    rel = client.get(f"/api/发版单/{rid}").json()
    assert rel["当前环境"] == "产" and rel["状态"] == "已放行"
    assert client.get("/api/对账").json()["对账差额"]["差额总数"] == 0
    # 事件流可重放定位：入测→晋升预→晋升产
    kinds = [e["类型"] for e in client.get("/api/分布事件").json()["事件流"]]
    assert kinds.count("晋升") == 2 and kinds[0] == "基线落地"


# 夹具二：缺事件/缓存分叉——对账暴露差额，手动重放以事件流纠偏，不长期双数
def test_missing_event_cache_drift_repairs(client):
    rid = seed_release_id(client)
    client.post(f"/api/发版单/{rid}/晋升", json={"目标环境": "预"})
    # 人为制造半截：只改缓存、不补事件（模拟事件缺失导致的名册/格拧花）
    with raw_conn() as conn:
        env_pre = conn.execute("SELECT id FROM environments WHERE code='预'").fetchone()["id"]
        app1 = conn.execute("SELECT id FROM apps WHERE name='结算网关'").fetchone()["id"]
        conn.execute(
            "UPDATE app_env_versions SET version='9.9.9' WHERE app_id=? AND env_id=?",
            (app1, env_pre),
        )
        conn.execute("UPDATE releases SET current_env_id=NULL WHERE id=?", (rid,))
    recon = client.get("/api/对账").json()
    diffs = recon["对账差额"]
    assert diffs["差额总数"] >= 2
    assert any(d["环境"] == "预" and d["真源版本"] == "1.3.0" for d in diffs["名册版本差额"])
    assert any(d["发版单编号"] == rid for d in diffs["发版单环境差额"])
    # 真源分布不受缓存污染：重放仍说该单在预
    assert dist_counts(client)["预"] == 1

    repaired = client.post("/api/投影/重放", json={}).json()
    assert repaired["重放前差额"]["差额总数"] >= 2
    assert repaired["重放后差额"]["差额总数"] == 0
    assert repaired["投影"]["纠偏行数"] >= 2
    assert roster_map(client)[("结算网关", "预")] == "1.3.0"
    assert client.get(f"/api/发版单/{rid}").json()["当前环境"] == "预"
    assert client.get("/api/对账").json()["对账差额"]["差额总数"] == 0


# 夹具三：空事件集——重放结果为全空名册、发版单全部未落地，不保留旧缓存
def test_empty_event_set_semantics(client):
    with raw_conn() as conn:
        conn.execute("DELETE FROM distribution_events")
    out = client.post("/api/投影/重放", json={}).json()
    assert out["重放后差额"]["差额总数"] == 0
    ov = client.get("/api/总览").json()
    assert ov["环境分布"]["计数"] == {"未落地": 1, "测": 0, "预": 0, "产": 0}
    for (_, _), ver in roster_map(client).items():
        assert ver == ""
    rel = client.get("/api/发版单").json()[0]
    assert rel["当前环境"] is None


# 夹具四：并发晋升与刷新——读端任何一次响应都不得出现半截/拧花状态
def test_concurrent_promote_and_refresh(client):
    rid = seed_release_id(client)
    total = len(client.get("/api/发版单").json())  # 本夹具不新建发版单，总数恒定
    errors: list[str] = []
    seen_tasks: list[int] = []
    seen_positions: list[int] = []
    stop = threading.Event()
    lock = threading.Lock()

    def promoter():
        for target in ("预", "产"):
            r = client.post(f"/api/发版单/{rid}/晋升", json={"目标环境": target})
            if r.status_code not in (200, 400):  # 400=并发下顺序校验，属正常拒绝
                errors.append(f"promote {target} -> {r.status_code}")
        stop.set()

    def reader():
        while not stop.is_set():
            ov = client.get("/api/总览")
            recon = client.get("/api/对账")
            roster = client.get("/api/应用名册")
            if not (ov.status_code == recon.status_code == roster.status_code == 200):
                continue
            o, rc, rs = ov.json(), recon.json(), roster.json()
            counts = o["环境分布"]["计数"]
            # 不变量1：单次响应内四格之和恒等于发版单总数，格不多不少（无半截格）
            if sum(counts.values()) != total:
                errors.append("bucket sum drift")
            # 不变量2：任何一次读取，缓存与事件流真源零分叉（同事务同命运，不可观察到双数）
            if rc["对账差额"]["差额总数"] != 0:
                errors.append("torn read: reconcile diff nonzero")
            # 不变量3/4：投影任务号与事件位点在观察序列上单调不减（只前进、不回闪旧分布）
            with lock:
                task = o["投影"]["投影任务号"]
                pos = o["投影"]["事件位点"]
                if seen_tasks and task < seen_tasks[-1]:
                    errors.append(f"projection task went backwards: {seen_tasks[-1]} -> {task}")
                if seen_positions and pos < seen_positions[-1]:
                    errors.append(f"event position went backwards: {seen_positions[-1]} -> {pos}")
                seen_tasks.append(task)
                seen_positions.append(pos)

    t1 = threading.Thread(target=promoter)
    t2 = threading.Thread(target=reader)
    t1.start(); t2.start()
    t1.join(); t2.join()
    assert errors == []
    assert dist_counts(client) == {"未落地": 0, "测": 0, "预": 0, "产": 1}
    # 最终代次所有页面同戳（无并发写者后必须收敛对齐）
    final = client.get("/api/总览").json()["投影"]
    assert client.get("/api/对账").json()["投影"] == final
    assert client.get("/api/应用名册").json()["投影"] == final
    assert client.get("/api/审计").json()["投影"] == final


# 夹具五：半截分布闪错——缓存与事件流拧花后必须能纠到选定真源，且不长期双数
def test_half_flash_converges_to_event_truth(client):
    rid = seed_release_id(client)  # 事件真源：该单在测
    with raw_conn() as conn:
        env_prod = conn.execute("SELECT id FROM environments WHERE code='产'").fetchone()["id"]
        app1 = conn.execute("SELECT id FROM apps WHERE name='结算网关'").fetchone()["id"]
        # 半截写入：名册产列被刷成幽灵版本、发版单缓存环境被拨到产，但无事件
        conn.execute(
            "INSERT INTO app_env_versions(app_id, env_id, version, updated_at) VALUES (?, ?, '5.0.0', '')"
            " ON CONFLICT(app_id, env_id) DO UPDATE SET version='5.0.0'",
            (app1, env_prod),
        )
        conn.execute("UPDATE releases SET current_env_id=? WHERE id=?", (env_prod, rid))
    # 闪错期间：真源四格仍说在测，缓存名册谎报产 5.0.0，对账差额如实暴露
    assert dist_counts(client)["测"] == 1 and dist_counts(client)["产"] == 0
    assert roster_map(client)[("结算网关", "产")] == "5.0.0"
    assert client.get("/api/对账").json()["对账差额"]["差额总数"] >= 2

    client.post("/api/投影/重放", json={})
    # 纠偏后：格与名册版本都回到事件真源，幽灵版本消失
    assert dist_counts(client) == {"未落地": 0, "测": 1, "预": 0, "产": 0}
    assert roster_map(client)[("结算网关", "产")] == "1.0.0"  # 种子基线版本
    assert client.get(f"/api/发版单/{rid}").json()["当前环境"] == "测"
    assert client.get("/api/对账").json()["对账差额"]["差额总数"] == 0


# 夹具六：金丝雀比例真源另立——分布重投影不动 canary_ratio
def test_canary_ratio_source_independent(client):
    apps = client.get("/api/应用").json()
    client.post(
        "/api/发版单",
        json={"应用编号": apps[1]["编号"], "目标版本": "2.0.0", "制品摘要": "sha256:x", "金丝雀比例": 25},
    )
    target = next(x for x in client.get("/api/发版单").json() if x["目标版本"] == "2.0.0")
    rid2 = target["编号"]
    assert target["金丝雀比例"] == 25
    client.post(f"/api/发版单/{rid2}/流水线", json={"流水线": "绿"})
    client.post(f"/api/发版单/{rid2}/入闸", json={})
    client.post(f"/api/发版单/{rid2}/晋升", json={"目标环境": "预"})
    client.post("/api/投影/重放", json={})
    again = next(x for x in client.get("/api/发版单").json() if x["编号"] == rid2)
    assert again["金丝雀比例"] == 25 and again["当前环境"] == "预"


# 夹具七：投影任务号单调递增、审计留痕，各页刷新戳对齐
def test_projection_task_monotonic_and_audit(client):
    rid = seed_release_id(client)
    t0 = client.get("/api/总览").json()["投影"]["投影任务号"]
    client.post(f"/api/发版单/{rid}/晋升", json={"目标环境": "预"})
    t1 = client.get("/api/总览").json()["投影"]["投影任务号"]
    client.post("/api/投影/重放", json={"备注": "巡检"})
    t2 = client.get("/api/总览").json()["投影"]["投影任务号"]
    assert t0 < t1 < t2
    flow = client.get("/api/审计").json()["流水"]
    assert any("重投影任务" in row["动作"] for row in flow)
    assert any(row["动作"] == "晋升到预" for row in flow)
