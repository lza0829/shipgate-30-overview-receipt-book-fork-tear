from __future__ import annotations
from fastapi import APIRouter
from app.db import db, rows_to_list
from app.services.common import RELEASE_SELECT
from app.services.projection import (
    environment_distribution,
    projection_gap,
    projection_stamp,
    roster_view,
)

router = APIRouter(tags=["总览"])


@router.get("/总览")
def overview():
    with db() as conn:
        # 状态桶：发版单工作流状态维度（与环境分布职责分开，不混用）
        status_counts = {}
        for name in ("待入闸", "已入闸", "晋升中", "已放行", "回滚中", "已回滚", "已关闭"):
            status_counts[name] = conn.execute(
                "SELECT COUNT(*) AS c FROM releases WHERE status=?", (name,)
            ).fetchone()["c"]
        # 环境分布四格：唯一来自分布事件重投影，禁止另写 COUNT
        dist = environment_distribution(conn)
        active = rows_to_list(
            conn.execute(
                RELEASE_SELECT
                + " WHERE r.status IN ('已入闸','晋升中','已放行','回滚中') ORDER BY r.id DESC"
            ).fetchall()
        )
        # 名册三环境版本列：投影缓存，与四格同一次重放、同一刷新戳
        versions = roster_view(conn)
        # 投影缺口：名册汇总或投影戳与事件真源分叉时挂缺口，拧花不得维持齐绿
        gap = projection_gap(conn)
        health = rows_to_list(
            conn.execute(
                """
                SELECT i.id AS 编号, a.name AS 应用, e.code AS 环境, i.version AS 版本,
                       i.health AS 健康, i.release_id AS 发版单编号, i.updated_at AS 更新时间
                FROM instances i
                JOIN apps a ON a.id = i.app_id
                JOIN environments e ON e.id = i.env_id
                ORDER BY a.id, e.sort_order, i.id
                """
            ).fetchall()
        )
        return {
            "状态分布": status_counts,
            "环境分布": dist,
            "投影": projection_stamp(conn),
            "投影缺口": gap,
            "对齐": not gap["有缺口"],
            "在途": active,
            "环境版本": versions,
            "实例": health,
        }

