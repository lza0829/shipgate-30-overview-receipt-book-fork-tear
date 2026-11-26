from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app.db import db, rows_to_list, row_to_dict
from app.services.common import (
    RELEASE_SELECT,
    assert_app_enabled,
    audit,
    get_release,
    get_setting,
    next_serial,
    now_str,
)
from app.services.projection import rebuild_projection, record_event

router = APIRouter(tags=["发版单"])


class ReleaseIn(BaseModel):
    应用编号: int
    目标版本: str = Field(min_length=1)
    制品摘要: str = ""
    金丝雀比例: int | None = None
    备注: str = ""


class PipelineIn(BaseModel):
    流水线: str


@router.get("/发版单")
def list_releases():
    with db() as conn:
        return rows_to_list(conn.execute(RELEASE_SELECT + " ORDER BY r.id DESC").fetchall())


@router.get("/发版单/{release_id}")
def one_release(release_id: int):
    with db() as conn:
        return row_to_dict(get_release(conn, release_id))


@router.post("/发版单")
def create_release(body: ReleaseIn):
    with db() as conn:
        assert_app_enabled(conn, body.应用编号)
        ratio = body.金丝雀比例
        if ratio is None:
            ratio = int(get_setting(conn, "金丝雀默认比例", "10") or "10")
        if ratio < 0 or ratio > 100:
            raise HTTPException(400, "金丝雀比例须在 0 到 100")
        serial = next_serial(conn)
        now = now_str()
        cur = conn.execute(
            """
            INSERT INTO releases(
              serial, app_id, target_version, artifact_digest, status, pipeline_status,
              canary_ratio, note, created_at
            ) VALUES (?, ?, ?, ?, '待入闸', '未回执', ?, ?, ?)
            """,
            (serial, body.应用编号, body.目标版本, body.制品摘要, ratio, body.备注, now),
        )
        rid = cur.lastrowid
        audit(conn, "发版单", rid, "申请发版", serial)
        return row_to_dict(get_release(conn, rid))


@router.post("/发版单/{release_id}/入闸")
def admit(release_id: int):
    with db() as conn:
        r = conn.execute("SELECT * FROM releases WHERE id=?", (release_id,)).fetchone()
        if not r:
            raise HTTPException(404, "发版单不存在")
        if r["status"] != "待入闸":
            raise HTTPException(400, "仅待入闸可入闸")
        assert_app_enabled(conn, r["app_id"])
        must_green = get_setting(conn, "入闸须流水线绿", "是") == "是"
        if must_green and r["pipeline_status"] != "绿":
            raise HTTPException(400, "流水线未绿，禁止入闸")
        if not r["artifact_digest"]:
            raise HTTPException(400, "缺少制品摘要，禁止入闸")
        active = conn.execute(
            """
            SELECT id FROM releases
            WHERE app_id=? AND id!=? AND status IN ('已入闸','晋升中','已放行','回滚中')
            """,
            (r["app_id"], release_id),
        ).fetchone()
        if active:
            raise HTTPException(400, "同应用已有在途发版单，禁止并行入闸")
        test = conn.execute("SELECT id FROM environments WHERE code='测'").fetchone()
        now = now_str()
        # 状态机命令侧维护；current_env_id 不再直写，交给分布事件重投影
        conn.execute(
            "UPDATE releases SET status='已入闸', admitted_at=? WHERE id=?",
            (now, release_id),
        )
        record_event(
            conn,
            app_id=r["app_id"],
            release_id=release_id,
            from_env_id=None,
            to_env_id=test["id"],
            kind="入测",
            version=r["target_version"],
            note=r["serial"],
        )
        task = rebuild_projection(conn, triggered_by="入闸", note=r["serial"])
        audit(conn, "发版单", release_id, "入闸", r["serial"])
        result = row_to_dict(get_release(conn, release_id))
        result["投影"] = task
        return result


@router.post("/发版单/{release_id}/流水线")
def set_pipeline(release_id: int, body: PipelineIn):
    if body.流水线 not in ("未回执", "绿", "红"):
        raise HTTPException(400, "流水线状态非法")
    with db() as conn:
        r = conn.execute("SELECT * FROM releases WHERE id=?", (release_id,)).fetchone()
        if not r:
            raise HTTPException(404, "发版单不存在")
        conn.execute(
            "UPDATE releases SET pipeline_status=? WHERE id=?",
            (body.流水线, release_id),
        )
        audit(conn, "发版单", release_id, "流水线回执", body.流水线)
        return row_to_dict(get_release(conn, release_id))
