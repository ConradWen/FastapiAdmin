"""m2-minset 工单 08a：族级跨模型机检单测（§12 清单最小集相关项，TDD RED）。

error 级阻断发布：引用完整性/权限位/角色引用/审批双出边/密钥零落盘；
warning 级留痕：表达式语体一致性（D3.01/D6.03 杜绝双定义）。
"""

from pathlib import Path

import pytest

from app.modules.metastella_semantics import ModelStructureError, check_family, load_model_family

PACKAGE = Path(__file__).parents[1] / "semantic_packages" / "library_smoke"
MANIFEST = "manifest.yaml"


def _load() -> dict:
    return load_model_family(PACKAGE, manifest_name=MANIFEST)


def test_current_corpus_passes_family_checks() -> None:
    result = check_family(_load(), package="library_smoke")
    assert result.errors == [], result.errors
    assert result.package == "library_smoke"


# ---- 引用完整性 ----


def test_behavior_applied_rule_must_exist() -> None:
    family = _load()
    family["BEHAVIOR"]["behaviors"][0]["appliedRules"].append("RULE-MISSING-999")
    with pytest.raises(ModelStructureError, match="RULE-MISSING-999"):
        check_family(family, raise_on_error=True)


def test_rule_reused_by_must_exist() -> None:
    family = _load()
    family["RULE"]["rules"][0]["reusedBy"].append("Ghost_Behavior")
    with pytest.raises(ModelStructureError, match="Ghost_Behavior"):
        check_family(family, raise_on_error=True)


def test_flow_behavior_ref_must_exist() -> None:
    family = _load()
    family["FLOW"]["flows"][0]["steps"][0]["behaviorRef"] = "Book_missing"
    with pytest.raises(ModelStructureError, match="Book_missing"):
        check_family(family, raise_on_error=True)


def test_flow_role_ref_must_exist_in_actor_model() -> None:
    family = _load()
    family["FLOW"]["flows"][0]["steps"][1]["roleRef"] = "ROLE-GHOST"
    with pytest.raises(ModelStructureError, match="ROLE-GHOST"):
        check_family(family, raise_on_error=True)


def test_action_point_behavior_ref_must_exist() -> None:
    family = _load()
    family["UI"]["screens"][0]["actionPoints"][0]["behaviorRef"] = "Book_ghost"
    with pytest.raises(ModelStructureError, match="Book_ghost"):
        check_family(family, raise_on_error=True)


def test_user_action_behavior_must_be_reachable_from_ui() -> None:
    """v9 §3.4 可追溯门禁：USER_ACTION 行为至少被一个 MU 操作点引用（禁孤儿行为）。"""
    family = _load()
    family["UI"]["screens"][0]["actionPoints"] = [
        ap
        for ap in family["UI"]["screens"][0]["actionPoints"]
        if ap["behaviorRef"] != "Book_borrowOut"
    ]
    for screen in family["UI"]["screens"]:
        screen["actionPoints"] = [
            ap for ap in screen.get("actionPoints", []) if ap["behaviorRef"] != "Book_borrowOut"
        ]
    with pytest.raises(ModelStructureError, match="Book_borrowOut"):
        check_family(family, raise_on_error=True)


def test_owner_entity_must_exist_in_m1() -> None:
    family = _load()
    family["BEHAVIOR"]["behaviors"][0]["ownerEntity"] = "Ghost"
    with pytest.raises(ModelStructureError, match="Ghost"):
        check_family(family, raise_on_error=True)


# ---- 权限位 ----


def test_required_permission_must_exist_in_actor_model() -> None:
    family = _load()
    family["BEHAVIOR"]["behaviors"][0]["requiredPermissions"] = [{"code": "PERM-LIBRARY-GHOST"}]
    with pytest.raises(ModelStructureError, match="PERM-LIBRARY-GHOST"):
        check_family(family, raise_on_error=True)


def test_permission_code_format_enforced() -> None:
    family = _load()
    family["ACTOR"]["actors"][0]["permissions"][0]["code"] = "perm-library-borrow"
    with pytest.raises(ModelStructureError, match="PERM-"):
        check_family(family, raise_on_error=True)


# ---- 角色引用（M6 人工任务禁自由文本/actorId） ----


def test_human_task_requires_role_ref() -> None:
    family = _load()
    del family["FLOW"]["flows"][0]["steps"][1]["roleRef"]
    with pytest.raises(ModelStructureError, match="roleRef"):
        check_family(family, raise_on_error=True)


def test_human_task_forbids_actor_id() -> None:
    family = _load()
    family["FLOW"]["flows"][0]["steps"][1]["actorId"] = "some-user"
    with pytest.raises(ModelStructureError, match="actorId"):
        check_family(family, raise_on_error=True)


# ---- 审批双出边（D6.05） ----


def test_approval_step_needs_approve_and_reject_out_edges() -> None:
    family = _load()
    steps = family["FLOW"]["flows"][0]["steps"]
    steps.insert(2, {"id": "STEP-APPROVE", "name": "审批", "stepType": "APPROVAL_TASK", "roleRef": "ROLE-LIBRARIAN"})
    family["FLOW"]["flows"][0]["transitions"].append({"from": "STEP-BORROW-OK", "to": "STEP-APPROVE"})
    family["FLOW"]["flows"][0]["transitions"].append({"from": "STEP-APPROVE", "to": "STEP-RETURN-REQ"})
    with pytest.raises(ModelStructureError, match="APPROVAL_TASK"):
        check_family(family, raise_on_error=True)

    # 补 reject 出边后过
    family["FLOW"]["flows"][0]["transitions"].append(
        {"from": "STEP-APPROVE", "to": "STEP-RETURN-OK", "outcome": "approve"}
    )
    family["FLOW"]["flows"][0]["transitions"].append(
        {"from": "STEP-APPROVE", "to": "STEP-BORROW-OK", "outcome": "reject"}
    )
    result = check_family(family)
    assert "APPROVAL_TASK" not in " ".join(result.errors)


# ---- 表达式语体一致性（warning 不阻断） ----


def test_duplicate_expression_warns_not_blocks() -> None:
    family = _load()
    dup = family["BEHAVIOR"]["behaviors"][0]["preconditions"][0]["expression"]
    family["FLOW"]["flows"][0]["transitions"][0]["conditionExpression"] = dup
    result = check_family(family)
    assert not result.errors
    assert any("表达式" in w or dup in w for w in result.warnings)


# ---- 密钥零落盘 ----


def test_secret_literal_rejected() -> None:
    family = _load()
    family["OBJECT"]["aggregates"][0]["attributes"][0]["description"] = "api_key=sk-live-abcdef123456"
    with pytest.raises(ModelStructureError, match="密钥"):
        check_family(family, raise_on_error=True)


# ---- 角色继承（D5.04） ----


def test_role_inheritance_cycle_rejected() -> None:
    family = _load()
    family["ACTOR"]["actors"][0]["inherits"] = ["ROLE-READER"]
    family["ACTOR"]["actors"][1]["inherits"] = ["ROLE-LIBRARIAN"]
    with pytest.raises(ModelStructureError, match="环"):
        check_family(family, raise_on_error=True)
