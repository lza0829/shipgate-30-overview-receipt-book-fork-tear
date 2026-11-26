from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.db import db, row_to_dict
from app.services.common import (
    active_rollback_window,
    audit,
    get_release,
    now_str,
    upsert_instance,
)
from app.services.projection import rebuild_projection, record_event

router = APIRouter(tags=["回滚"])


class RollbackIn(BaseModel):
    目标版本: str
    备注: str = ""


@router.post("/发版单/{release_id}/回滚")
def rollback(release_id: int, body: RollbackIn):
    with db() as conn:
        r = conn.execute("SELECT * FROM releases WHERE id=?", (release_id,)).fetchone()
        if not r:
            raise HTTPException(404, "发版单不存在")
        if r["status"] not in ("已放行", "晋升中"):
            raise HTTPException(400, "当前状态不可回滚")
        if not r["current_env_id"]:
            raise HTTPException(400, "无当前环境，无法回滚")
        win = active_rollback_window(conn, r["current_env_id"])
        if not win:
            raise HTTPException(400, "回滚窗已关，禁止回滚")
        now = now_str()
        # 状态机命令侧维护；回滚后发版单仍停在原环境（环境分布格不变）
        conn.execute(
            """
            UPDATE releases SET status='已回滚', rolled_back_at=?, target_version=? WHERE id=?
            """,
            (now, body.目标版本, release_id),
        )
        # 分布真源：回滚是一条落地到同环境的版本事件，名册版本由投影重写
        record_event(
            conn,
            app_id=r["app_id"],
            release_id=release_id,
            from_env_id=r["current_env_id"],
            to_env_id=r["current_env_id"],
            kind="回滚",
            version=body.目标版本,
            note=body.备注,
        )
        upsert_instance(conn, r["app_id"], r["current_env_id"], body.目标版本, "探针绿", release_id)
        # 旧版本实例标红，便于对账发现残留
        conn.execute(
            """
            UPDATE instances SET health='探针红', updated_at=?
            WHERE app_id=? AND env_id=? AND version!=? AND release_id=?
            """,
            (now, r["app_id"], r["current_env_id"], body.目标版本, release_id),
        )
        task = rebuild_projection(conn, triggered_by="回滚", note=body.备注)
        audit(conn, "回滚", release_id, f"回滚到{body.目标版本}", body.备注)
        result = row_to_dict(get_release(conn, release_id))
        result["投影"] = task
        return result
