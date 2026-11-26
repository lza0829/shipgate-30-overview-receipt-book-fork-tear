from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from app.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS apps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  owner TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT '启用' CHECK(status IN ('启用','停用'))
);
CREATE TABLE IF NOT EXISTS environments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  sort_order INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS app_env_versions (
  app_id INTEGER NOT NULL,
  env_id INTEGER NOT NULL,
  version TEXT NOT NULL DEFAULT '',
  updated_at TEXT,
  PRIMARY KEY(app_id, env_id),
  FOREIGN KEY(app_id) REFERENCES apps(id),
  FOREIGN KEY(env_id) REFERENCES environments(id)
);
CREATE TABLE IF NOT EXISTS releases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  serial TEXT NOT NULL UNIQUE,
  app_id INTEGER NOT NULL,
  target_version TEXT NOT NULL,
  artifact_digest TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT '待入闸'
    CHECK(status IN ('待入闸','已入闸','晋升中','已放行','回滚中','已回滚','已关闭')),
  pipeline_status TEXT NOT NULL DEFAULT '未回执'
    CHECK(pipeline_status IN ('未回执','绿','红')),
  current_env_id INTEGER,
  canary_ratio INTEGER NOT NULL DEFAULT 10,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  admitted_at TEXT,
  released_at TEXT,
  rolled_back_at TEXT,
  FOREIGN KEY(app_id) REFERENCES apps(id),
  FOREIGN KEY(current_env_id) REFERENCES environments(id)
);
CREATE TABLE IF NOT EXISTS promote_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  release_id INTEGER NOT NULL,
  from_env_id INTEGER,
  to_env_id INTEGER NOT NULL,
  decision TEXT NOT NULL CHECK(decision IN ('放行','拒绝')),
  created_at TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  FOREIGN KEY(release_id) REFERENCES releases(id),
  FOREIGN KEY(from_env_id) REFERENCES environments(id),
  FOREIGN KEY(to_env_id) REFERENCES environments(id)
);
-- 环境分布唯一真源：分布事件流（事件溯源）。
-- 名册 app_env_versions 与 releases.current_env_id 仅为该流的投影缓存，
-- 只能由 app.services.projection 重放写入，命令侧不得直写。
CREATE TABLE IF NOT EXISTS distribution_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  release_id INTEGER,
  app_id INTEGER NOT NULL,
  from_env_id INTEGER,
  to_env_id INTEGER,
  kind TEXT NOT NULL CHECK(kind IN ('基线落地','入测','晋升','回滚')),
  version TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  FOREIGN KEY(release_id) REFERENCES releases(id),
  FOREIGN KEY(app_id) REFERENCES apps(id),
  FOREIGN KEY(from_env_id) REFERENCES environments(id),
  FOREIGN KEY(to_env_id) REFERENCES environments(id)
);
-- 投影任务账本：记录最近一次重投影任务号、刷新戳与事件位点
CREATE TABLE IF NOT EXISTS projection_meta (
  id INTEGER PRIMARY KEY CHECK(id = 1),
  task_no INTEGER NOT NULL DEFAULT 0,
  last_event_id INTEGER NOT NULL DEFAULT 0,
  projected_at TEXT NOT NULL DEFAULT '',
  triggered_by TEXT NOT NULL DEFAULT '',
  repaired_rows INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS release_windows (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  env_id INTEGER NOT NULL,
  open_at TEXT NOT NULL,
  close_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT '窗开' CHECK(status IN ('窗开','窗关')),
  FOREIGN KEY(env_id) REFERENCES environments(id)
);
CREATE TABLE IF NOT EXISTS rollback_windows (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  env_id INTEGER NOT NULL,
  open_at TEXT NOT NULL,
  close_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT '窗开' CHECK(status IN ('窗开','窗关')),
  FOREIGN KEY(env_id) REFERENCES environments(id)
);
CREATE TABLE IF NOT EXISTS instances (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  app_id INTEGER NOT NULL,
  env_id INTEGER NOT NULL,
  version TEXT NOT NULL,
  health TEXT NOT NULL DEFAULT '探针绿' CHECK(health IN ('探针绿','探针红')),
  release_id INTEGER,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(app_id) REFERENCES apps(id),
  FOREIGN KEY(env_id) REFERENCES environments(id),
  FOREIGN KEY(release_id) REFERENCES releases(id)
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  ref_id INTEGER,
  action TEXT NOT NULL,
  created_at TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT ''
);
"""

RELEASE_STATUSES = ("待入闸", "已入闸", "晋升中", "已放行", "回滚中", "已回滚", "已关闭")
PIPELINE_STATUSES = ("未回执", "绿", "红")
HEALTH_STATUSES = ("探针绿", "探针红")
WINDOW_STATUSES = ("窗开", "窗关")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def rows_to_list(rows) -> list[dict]:
    return [dict(r) for r in rows]
