"""M1→PostgreSQL DDL 确定性生成器（D1.02 方言钉死 / D1.03 租户注入 / D1.05 逻辑删除 / D1.06 确定性 / D1.07 字符串码字典）。

生成纪律：同语义包重复生成产出**字节级一致**的 DDL（D1.06）——
排序全部显式化（聚合按 alias、字典域按声明序、枚举合成域按 (表,列)），键序/插入序无关。

D1.07（工单 12）：Enum/DictionaryRef 落**字符串业务码**——
生成 `t_dict_type`/`t_dict_data` 两张字典表（含种子），业务列 = varchar 存 code，
复合外键 (固定 type_code, code)→t_dict_data(type_code, code)；type_code 以 PG
GENERATED STORED 常量列承载（单业务列也能挂复合 FK）。Enum 内联值合成枚举域。
"""

from __future__ import annotations

from typing import Any

from .errors import ModelStructureError

# D1.02：语义类型 → PG 方言（钉死；禁任何非 PG 类型出这套映射）
# D1.07 修正：Enum/DictionaryRef 不在此表（改走字符串码+字典表外键分支）。
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
    "Reference": "bigint",
    "Attachment": "text",
    "AggregateRootRef": "bigint",
}

_DICT_CODE_LEN = 64


def generate_ddl_statements(family: dict[str, Any]) -> list[str]:
    """逐条语句（结构化出口，供迁移生成器直接迭代——禁对 DDL 文本再 split(';')）。

    顺序：字典两表 + 种子 → 聚合表 → 聚合间外键 ALTER（保证 PG 可顺序执行）。
    """
    m1 = family.get("OBJECT")
    if not isinstance(m1, dict):
        raise ModelStructureError("generate_ddl 需要 family['OBJECT']（M1 对象模型）")

    aggregates = sorted(m1.get("aggregates", []), key=lambda a: a.get("alias", ""))
    domains, items = _collect_dictionaries(m1, aggregates)

    statements: list[str] = [
        _dict_type_ddl(),
        _dict_data_ddl(),
        _dict_type_insert(domains),
        _dict_data_insert(items),
    ]
    for agg in aggregates:
        statements.append(_table_ddl(agg))
    statements.extend(_aggregate_fk_alters(aggregates))
    return [s for s in statements if s]


def generate_ddl(family: dict[str, Any]) -> str:
    """从语义包族生成完整 PG DDL（当前消费 M1 OBJECT；其余模型类型不产出表）。"""
    return "\n\n".join(generate_ddl_statements(family)) + "\n"


# ---- 字典表 ----


def _dict_type_ddl() -> str:
    return (
        "CREATE TABLE t_dict_type (\n"
        f"    type_code varchar({_DICT_CODE_LEN}) PRIMARY KEY,\n"
        "    name text\n"
        ");"
    )


def _dict_data_ddl() -> str:
    return (
        "CREATE TABLE t_dict_data (\n"
        f"    type_code varchar({_DICT_CODE_LEN}) NOT NULL,\n"
        f"    code varchar({_DICT_CODE_LEN}) NOT NULL,\n"
        "    label text,\n"
        "    sort_order bigint,\n"
        "    PRIMARY KEY (type_code, code),\n"
        "    FOREIGN KEY (type_code) REFERENCES t_dict_type(type_code)\n"
        ");"
    )


def _dict_type_insert(domains: list[tuple[str, str]]) -> str:
    if not domains:
        return ""
    rows = ",\n".join(f"    ({_sql_str(tc)}, {_sql_str(name)})" for tc, name in domains)
    return f"INSERT INTO t_dict_type (type_code, name) VALUES\n{rows};"


def _dict_data_insert(items: list[tuple[str, str, str, int | None]]) -> str:
    if not items:
        return ""
    rows = ",\n".join(
        f"    ({_sql_str(tc)}, {_sql_str(code)}, {_sql_str(label)}, {_sort_sql(sort)})" for tc, code, label, sort in items
    )
    return f"INSERT INTO t_dict_data (type_code, code, label, sort_order) VALUES\n{rows};"


# ---- 域收集（字典声明 + 枚举合成，确定性序）----


def _collect_dictionaries(m1: dict, aggregates: list[dict]) -> tuple[list[tuple[str, str]], list[tuple[str, str, str, int | None]]]:
    domains: list[tuple[str, str]] = []
    items: list[tuple[str, str, str, int | None]] = []
    seen_domains: set[str] = set()

    for dic in m1.get("data_dictionaries", []):
        for typ in dic.get("types", []):
            tc = str(typ.get("typeCode", ""))
            if tc and tc not in seen_domains:
                seen_domains.add(tc)
                domains.append((tc, str(typ.get("typeName", tc))))
            for it in typ.get("items", []):
                items.append((tc, str(it.get("code", "")), str(it.get("label", "")), _as_int(it.get("sortOrder"))))

    # 枚举内联值合成枚举域（D1.07：Enum 同样落字典表），按 (表名, 列名) 排序保证确定
    enum_domains: list[tuple[str, str, list[str]]] = []
    for agg in aggregates:
        table = _table_name(str(agg["alias"]))
        for attr in agg.get("attributes", []):
            if str(attr.get("type")) == "Enum":
                tc = f"{table}_{_camel_to_snake(str(attr['name']))}".upper()
                vals = [str(v) for v in attr.get("enumValues", [])]
                enum_domains.append((tc, str(attr.get("label", tc)), vals))
    for tc, name, vals in sorted(enum_domains, key=lambda e: e[0]):
        if tc not in seen_domains:
            seen_domains.add(tc)
            domains.append((tc, name))
        for i, v in enumerate(vals):
            items.append((tc, v, v, (i + 1) * 10))
    return domains, items


# ---- 聚合表 ----


def _table_ddl(agg: dict[str, Any]) -> str:
    alias: str = str(agg["alias"])
    table = _table_name(alias)
    lines: list[str] = [f"CREATE TABLE {table} ("]

    column_lines: list[str] = ["    id bigint PRIMARY KEY"]
    constraints: list[str] = []
    for attr in agg.get("attributes", []):
        col_sql, fk = _column_ddl(table, attr)
        column_lines.append(f"    {col_sql}")
        if fk:
            constraints.append(f"    {fk}")
    # D1.03：tenant_id 生成器统一注入（M1 不显式建模）
    column_lines.append("    tenant_id bigint NOT NULL")
    # D1.05：聚合根默认逻辑删除列
    column_lines.append("    deleted boolean NOT NULL DEFAULT false")
    column_lines.append("    created_at timestamptz NOT NULL DEFAULT now()")
    column_lines.append("    updated_at timestamptz NOT NULL DEFAULT now()")
    all_lines = column_lines + constraints
    lines.append(",\n".join(all_lines))
    lines.append(");")
    return "\n".join(lines)


def _column_ddl(table: str, attr: dict[str, Any]) -> tuple[str, str | None]:
    """返回 (列定义行, 内联约束行)。DictionaryRef/Enum 复合外键在此内联（t_dict_data 已先建）。"""
    name = _camel_to_snake(str(attr["name"]))
    sem_type = str(attr["type"])

    if sem_type in ("DictionaryRef", "Enum"):
        if sem_type == "DictionaryRef":
            ref = attr.get("dictionaryRef") or {}
            type_code = str(ref.get("typeCode", ""))
        else:
            type_code = f"{table}_{name}".upper()
        tc_col = f"{name}_dict_type"
        col = f"{name} varchar({_DICT_CODE_LEN}) {'NOT NULL' if attr.get('required') else 'NULL'}"
        gen = f"{tc_col} varchar({_DICT_CODE_LEN}) GENERATED ALWAYS AS ({_sql_str(type_code)}) STORED"
        fk = f"FOREIGN KEY ({tc_col}, {name}) REFERENCES t_dict_data(type_code, code)"
        return f"{col},\n    {gen}", fk

    if sem_type not in _PG_TYPES:
        raise ModelStructureError(f"属性 {name}: type={sem_type} 无 PG 方言映射（D1.02）")
    pg_type = _PG_TYPES[sem_type]
    parts = [f"{name} {pg_type}", "NOT NULL" if attr.get("required") else "NULL"]
    if attr.get("unique"):
        parts.append("UNIQUE")
    if "defaultValue" in attr:
        parts.append(f"DEFAULT {_default_sql(attr['defaultValue'])}")
    return " ".join(parts), None


def _aggregate_fk_alters(aggregates: list[dict]) -> list[str]:
    """AggregateRootRef → 目标聚合表 id 的外键（延迟 ALTER，跨表依赖不受建表顺序影响）。"""
    by_id = {str(a.get("id")): _table_name(str(a["alias"])) for a in aggregates}
    alters: list[str] = []
    for agg in aggregates:
        table = _table_name(str(agg["alias"]))
        for attr in agg.get("attributes", []):
            if str(attr.get("type")) != "AggregateRootRef":
                continue
            target_table = by_id.get(str(attr.get("targetAggregate", "")))
            if not target_table:
                continue
            col = _camel_to_snake(str(attr["name"]))
            cons = f"fk_{table}_{col}_{target_table}"
            alters.append(
                f"ALTER TABLE {table} ADD CONSTRAINT {cons} FOREIGN KEY ({col}) REFERENCES {target_table}(id);"
            )
    return sorted(alters)


# ---- 标量助手 ----


def _sql_str(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _sort_sql(value: Any) -> str:
    return str(value) if isinstance(value, int) else "NULL"


def _as_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _default_sql(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "NULL"
    if isinstance(value, int | float):
        return str(value)
    return _sql_str(str(value))


def _table_name(alias: str) -> str:
    """alias（PascalCase）→ snake_case 表名，统一加 t_ 前缀。"""
    snake = "".join(f"_{c.lower()}" if c.isupper() else c for c in alias).lstrip("_")
    return f"t_{snake}"


def _camel_to_snake(name: str) -> str:
    """属性名 camelCase → 列名 snake_case（PG 不加引号会折叠小写——统一 ORM 约定）。"""
    out: list[str] = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0 and (not name[i - 1].isupper() or (i + 1 < len(name) and name[i + 1].islower())):
            out.append("_")
        out.append(ch.lower())
    return "".join(out)
