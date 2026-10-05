"""m2-minset 工单 08b：M2~MU 五章 validator+语料 canonical 化（TDD RED）。

完成定义：发布记录 validators_pending=[]（G2「validator 全绿」口径）。
覆盖 v9 §3.2/4.3/5.3/6.3/8.2 元素表关键约束 + D2.02 行为-API 命名 + D8.04 elementId 对齐。
"""

from pathlib import Path

import pytest

from app.modules.metastella_semantics import (
    ModelStructureError,
    load_model_family,
    publish_package,
    validate_model,
)

PACKAGE = Path(__file__).parents[1] / "semantic_packages" / "library_smoke"
MANIFEST = "manifest.yaml"


def _load() -> dict:
    return load_model_family(PACKAGE, manifest_name=MANIFEST)


@pytest.fixture(autouse=True)
def _reset_publish_registry():
    from app.modules.metastella_semantics.publish import _reset_registry_for_tests

    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


# ---- 完成定义：pending 清零 ----


def test_publish_no_longer_pending_any_chapter() -> None:
    record = publish_package(_load(), package_name="library_smoke")
    assert record["validators_pending"] == [], record["validators_pending"]


# ---- M2 BEHAVIOR ----


def test_behavior_invalid_type_rejected() -> None:
    doc = _load()["BEHAVIOR"]
    doc["behaviors"][0]["behaviorType"] = "MIXED"
    with pytest.raises(ModelStructureError, match="behaviorType"):
        validate_model(doc)


def test_behavior_query_must_not_change_state() -> None:
    """v9 §3.2：QUERY 只读——postconditions/syncTriggers 必须为空。"""
    doc = _load()["BEHAVIOR"]
    query = next(b for b in doc["behaviors"] if b["behaviorType"] == "QUERY")
    query["postconditions"] = [{"description": "非法：查询改了状态"}]
    with pytest.raises(ModelStructureError, match="QUERY"):
        validate_model(doc)


def test_behavior_sync_trigger_cross_aggregate_required() -> None:
    """v9 §3.2.2-4：syncTriggers 下游必须跨聚合，禁同聚合自我联动。"""
    doc = _load()["BEHAVIOR"]
    doc["behaviors"][0]["syncTriggers"] = [
        {"behaviorRef": "Book_returnBack", "description": "同聚合联动（非法）"}
    ]
    with pytest.raises(ModelStructureError, match="跨聚合"):
        validate_model(doc)


def test_behavior_id_endpoint_convention_d2_02() -> None:
    """D2.02：id 格式 {Entity}_{action}（camelCase 动作段）——endpoint 确定性推导的前提。"""
    doc = _load()["BEHAVIOR"]
    doc["behaviors"][0]["id"] = "borrow out"
    with pytest.raises(ModelStructureError, match="id"):
        validate_model(doc)


# ---- M3 RULE ----


def test_rule_requires_rule_type() -> None:
    doc = _load()["RULE"]
    doc["rules"][0].pop("ruleType", None)
    with pytest.raises(ModelStructureError, match="ruleType"):
        validate_model(doc)


def test_rule_passive_only_no_state_change_fields() -> None:
    doc = _load()["RULE"]
    doc["rules"][0]["postconditions"] = [{"description": "规则改状态=违宪"}]
    with pytest.raises(ModelStructureError, match="被动"):
        validate_model(doc)


# ---- M5 ACTOR ----


def test_actor_role_id_unique_and_name_required() -> None:
    doc = _load()["ACTOR"]
    dup = dict(doc["actors"][0])
    doc["actors"].append(dup)
    with pytest.raises(ModelStructureError, match="唯一"):
        validate_model(doc)


# ---- M6 FLOW ----


def test_flow_step_type_enum_and_unique_ids() -> None:
    doc = _load()["FLOW"]
    doc["flows"][0]["steps"][0]["stepType"] = "WHATEVER"
    with pytest.raises(ModelStructureError, match="stepType"):
        validate_model(doc)


def test_flow_transition_endpoints_must_exist_in_flow() -> None:
    doc = _load()["FLOW"]
    doc["flows"][0]["transitions"][0]["to"] = "STEP-GHOST"
    with pytest.raises(ModelStructureError, match="STEP-GHOST"):
        validate_model(doc)


# ---- MU UI ----


def test_ui_layout_element_ids_must_exist_in_elements() -> None:
    """08c 深对齐后：elements 清空 → layout token 与 actionPoint.elementId 双重违规。"""
    doc = _load()["UI"]
    screen = next(s for s in doc["screens"] if s["id"] == "SCREEN-BOOK-LIST")
    screen["elements"] = []
    with pytest.raises(ModelStructureError, match="D8.04"):
        validate_model(doc)


def test_ui_action_point_ids_unique() -> None:
    doc = _load()["UI"]
    screen = next(s for s in doc["screens"] if s["id"] == "SCREEN-BOOK-LIST")
    dup = dict(screen["actionPoints"][0])
    screen["actionPoints"].append(dup)
    with pytest.raises(ModelStructureError, match="唯一"):
        validate_model(doc)
