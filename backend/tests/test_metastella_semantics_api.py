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
    # M2~MU 深度校验章未落地——显式留痕（占位≠通过伪装）
    assert data["validators_pending"] == ["ACTOR", "BEHAVIOR", "FLOW", "RULE", "UI"]


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


def test_unknown_package_returns_404() -> None:
    resp = _client().get("/metastella/packages/no_such_pkg/manifest")
    assert resp.status_code == 404
