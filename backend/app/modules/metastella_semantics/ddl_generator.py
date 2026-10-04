"""M1→PostgreSQL DDL 确定性生成器（D1.02 方言钉死 / D1.03 租户注入 / D1.05 逻辑删除 / D1.06 确定性）。

生成纪律：同语义包重复生成产出**字节级一致**的 DDL（D1.06）——
排序全部显式化（聚合按 alias、属性按声明序），键序/插入序无关。
"""

from __future__ import annotations

from typing import Any

from .errors import ModelStructureError

# D1.02：语义类型 → PG 方言（钉死；禁任何非 PG 类型出这套映射）
_PG_TYPES: dict[str, str] = {
    "String": "varchar(255)",
    "Text": "text",
    "Integer": "bigint",
    "Decimal": "numeric(18, 2)",
    "Money": "numeric(18, 2)",
    "Boolean": "boolean",
    "Date": "date",
    "DateTime": "timestamptz",
    "JSON": "jsonb",
    "Enum": "int",
    "Reference": "bigint",
    "Attachment": "text",
    "AggregateRootRef": "bigint",
    "DictionaryRef": "int",
}


def generate_ddl(family: dict[str, Any]) -> str:
    """从语义包族生成完整 PG DDL（当前消费 M1 OBJECT；其余模型类型不产出表）。"""
    m1 = family.get("OBJECT")
    if not isinstance(m1, dict):
        raise ModelStructureError("generate_ddl 需要 family['OBJECT']（M1 对象模型）")

    aggregates = sorted(m1.get("aggregates", []), key=lambda a: a.get("alias", ""))
    statements: list[str] = []
    for agg in aggregates:
        statements.append(_table_ddl(agg))
    return "\n\n".join(statements) + "\n"


def _table_ddl(agg: dict[str, Any]) -> str:
    alias: str = str(agg["alias"])
    table = _table_name(alias)
    lines: list[str] = [f"CREATE TABLE {table} ("]

    column_lines: list[str] = ["    id bigint PRIMARY KEY"]
    for attr in agg.get("attributes", []):
        column_lines.append(f"    {_column_ddl(attr)}")
    # D1.03：tenant_id 生成器统一注入（M1 不显式建模）
    column_lines.append("    tenant_id bigint NOT NULL")
    # D1.05：聚合根默认逻辑删除列
    column_lines.append("    deleted boolean NOT NULL DEFAULT false")
    column_lines.append("    created_at timestamptz NOT NULL DEFAULT now()")
    column_lines.append("    updated_at timestamptz NOT NULL DEFAULT now()")

    lines.append(",\n".join(column_lines))
    lines.append(");")
    return "\n".join(lines)


def _column_ddl(attr: dict[str, Any]) -> str:
    name = str(attr["name"])
    sem_type = str(attr["type"])
    if sem_type not in _PG_TYPES:
        raise ModelStructureError(f"属性 {name}: type={sem_type} 无 PG 方言映射（D1.02）")
    pg_type = _PG_TYPES[sem_type]
    parts = [f"{name} {pg_type}", "NOT NULL" if attr.get("required") else "NULL"]
    if attr.get("unique"):
        parts.append("UNIQUE")
    if "defaultValue" in attr:
        parts.append(f"DEFAULT {_default_sql(attr['defaultValue'])}")
    return " ".join(parts)


def _default_sql(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "NULL"
    if isinstance(value, int | float):
        return str(value)
    text = str(value).replace("'", "''")
    return f"'{text}'"


def _table_name(alias: str) -> str:
    """alias（PascalCase）→ snake_case 表名，统一加 t_ 前缀。"""
    snake = "".join(f"_{c.lower()}" if c.isupper() else c for c in alias).lstrip("_")
    return f"t_{snake}"
