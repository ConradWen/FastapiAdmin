"""审计修复批（语义引擎 Important）：B-I7 指纹非单射 / B-I2 族成员缺失放行 / B-I1 引用机检漏字段。"""

from pathlib import Path

import pytest

from app.modules.metastella_semantics import (
    ModelStructureError,
    compute_package_fingerprint,
    load_model_family,
    publish_package,
    validate_model,
)

PACKAGE = Path(__file__).parents[1] / "semantic_packages" / "library_smoke"


def _load() -> dict:
    return load_model_family(PACKAGE, manifest_name="manifest.yaml")


# ---- B-I7: canonical_json 非单射（date 与 其字符串形态不得同指纹）----


def test_fingerprint_distinguishes_date_from_string() -> None:
    from datetime import date

    f1 = _load()
    f2 = _load()
    f1["OBJECT"]["aggregates"][0]["attributes"][0]["defaultValue"] = "2026-01-01"
    f2["OBJECT"]["aggregates"][0]["attributes"][0]["defaultValue"] = date(2026, 1, 1)
    assert compute_package_fingerprint(f1) != compute_package_fingerprint(f2), (
        "B-I7: date 与同形字符串经 default=str 后撞指纹 → F-3 会误判已发布"
    )


# ---- B-I2: 族成员缺失不得静默放行（D13.01 最小集六件=发布单元）----


def test_publish_requires_minimal_family_members() -> None:
    family = {"OBJECT": _load()["OBJECT"]}
    with pytest.raises(ModelStructureError, match="最小集"):
        publish_package(family, package_name="partial_pkg")


# ---- B-I1: 引用完整性机检不得漏字段 ----


def test_sync_trigger_rule_ref_must_exist() -> None:
    from app.modules.metastella_semantics import check_family

    family = _load()
    family["BEHAVIOR"]["behaviors"][0]["syncTriggers"] = [{"behaviorRef": "Book_returnBack", "ruleRef": "RULE-NOPE"}]
    # Book_borrowOut→Book_returnBack 同 ownerEntity 会先触发跨聚合守卫，故用合法跨聚合组合验证 ruleRef：
    family["BEHAVIOR"]["behaviors"][0]["syncTriggers"] = [{"behaviorRef": "Reader_register", "ruleRef": "RULE-NOPE"}]
    with pytest.raises(Exception, match="RULE-NOPE"):
        check_family(family, raise_on_error=True)


def test_owner_entity_required_in_behavior() -> None:
    family = _load()
    del family["BEHAVIOR"]["behaviors"][0]["ownerEntity"]
    with pytest.raises(ModelStructureError, match="ownerEntity"):
        validate_model(family["BEHAVIOR"])
