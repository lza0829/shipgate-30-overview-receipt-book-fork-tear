"""环境分布投影（事件溯源读模型）。

定臂：以分布事件流 distribution_events 重投影为环境分布唯一真源。
- app_env_versions（应用名册各环境版本）与 releases.current_env_id（发版单当前环境）
  都只是本投影维护的缓存，命令侧（晋升/入闸/回滚）不得直写。
- 总览四格、应用名册、对账全部经本模块读取同一份重放结果，禁止各算各的。
- 每次命令与投影在同一数据库事务内完成（同命运）；另有 rebuild_projection 显式纠偏口，
  缓存与事件流分叉时以事件流为准整体重写，不允许长期双数。
- 空事件集语义自洽：重放得到全空名册、全部发版单“未落地”，绝不保留旧缓存。
"""
from __future__ import annotations

from app.services.common import audit, now_str, ordered_envs

UNLANDED = "未落地"


def record_event(
    conn,
    *,
    app_id: int,
    kind: str,
    version: str,
    release_id: int | None = None,
    from_env_id: int | None = None,
    to_env_id: int | None = None,
    note: str = "",
) -> int:
    """向分布事件流追加一条不可变事件，返回事件 id。"""
    cur = conn.execute(
        """
        INSERT INTO distribution_events(
          release_id, app_id, from_env_id, to_env_id, kind, version, created_at, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (release_id, app_id, from_env_id, to_env_id, kind, version, now_str(), note),
    )
    return cur.lastrowid


def replay_events(conn) -> dict:
    """按 id 顺序重放全量分布事件，得到权威读模型。

    返回：
      release_env: {release_id: env_code}，未落地的发版单不在表内
      roster:      {(app_id, env_id): version}
      events:      事件行列表（供定位面/事件流展示）
      last_event_id
    空事件集 => release_env/roster 均为空 dict，语义明确。
    """
    envs = ordered_envs(conn)
    env_ids = {e["id"]: e["code"] for e in envs}
    release_env: dict[int, str] = {}
    roster: dict[tuple[int, int], str] = {}
    events = conn.execute(
        """
        SELECT id, release_id, app_id, from_env_id, to_env_id, kind, version, created_at, note
        FROM distribution_events ORDER BY id
        """
    ).fetchall()
    for ev in events:
        if ev["release_id"] is not None:
            if ev["to_env_id"] is None:
                release_env.pop(ev["release_id"], None)
            else:
                release_env[ev["release_id"]] = env_ids[ev["to_env_id"]]
        # 只有真正落地到某环境的事件才改写名册版本（回滚同样落地一个新版本）
        if ev["to_env_id"] is not None:
            roster[(ev["app_id"], ev["to_env_id"])] = ev["version"]
    return {
        "release_env": release_env,
        "roster": roster,
        "events": events,
        "last_event_id": events[-1]["id"] if events else 0,
    }


def _next_task_no(conn) -> int:
    row = conn.execute("SELECT task_no FROM projection_meta WHERE id=1").fetchone()
    return (row["task_no"] if row else 0) + 1


def rebuild_projection(conn, triggered_by: str = "系统", note: str = "") -> dict:
    """以事件流为准整体重投影，纠偏所有缓存。

    在调用方事务内执行：重放 -> 对比缓存 -> 以重放结果整体重写
    releases.current_env_id 与 app_env_versions，并推进投影任务账本。
    返回任务号、刷新戳、事件位点与本次纠偏行数（缓存分叉规模）。
    """
    envs = ordered_envs(conn)
    env_codes = [e["code"] for e in envs]
    apps = conn.execute("SELECT id FROM apps ORDER BY id").fetchall()
    model = replay_events(conn)

    repaired = 0

    # 1) 发版单当前环境：以重放结果为准，未落地一律置空
    releases = conn.execute("SELECT id, current_env_id FROM releases").fetchall()
    env_code_to_id = {e["code"]: e["id"] for e in envs}
    for r in releases:
        expected_code = model["release_env"].get(r["id"])
        expected_id = env_code_to_id[expected_code] if expected_code else None
        if r["current_env_id"] != expected_id:
            repaired += 1
        conn.execute("UPDATE releases SET current_env_id=? WHERE id=?", (expected_id, r["id"]))

    # 2) 名册三环境列：以重放结果为准，缺失格落为空版本
    for app in apps:
        for env in envs:
            expected_ver = model["roster"].get((app["id"], env["id"]), "")
            row = conn.execute(
                "SELECT version FROM app_env_versions WHERE app_id=? AND env_id=?",
                (app["id"], env["id"]),
            ).fetchone()
            current_ver = row["version"] if row else None
            if current_ver is None:
                conn.execute(
                    "INSERT INTO app_env_versions(app_id, env_id, version, updated_at) VALUES (?, ?, ?, ?)",
                    (app["id"], env["id"], expected_ver, now_str()),
                )
                if expected_ver:
                    repaired += 1
            elif current_ver != expected_ver:
                conn.execute(
                    "UPDATE app_env_versions SET version=?, updated_at=? WHERE app_id=? AND env_id=?",
                    (expected_ver, now_str(), app["id"], env["id"]),
                )
                repaired += 1

    # 3) 推进投影任务账本（任务号单调递增，刷新戳即本次重投影时间）
    task_no = _next_task_no(conn)
    stamp = now_str()
    conn.execute(
        """
        INSERT INTO projection_meta(id, task_no, last_event_id, projected_at, triggered_by, repaired_rows)
        VALUES (1, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          task_no=excluded.task_no,
          last_event_id=excluded.last_event_id,
          projected_at=excluded.projected_at,
          triggered_by=excluded.triggered_by,
          repaired_rows=excluded.repaired_rows
        """,
        (task_no, model["last_event_id"], stamp, triggered_by, repaired),
    )
    audit(conn, "投影", None, f"重投影任务{task_no:04d}", f"位点{model['last_event_id']} 纠偏{repaired}行 {note}".strip())
    return {
        "投影任务号": task_no,
        "刷新戳": stamp,
        "事件位点": model["last_event_id"],
        "纠偏行数": repaired,
        "环境序列": env_codes,
    }


def projection_stamp(conn) -> dict:
    """读取最近投影任务账本（各页展示用刷新戳，须与四格/名册同源）。"""
    row = conn.execute("SELECT * FROM projection_meta WHERE id=1").fetchone()
    if not row:
        return {"投影任务号": 0, "刷新戳": "", "事件位点": 0, "纠偏行数": 0}
    return {
        "投影任务号": row["task_no"],
        "刷新戳": row["projected_at"],
        "事件位点": row["last_event_id"],
        "纠偏行数": row["repaired_rows"],
    }


def environment_distribution(conn) -> dict:
    """总览四格真源：按重放得到的发版单当前环境计数。

    四格 = 未落地 / 测 / 预 / 产（环境列按 sort_order 动态生成，未落地恒在首）。
    状态桶（待入闸等）另由 releases.status 统计，二者职责分开，
    环境分布只能出自这里，禁止 SQL 各自 COUNT。
    """
    envs = ordered_envs(conn)
    buckets = [UNLANDED] + [e["code"] for e in envs]
    counts = {code: 0 for code in buckets}
    model = replay_events(conn)
    releases = conn.execute("SELECT id FROM releases").fetchall()
    for r in releases:
        code = model["release_env"].get(r["id"], UNLANDED)
        counts[code] = counts.get(code, 0) + 1
    return {"四格顺序": buckets, "计数": counts}


def roster_view(conn) -> list[dict]:
    """应用名册三环境版本列：读投影缓存 app_env_versions（已由事件流重放保证权威）。"""
    return [
        dict(r)
        for r in conn.execute(
            """
            SELECT a.id AS 应用编号, a.name AS 应用, e.id AS 环境编号,
                   e.code AS 环境, e.name AS 环境名,
                   v.version AS 版本, v.updated_at AS 版本戳
            FROM apps a
            JOIN environments e
            LEFT JOIN app_env_versions v ON v.app_id=a.id AND v.env_id=e.id
            ORDER BY a.id, e.sort_order
            """
        ).fetchall()
    ]


def distribution_diffs(conn) -> dict:
    """对账差额：把投影缓存与事件流重放结果逐项比对，任何分叉都显式暴露。"""
    model = replay_events(conn)
    env_ids = {e["id"]: e["code"] for e in ordered_envs(conn)}

    current_env_diff = []
    for r in conn.execute("SELECT id, current_env_id FROM releases").fetchall():
        expected_id = None
        code = model["release_env"].get(r["id"])
        if code:
            expected_id = next(eid for eid, c in env_ids.items() if c == code)
        if r["current_env_id"] != expected_id:
            current_env_diff.append(
                {"发版单编号": r["id"], "缓存环境编号": r["current_env_id"], "真源环境编号": expected_id}
            )

    roster_diff = []
    for app in conn.execute("SELECT id, name FROM apps").fetchall():
        for env in ordered_envs(conn):
            expected = model["roster"].get((app["id"], env["id"]), "")
            row = conn.execute(
                "SELECT version FROM app_env_versions WHERE app_id=? AND env_id=?",
                (app["id"], env["id"]),
            ).fetchone()
            cached = row["version"] if row else None
            if cached != expected:
                roster_diff.append(
                    {
                        "应用": app["name"],
                        "环境": env["code"],
                        "缓存版本": cached,
                        "真源版本": expected,
                    }
                )

    event_count = conn.execute("SELECT COUNT(*) AS c FROM distribution_events").fetchone()["c"]
    return {
        "事件总数": event_count,
        "发版单环境差额": current_env_diff,
        "名册版本差额": roster_diff,
        "差额总数": len(current_env_diff) + len(roster_diff),
    }


def projection_gap(conn) -> dict:
    """投影缺口：名册缓存/投影账本戳与事件流真源分叉时显式挂缺口。

    定臂：环境分布格允许先行变绿（总出自事件流重放），但名册汇总或投影任务戳
    与真源不一致时必须挂缺口；缺口未清，任何页面不得当已对齐。
    总览、名册、对账、投影旁读、审计共用本函数的同一份判定，禁止各算各的。
    """
    diffs = distribution_diffs(conn)
    stamp = projection_stamp(conn)
    event_total = diffs["事件总数"]
    # 账本位点差 = 事件流长度 - 账本记录位点；非 0 即戳与流不齐（含账本缺失/被回拨）
    lag = event_total - stamp["事件位点"]
    reasons: list[str] = []
    if diffs["名册版本差额"]:
        reasons.append(f"名册版本差额{len(diffs['名册版本差额'])}行")
    if diffs["发版单环境差额"]:
        reasons.append(f"发版单环境差额{len(diffs['发版单环境差额'])}行")
    if lag != 0:
        reasons.append(f"投影账本位点{stamp['事件位点']}与事件流{event_total}不齐")
    if event_total and not stamp["投影任务号"]:
        reasons.append("投影账本缺失")
    return {
        "有缺口": bool(reasons),
        "差额总数": diffs["差额总数"],
        "账本位点差": lag,
        "原因": reasons,
    }
