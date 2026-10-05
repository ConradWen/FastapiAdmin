"""发布台账持久化（F-3 跨重启：metastella_publish_ledger 表）。

进程内注册表只是缓存；**台账=持久事实源**（package_name+fingerprint 主键唯一=内容不可变）。
DSN 复用平台既有 psycopg 依赖；表由 ensure_ledger 幂等建。
"""

from __future__ import annotations

import json
from typing import Any

from .errors import ModelPackageAlreadyPublishedError

TABLE = "metastella_publish_ledger"

_DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    package_name text NOT NULL,
    fingerprint text NOT NULL,
    schema_version text NOT NULL,
    published_at text NOT NULL,
    published_by text NOT NULL,
    payload jsonb NOT NULL,
    PRIMARY KEY (package_name, fingerprint)
)
"""


def ensure_ledger(conn: Any) -> None:
    conn.execute(_DDL)
    conn.commit()


def record_publish(conn: Any, record: dict[str, Any]) -> None:
    """写入发布记录；(package, fingerprint) 撞车=已发布（F-3）。竞态同样回领域错误。"""
    import psycopg.errors

    try:
        conn.execute(
            f"INSERT INTO {TABLE} (package_name, fingerprint, schema_version, published_at, published_by, payload) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                record["package_name"],
                record["fingerprint"],
                record["schema_version"],
                record["published_at"],
                record["published_by"],
                json.dumps(record, ensure_ascii=False),
            ),
        )
        conn.commit()
    except psycopg.errors.UniqueViolation as exc:
        conn.rollback()
        raise ModelPackageAlreadyPublishedError(
            f"语义包 {record['package_name']} 指纹 {record['fingerprint']} 台账已存在（F-3）"
        ) from exc


def is_published(conn: Any, package_name: str, fingerprint: str) -> bool:
    row = conn.execute(
        f"SELECT 1 FROM {TABLE} WHERE package_name = %s AND fingerprint = %s",
        (package_name, fingerprint),
    ).fetchone()
    return row is not None
