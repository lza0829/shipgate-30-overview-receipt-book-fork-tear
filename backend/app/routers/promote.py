from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.db import db, row_to_dict
from app.services.common import (
    active_release_window,
    audit,
    env_by_code,
    get_release,
    get_setting,
    now_str,
    ordered_envs,
    upsert_instance,
)
from app.services.projection import rebuild_projection, record_event

router = APIRouter(tags=["晋升"])


class PromoteIn(BaseModel):
    目标环境: str
    备注: str = ""


@router.post("/发版单/{release_id}/晋升")
def promote(release_id: int, body: PromoteIn):
    with db() as conn:
        r = conn.execute("SELECT * FROM releases WHERE id=?", (release_id,)).fetchone()
        if not r:
            raise HTTPException(404, "发版单不存在")
        if r["status"] not in ("已入闸", "晋升中"):
            raise HTTPException(400, "当前状态不可晋升")
        to_env = env_by_code(conn, body.目标环境)
        envs = ordered_envs(conn)
        codes = [e["code"] for e in envs]
        if body.目标环境 not in codes:
            raise HTTPException(400, "目标环境非法")
        cur_env = None
        if r["current_env_id"]:
            cur_env = conn.execute(
                "SELECT * FROM environments WHERE id=?", (r["current_env_id"],)
            ).fetchone()
        allow_skip = get_setting(conn, "允许跳级", "否") == "是"
        if cur_env:
            cur_idx = codes.index(cur_env["code"])
            to_idx = codes.index(body.目标环境)
            if to_idx <= cur_idx:
                raise HTTPException(400, "只能向更高环境晋升")
            if not allow_skip and to_idx != cur_idx + 1:
                raise HTTPException(400, "禁止跳级，须逐级晋升")
        else:
            if body.目标环境 != "测":
                raise HTTPException(400, "未落地时只能先入测")

        win = active_release_window(conn, to_env["id"])
        hard = get_setting(conn, "维护窗硬拒", "是") == "是"
        if hard and not win:
            raise HTTPException(400, "目标环境放行窗已关，禁止晋升")

        now = now_str()
        # 闸口裁决流水（拒绝/放行审计留痕），与分布真源分离
        conn.execute(
            """
            INSERT INTO promote_events(release_id, from_env_id, to_env_id, decision, created_at, note)
            VALUES (?, ?, ?, '放行', ?, ?)
            """,
            (release_id, r["current_env_id"], to_env["id"], now, body.备注),
        )
        new_status = "已放行" if body.目标环境 == "产" else "晋升中"
        released_at = now if body.目标环境 == "产" else r["released_at"]
        # 状态机仍属命令侧；current_env_id 交投影，禁止直写
        conn.execute(
            "UPDATE releases SET status=?, released_at=? WHERE id=?",
            (new_status, released_at, release_id),
        )
        # 分布真源：追加晋升事件，随后同一事务内整体重投影（同命运）
        record_event(
            conn,
            app_id=r["app_id"],
            release_id=release_id,
            from_env_id=r["current_env_id"],
            to_env_id=to_env["id"],
            kind="晋升",
            version=r["target_version"],
            note=body.备注,
        )
        # 实例为运行时证据，保留命令侧写入，对账时与名册投影比对
        upsert_instance(conn, r["app_id"], to_env["id"], r["target_version"], "探针绿", release_id)
        task = rebuild_projection(conn, triggered_by="晋升", note=body.备注)
        audit(conn, "晋升", release_id, f"晋升到{body.目标环境}", body.备注)
        result = row_to_dict(get_release(conn, release_id))
        result["投影"] = task
        return result
