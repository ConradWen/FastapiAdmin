"""m2-minset 工单 05b：语义引擎 API 骨架单测（TDD RED 阶段）。

四端点（D2.02 命名纪律）：
- GET  /metastella/packages/{pkg}/manifest      族装载
- POST /metastella/packages/{pkg}/validate      校验
- POST /metastella/packages/{pkg}/publish       发布（指纹钉死）
- POST /metastella/packages/{pkg}/ddl           DDL 生成
路由前缀按底座 discover 约定：module_metastella → /metastella。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.exceptions import handle_exception
from app.plugin.module_metastella.semantics.controller import MetastellaRouter


@pytest.fixture(autouse=True)
def _reset_publish_registry():
    """发布判重单源在引擎层——逐测试清空，杜绝顺序耦合。"""
    from app.modules.metastella_semantics.publish import _reset_registry_for_tests

    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


def _client() -> TestClient:
    """最小 app 按 discover 同构挂载（module_metastella → /metastella 容器前缀）+底座异常处理器；
    不拉起平台全栈（底座 database.py 模块级连库，M2 无 DB 依赖冒烟）。"""
    minimal = FastAPI()
    minimal.include_router(MetastellaRouter, prefix="/metastella")
    handle_exception(minimal)
    return TestClient(minimal)


def test_manifest_endpoint_loads_library_smoke() -> None:
    resp = _client().get("/metastella/packages/library_smoke/manifest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["model_types"] == ["ACTOR", "BEHAVIOR", "FLOW", "OBJECT", "RULE", "UI"]
    assert body["data"]["schema_version"] == "1.0.0"


def test_validate_endpoint_green_for_library_smoke() -> None:
    resp = _client().post("/metastella/packages/library_smoke/validate")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["valid"] is True
    assert data["errors"] == []
    # 08b：最小集六章 validator 全在位，pending 清零（G2「validator 全绿」口径）
    assert data["validators_pending"] == []


def test_publish_endpoint_returns_fingerprint() -> None:
    resp = _client().post("/metastella/packages/library_smoke/publish")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "PUBLISHED"
    assert data["schema_version"] == "1.0.0"
    assert len(data["fingerprint"]) == 64


def test_publish_endpoint_rejects_republish() -> None:
    client = _client()
    first = client.post("/metastella/packages/library_smoke/publish")
    assert first.status_code == 200, first.text
    resp = client.post("/metastella/packages/library_smoke/publish")
    assert resp.status_code == 409


def test_ddl_endpoint_deterministic() -> None:
    d1 = _client().post("/metastella/packages/library_smoke/ddl").json()["data"]["ddl"]
    d2 = _client().post("/metastella/packages/library_smoke/ddl").json()["data"]["ddl"]
    assert d1 == d2
    assert "CREATE TABLE t_book" in d1


def test_migration_endpoint_deterministic() -> None:
    c = _client()
    r1 = c.post("/metastella/packages/library_smoke/migration")
    assert r1.status_code == 200
    r2 = c.post("/metastella/packages/library_smoke/migration")
    assert r1.json()["data"]["script"] == r2.json()["data"]["script"]
    assert "def upgrade()" in r1.json()["data"]["script"]


def test_unknown_package_returns_404() -> None:
    resp = _client().get("/metastella/packages/no_such_pkg/manifest")
    assert resp.status_code == 404


def test_generation_endpoints_gate_invalid_package(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """阶段审计 B-C2：生成链与发布链同门禁——坏包不得产出 DDL/迁移。"""
    from app.plugin.module_metastella.semantics import controller as cmod

    pkg = tmp_path / "bad_pkg"
    pkg.mkdir()
    (pkg / "manifest.yaml").write_text(
        "schema_version: \"1.0.0\"\nmodel_type: MANIFEST\nmodel_files: [m1.yaml]\n", encoding="utf-8"
    )
    (pkg / "m1.yaml").write_text(
        "schema_version: \"1.0.0\"\nmodel_type: OBJECT\naggregates:\n"
        "  - id: AGG-X-001\n    name: 坏聚合\n    alias: My Book\n"
        "    aggregateType: AGGREGATE_ROOT\n    attributes: []\n"
        "    entities: []\n    valueObjects: []\n    invariants: []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cmod, "PACKAGES_ROOT", tmp_path)
    client = _client()
    for path in ("/ddl", "/migration"):
        resp = client.post(f"/metastella/packages/bad_pkg{path}")
        assert resp.status_code == 422, (path, resp.text)
    ok = client.post("/metastella/packages/bad_pkg/publish")
    assert ok.status_code == 422, ok.text  # 发布链同样被拒（同一坏包）
