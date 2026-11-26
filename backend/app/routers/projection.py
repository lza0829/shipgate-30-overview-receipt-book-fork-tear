from __future__ import annotations
from fastapi import APIRouter
from pydantic import BaseModel
from app.db import db, rows_to_list
from app.services.projection import (
    distribution_diffs,
    environment_distribution,
    projection_stamp,
    rebuild_projection,
)

router = APIRouter(tags=["投影"])


class ReplayIn(BaseModel):
    备注: str = ""


@router.get("/分布事件")
def list_distribution_events():
    """定位面：环境分布唯一真源事件流，按重放顺序返回。"""
    with db() as conn:
        events = rows_to_list(
            conn.execute(
                """
                SELECT d.id AS 事件号, d.release_id AS 发版单编号, d.app_id AS 应用编号,
                       a.name AS 应用,
                       ef.code AS 源环境, et.code AS 目标环境,
                       d.kind AS 类型, d.version AS 版本,
                       d.created_at AS 时间, d.note AS 备注
                FROM distribution_events d
                JOIN apps a ON a.id = d.app_id
                LEFT JOIN environments ef ON ef.id = d.from_env_id
                LEFT JOIN environments et ON et.id = d.to_env_id
                ORDER BY d.id
                """
            ).fetchall()
        )
        return {
            "事件流": events,
            "分布": environment_distribution(conn),
            "投影": projection_stamp(conn),
            "差额": distribution_diffs(conn),
        }


@router.post("/投影/重放")
def replay(body: ReplayIn):
    """显式纠偏口：以分布事件流为准整体重投影，缓存分叉在此被收敛，不允许长期双数。"""
    with db() as conn:
        before = distribution_diffs(conn)
        task = rebuild_projection(conn, triggered_by="手动重放", note=body.备注)
        after = distribution_diffs(conn)
        return {
            "投影": task,
            "重放前差额": before,
            "重放后差额": after,
        }
