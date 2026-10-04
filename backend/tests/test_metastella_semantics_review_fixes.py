"""m2-minset 评审修复批（fresh reviewer 2026-10-04 结论落地）——TDD。

覆盖：C1 发布门禁（§12 发布前必跑全绿）/C2 标识符注入拦截/D1.03 entity 豁免扫描+类型检查/
D1.04 按规范撤拦截（Schema 不拦）/D11.02 指纹对 YAML 原生类型不崩/错误映射 CustomException 单源/
DDL defaultValue 落地/语料跨模型互链完整性。
"""

from datetime import date
from pathlib import Path

import pytest

from app.modules.metastella_semantics import (
    ModelStructureError,
    compute_package_fingerprint,
    load_model_family,
    publish_package,
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


# ---- C1 发布门禁 ----


def test_publish_package_rejects_invalid_model() -> None:
    """§12 发布语义包前必跑校验：坏 M1 的包不得发布。"""
    family = _load()
    family["OBJECT"]["aggregates"][0]["attributes"][0]["type"] = "VARCHAR"
    with pytest.raises(ModelStructureError, match="D1.02"):
        publish_package(family, package_name="bad_pkg")


def test_publish_package_records_pending_chapters() -> None:
    """占位章（M2~MU）不阻断发布，但发布记录显式留痕 validators_pending。"""
    record = publish_package(_load(), package_name="library_smoke")
    assert record["validators_pending"] == ["ACTOR", "BEHAVIOR", "FLOW", "RULE", "UI"]


def test_publish_record_takes_schema_version_from_family() -> None:
    record = publish_package(_load(), package_name="library_smoke")
    assert record["schema_version"] == "1.0.0"


# ---- D11.02 指纹类型面 ----


def test_fingerprint_survives_yaml_native_types() -> None:
    family = _load()
    family["OBJECT"]["aggregates"][0]["attributes"][0]["defaultValue"] = date(2026, 1, 1)
    fp = compute_package_fingerprint(family)
    assert len(fp) == 64


# ---- C2 标识符注入 ----


def test_aggregate_alias_must_be_identifier() -> None:
    family = _load()
    family["OBJECT"]["aggregates"][0]["alias"] = "My Book"
    with pytest.raises(ModelStructureError, match="alias"):
        from app.modules.metastella_semantics import validate_model

        validate_model(family["OBJECT"])


def test_attribute_name_injection_rejected() -> None:
    family = _load()
    family["OBJECT"]["aggregates"][0]["attributes"][0]["name"] = "a; DROP TABLE x"
    with pytest.raises(ModelStructureError, match="name"):
        from app.modules.metastella_semantics import validate_model

        validate_model(family["OBJECT"])


@pytest.mark.parametrize("reserved", ["id", "tenant_id", "deleted", "created_at", "updated_at"])
def test_attribute_name_reserving_generated_columns_rejected(reserved: str) -> None:
    family = _load()
    family["OBJECT"]["aggregates"][0]["attributes"][0]["name"] = reserved
    with pytest.raises(ModelStructureError):
        from app.modules.metastella_semantics import validate_model

        validate_model(family["OBJECT"])


# ---- D1.04：规范说 Schema 不拦 ----


def test_concurrency_unknown_value_not_blocked() -> None:
    """D1.04/D11.07 原文：「字段可不实现、Schema 不拦」——未来值声明不得误杀老包。"""
    from app.modules.metastella_semantics import validate_model

    family = _load()
    family["OBJECT"]["aggregates"][0]["attributes"][0]["concurrency"] = "row_lock"
    validate_model(family["OBJECT"])  # 不抛


# ---- D1.03 豁免扫描面 ----


def test_entity_tenant_scoped_false_requires_registry() -> None:
    from app.modules.metastella_semantics import validate_model

    family = _load()
    family["OBJECT"]["aggregates"][0]["entities"].append(
        {
            "name": "馆藏副本",
            "alias": "BookCopy",
            "description": "副本",
            "localId": "copyId",
            "cardinality": "ZERO_OR_MORE",
            "tenantScoped": False,
            "attributes": [{"name": "copyId", "label": "编号", "type": "String", "required": True}],
        }
    )
    with pytest.raises(ModelStructureError, match="D1.03"):
        validate_model(family["OBJECT"])


def test_tenant_scoped_wrong_type_rejected() -> None:
    from app.modules.metastella_semantics import validate_model

    family = _load()
    family["OBJECT"]["aggregates"][0]["tenantScoped"] = "false"
    with pytest.raises(ModelStructureError, match="tenantScoped"):
        validate_model(family["OBJECT"])


# ---- DDL defaultValue ----


def test_ddl_emits_default_values() -> None:
    from app.modules.metastella_semantics import generate_ddl

    family = _load()
    family["OBJECT"]["aggregates"][0]["attributes"][1]["defaultValue"] = "未命名"
    ddl = generate_ddl(family)
    assert "DEFAULT '未命名'" in ddl


# ---- 语料跨模型互链 ----


def test_corpus_rule_backlinks_behaviors() -> None:
    """M3.reusedBy 引用的行为必须存在，且行为侧 appliedRules 回填（杜绝单向假链）。"""
    family = _load()
    behavior_ids = {b["id"] for b in family["BEHAVIOR"]["behaviors"]}
    rule_ids = {r["id"] for r in family["RULE"]["rules"]}
    for rule in family["RULE"]["rules"]:
        for ref in rule.get("reusedBy", []):
            assert ref in behavior_ids, f"规则 {rule['id']} reusedBy 指向不存在行为 {ref}"
    for behavior in family["BEHAVIOR"]["behaviors"]:
        for ref in behavior.get("appliedRules", []):
            assert ref in rule_ids, f"行为 {behavior['id']} appliedRules 指向不存在规则 {ref}"
    assert family["RULE"]["rules"][0]["id"] in {
        r for b in family["BEHAVIOR"]["behaviors"] for r in b.get("appliedRules", [])
    }, "借阅上限规则未回填行为侧（单向链）"


def test_corpus_mu_action_points_trace_to_behaviors() -> None:
    family = _load()
    behavior_ids = {b["id"] for b in family["BEHAVIOR"]["behaviors"]}
    for screen in family["UI"]["screens"]:
        for ap in screen.get("actionPoints", []):
            assert ap["behaviorRef"] in behavior_ids, f"操作点 {ap['id']} 挂空行为"
    assert any(b["id"] == "Book_query" for b in family["BEHAVIOR"]["behaviors"]), "缺图书查询行为（MU 搜索点正主）"


# ---- API 错误映射（CustomException 单源） ----


def test_api_publish_conflict_returns_409_and_single_source() -> None:
    """删 controller 私有注册表后：同指纹重发布经引擎层判重→409；首发布必须 200。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.core.exceptions import handle_exception
    from app.plugin.module_metastella.semantics.controller import MetastellaRouter

    minimal = FastAPI()
    minimal.include_router(MetastellaRouter, prefix="/metastella")
    handle_exception(minimal)
    client = TestClient(minimal)
    first = client.post("/metastella/packages/library_smoke/publish")
    assert first.status_code == 200, first.text
    second = client.post("/metastella/packages/library_smoke/publish")
    assert second.status_code == 409


def test_api_broken_package_returns_4xx_not_500(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """manifest 指向缺失文件/族不一致/未知类型=客户端可修正错误，不得裸穿 500。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import app.plugin.module_metastella.semantics.controller as controller_mod
    from app.core.exceptions import handle_exception

    pkg = tmp_path / "broken_pkg"
    pkg.mkdir()
    (pkg / "manifest.yaml").write_text(
        "schema_version: \"1.0.0\"\nmodel_type: MANIFEST\nmodel_files: [no_such.yaml]\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(controller_mod, "PACKAGES_ROOT", tmp_path)

    minimal = FastAPI()
    minimal.include_router(controller_mod.MetastellaRouter, prefix="/metastella")
    handle_exception(minimal)
    resp = TestClient(minimal).get("/metastella/packages/broken_pkg/manifest")
    assert resp.status_code < 500, resp.text
