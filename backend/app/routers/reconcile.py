from __future__ import annotations
from fastapi import APIRouter
from app.db import db, rows_to_list
from app.services.projection import (
    distribution_diffs,
    environment_distribution,
    projection_gap,
    projection_stamp,
)

router = APIRouter(tags=["对账"])


@router.get("/对账")
def reconcile():
    with db() as conn:
        # 状态统计仍以发版单状态机为准（工作流维度，非环境分布真源）
        release_stats = {
            "申请数": conn.execute("SELECT COUNT(*) AS c FROM releases").fetchone()["c"],
            "已放行": conn.execute(
                "SELECT COUNT(*) AS c FROM releases WHERE status='已放行'"
            ).fetchone()["c"],
            "已回滚": conn.execute(
                "SELECT COUNT(*) AS c FROM releases WHERE status='已回滚'"
            ).fetchone()["c"],
            "在途": conn.execute(
                """
                SELECT COUNT(*) AS c FROM releases
                WHERE status IN ('已入闸','晋升中','已放行','回滚中')
                """
            ).fetchone()["c"],
        }
        # 名册（投影缓存）与实例（运行时证据）比对
        version_vs_instance = rows_to_list(
            conn.execute(
                """
                SELECT a.name AS 应用, e.code AS 环境,
                       v.version AS 名册版本,
                       GROUP_CONCAT(i.version, ',') AS 实例版本们,
                       SUM(CASE WHEN i.health='探针红' THEN 1 ELSE 0 END) AS 红灯数
                FROM app_env_versions v
                JOIN apps a ON a.id = v.app_id
                JOIN environments e ON e.id = v.env_id
                LEFT JOIN instances i ON i.app_id = v.app_id AND i.env_id = v.env_id
                GROUP BY v.app_id, v.env_id
                ORDER BY a.id, e.sort_order
                """
            ).fetchall()
        )
        promote_count = conn.execute("SELECT COUNT(*) AS c FROM promote_events").fetchone()["c"]
        # 投影缺口未清，对账不得当已对齐
        gap = projection_gap(conn)
        return {
            "发版统计": release_stats,
            "晋升事件数": promote_count,
            "名册与实例": version_vs_instance,
            # 环境分布与总览四格共用同一次重投影
            "环境分布": environment_distribution(conn),
            # 缓存与事件流真源的分叉差额；正常应为 0，重放纠偏后归零
            "对账差额": distribution_diffs(conn),
            "投影": projection_stamp(conn),
            "投影缺口": gap,
            "对齐": not gap["有缺口"],
        }

