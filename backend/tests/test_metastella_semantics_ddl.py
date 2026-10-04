"""m2-minset 工单 05a：M1→PG DDL 确定性生成器单测（TDD RED 阶段）。

验收核心：同语义包重复生成同 DDL（D1.06 确定性；字节级一致断言）。
类型映射钉 PG 方言（D1.02）；tenant_id 由生成器统一注入（D1.03）；deleted 列随聚合根默认带（D1.05）。
"""

from pathlib import Path

from app.modules.metastella_semantics import generate_ddl, load_model_family

PACKAGE = Path(__file__).parents[1] / "semantic_packages" / "library_smoke"
MANIFEST = "manifest.yaml"


def _load() -> dict:
    return load_model_family(PACKAGE, manifest_name=MANIFEST)


def test_ddl_column_names_are_snake_case() -> None:
    """容器冒烟抓出：camelCase 不加引号进 PG 折叠为小写——生成列名必须 snake_case（PG/ORM 约定）。"""
    ddl = generate_ddl(_load())
    assert "book_no" in ddl
    assert "category_code" in ddl
    assert "borrow_no" in ddl


def test_same_package_generates_identical_ddl() -> None:
    """D1.06 确定性铁律：同包 N 次生成字节级一致。"""
    family = _load()
    ddl1 = generate_ddl(family)
    ddl2 = generate_ddl(_load())
    assert ddl1 == ddl2


def test_ddl_covers_all_aggregates_and_is_pg_dialect() -> None:
    ddl = generate_ddl(_load())
    for table in ("t_book", "t_reader", "t_borrow_record"):
        assert f"CREATE TABLE {table}" in ddl, f"缺表 {table}"
    assert "CREATE TABLE" in ddl
    # D1.02 方言抽查：numeric/timestamptz/varchar 出现（PG 专属字样）
    assert "numeric(" in ddl
    assert "timestamptz" in ddl


def test_ddl_maps_type_system_d1_02() -> None:
    ddl = generate_ddl(_load())
    # String→varchar(n)/Money→numeric(18,2)/Date→date
    assert "varchar(" in ddl
    assert "numeric(18, 2)" in ddl or "numeric(18,2)" in ddl
    assert "date" in ddl


def test_ddl_injects_tenant_id_d1_03() -> None:
    """D1.03：tenant_id 由生成器统一注入（M1 模型未显式建模）。"""
    ddl = generate_ddl(_load())
    assert ddl.count("tenant_id bigint NOT NULL") >= 3  # 三张业务表各一


def test_ddl_appends_deleted_column_d1_05() -> None:
    """D1.05：聚合根默认携带 deleted 逻辑删除列。"""
    ddl = generate_ddl(_load())
    assert ddl.count("deleted boolean NOT NULL DEFAULT false") == 3


def test_ddl_deterministic_across_key_order() -> None:
    family = _load()
    ddl1 = generate_ddl(family)
    reordered = {k: dict(reversed(list(v.items()))) for k, v in family.items()}
    assert generate_ddl(reordered) == ddl1
