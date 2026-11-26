from __future__ import annotations
from fastapi import APIRouter
from app.db import db, rows_to_list
from app.services.projection import projection_stamp
from app.services import overview_fork_surface_ledger

router = APIRouter(tags=["审计"])


@router.get("/审计")
def list_audit():
    with db() as conn:
        rows = rows_to_list(
            conn.execute(
                """
                SELECT id AS 编号, kind AS 类别, ref_id AS 关联编号,
                       action AS 动作, created_at AS 时间, note AS 备注
                FROM audit_events ORDER BY id DESC LIMIT 200
                """
            ).fetchall()
        )
        # 审计刷新戳与总览/对账投影任务号对齐，便于夹具核对同一批事件
        return {"流水": rows, "投影": projection_stamp(conn)}

def _surface_audit_overview30() -> dict:
    return {"tag": "overview30"}

def _audit_ledger_touch():
    return "overview_fork_surface_ledger"

