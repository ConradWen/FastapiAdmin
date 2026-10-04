"""m2-minset 工单 03：图书考题六模型语料冒烟（TDD RED 阶段）。

语料落 fba/backend/semantic_packages/library_smoke/：manifest + M1 对象模型先行（工单 02 validator 实测面）；
M2/M3/M5/M6/MU 五件元文件随骨架落位（model_type 已注册，validator 占位章仅走注册识别）。
本测试=工单 03 验收的核心断言：语料必须全量装载+全量过校验。
"""

from pathlib import Path

import pytest

from app.modules.metastella_semantics import load_model_family

PACKAGE = Path(__file__).parents[1] / "semantic_packages" / "library_smoke"
MANIFEST = "manifest.yaml"  # §0.3：元文件一律 YAML（族装载显式指定，默认 manifest.json 为兼容项）

REQUIRED_MODELS = {"OBJECT", "BEHAVIOR", "RULE", "ACTOR", "FLOW", "UI"}


def test_library_smoke_package_exists() -> None:
    assert (PACKAGE / MANIFEST).is_file(), f"缺 manifest: {PACKAGE}"


def test_library_smoke_manifest_declares_six_models() -> None:
    family_files = load_model_family(PACKAGE, manifest_name=MANIFEST)
    assert REQUIRED_MODELS <= set(family_files), f"缺模型文件: {REQUIRED_MODELS - set(family_files)}"


def test_library_smoke_all_models_load_and_version_consistent() -> None:
    family = load_model_family(PACKAGE, manifest_name=MANIFEST)
    assert len(family) == 6
    versions = {doc["schema_version"] for doc in family.values()}
    assert versions == {"1.0.0"}


def test_library_smoke_m1_passes_object_validator() -> None:
    family = load_model_family(PACKAGE, manifest_name=MANIFEST)
    from app.modules.metastella_semantics import validate_model

    validate_model(family["OBJECT"])  # 不抛=过


def test_library_smoke_covers_three_business_faces() -> None:
    """三大业务面：封面（图书元数据）/借阅（核心交易）/读者（主体）。"""
    family = load_model_family(PACKAGE, manifest_name=MANIFEST)
    m1 = family["OBJECT"]
    aggregate_aliases = {agg["alias"] for agg in m1["aggregates"]}
    assert {"Book", "BorrowRecord", "Reader"} <= aggregate_aliases


def test_library_smoke_m1_covers_dictionary_and_reference_and_invariant() -> None:
    """M1 必须覆盖三类元素实测：字典引用/聚合引用/不变量（工单 02 validator 的真实语料命中）。"""
    family = load_model_family(PACKAGE, manifest_name=MANIFEST)
    m1 = family["OBJECT"]
    root = m1["aggregates"][0]
    types_used = {attr["type"] for agg in m1["aggregates"] for attr in agg["attributes"]}
    assert "DictionaryRef" in types_used
    assert "AggregateRootRef" in types_used
    assert any(agg.get("invariants") for agg in m1["aggregates"])
    assert m1["data_dictionaries"], "缺数据字典"


def test_library_smoke_m1_has_no_tenant_id_attribute() -> None:
    """D1.03 机检实测：语料中不得出现 tenant_id 显式建模。"""
    family = load_model_family(PACKAGE, manifest_name=MANIFEST)
    for agg in family["OBJECT"]["aggregates"]:
        for attr in agg.get("attributes", []):
            assert attr["name"] not in {"tenantId", "tenant_id"}


@pytest.mark.parametrize(
    ("model_key", "required_keys"),
    [
        ("BEHAVIOR", {"behaviors"}),
        ("RULE", {"rules"}),
        ("ACTOR", {"actors"}),
        ("FLOW", {"flows"}),
        ("UI", {"screens"}),
    ],
)
def test_library_smoke_model_files_carry_top_level_collections(model_key: str, required_keys: set[str]) -> None:
    family = load_model_family(PACKAGE, manifest_name=MANIFEST)
    doc = family[model_key]
    missing = required_keys - set(doc)
    assert not missing, f"{model_key} 缺顶层集合: {missing}"
