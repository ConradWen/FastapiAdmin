"""生成物应用骨架构建器（P-13「确定性生成」面的第一块可运行产物）。

同语义包→同文件集（字节级确定性）。产物 main.py：自足 FastAPI 应用——
GET /health 与每聚合 GET /api/{Alias}/list（PG 表实查，表名=DDL 生成器同规则 t_xxx）。
"""

from __future__ import annotations

from typing import Any

from .ddl_generator import _table_name
from .publish import compute_package_fingerprint


def generate_app_bundle(family: dict[str, Any], *, package_name: str) -> dict[str, str]:
    aggregates = sorted(family["OBJECT"].get("aggregates", []), key=lambda a: a["alias"])
    fingerprint = compute_package_fingerprint(family)

    routes: list[str] = []
    for agg in aggregates:
        alias = agg["alias"]
        table = _table_name(alias)
        camel = alias[0].lower() + alias[1:]
        routes.append(
            f'''

@app.get("/api/{alias}/list")
def list_{camel}(request: Request):
    import psycopg

    tenant = request.headers.get("X-Tenant-Id")
    if not tenant:
        raise HTTPException(401, detail="X-Tenant-Id required")
    try:
        tenant_id = int(tenant)
    except ValueError:
        raise HTTPException(400, detail="invalid tenant id") from None

    dsn = os.environ.get("DATABASE_URI", DEFAULT_DSN)
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT to_jsonb(t) FROM {table} t WHERE deleted = false AND tenant_id = %s LIMIT 100",
            (tenant_id,),
        )
        return {{"table": "{table}", "tenant_id": tenant_id, "rows": [row for (row,) in cur.fetchall()]}}
'''
        )

    main_py = f'''"""MetaStella 生成物——{package_name}（指纹 {fingerprint[:12]}；D1.06 确定性产物）"""

import os

from fastapi import FastAPI, HTTPException, Request

DEFAULT_DSN = os.environ.get(
    "DEFAULT_DSN",
    "postgresql://metastella:metastella_dev@postgres:5432/metastella",
)

app = FastAPI(title="{package_name}")


@app.get("/health")
def health():
    return {{"package": "{package_name}", "fingerprint": "{fingerprint}"}}
{"".join(routes)}
'''

    requirements = "fastapi\nuvicorn\npsycopg[binary]\n"
    return {"main.py": main_py, "requirements.txt": requirements}
