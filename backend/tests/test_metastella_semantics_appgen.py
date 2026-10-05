"""m2-minset 工单 07/W2b：生成物应用骨架构建器单测（行为断言版）。

审计修复：07 版只断言源码文本含 "401"/WHERE——改为**执行生成路由**验证行为：
无头 401 / 头注入 SQL 参数 / 产物无内嵌凭据 / 确定性 / compile 合法。
"""

import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.modules.metastella_semantics import generate_app_bundle, load_model_family

PACKAGE = Path(__file__).parents[1] / "semantic_packages" / "library_smoke"
MANIFEST = "manifest.yaml"

captured: list = []


def _exec_main(bundle: dict[str, str]) -> types.ModuleType:
    main = types.ModuleType("gen_main")
    exec(compile(bundle["main.py"], "main.py", "exec"), main.__dict__)  # noqa: S102 — 生成物自足模板
    return main


class _FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        captured.append((sql, params))

    def fetchall(self):
        return []


class _FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return _FakeCursor()


@pytest.fixture()
def fake_psycopg(monkeypatch: pytest.MonkeyPatch):
    captured.clear()
    fake = types.ModuleType("psycopg")
    fake.connect = lambda dsn: _FakeConn()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "psycopg", fake)
    monkeypatch.setenv("DATABASE_URI", "postgresql://x@example.invalid/db")
    return fake


def test_bundle_is_deterministic() -> None:
    assert generate_app_bundle(_load(), package_name="library_smoke") == generate_app_bundle(
        _load(), package_name="library_smoke"
    )


def _load() -> dict:
    return load_model_family(PACKAGE, manifest_name=MANIFEST)


def test_bundle_python_files_compile() -> None:
    bundle = generate_app_bundle(_load(), package_name="library_smoke")
    for name, src in bundle.items():
        if name.endswith(".py"):
            compile(src, name, "exec")


def test_bundle_has_aggregate_list_routes() -> None:
    bundle = generate_app_bundle(_load(), package_name="library_smoke")
    assert "/api/Book/list" in bundle["main.py"]
    assert "/api/BorrowRecord/list" in bundle["main.py"]


def test_bundle_carries_no_embedded_credentials() -> None:
    """产物无密钥不变量：DSN/口令不得进生成源码（阶段审计 B-C4）。"""
    bundle = generate_app_bundle(_load(), package_name="library_smoke")
    src = bundle["main.py"]
    for banned in ("metastella_dev", "postgres:5432", "DEFAULT_DSN"):
        assert banned not in src, f"生成物内嵌了敏感默认值: {banned}"


def test_list_requires_tenant_header(fake_psycopg) -> None:
    main = _exec_main(generate_app_bundle(_load(), package_name="library_smoke"))
    client = TestClient(main.app)
    assert client.get("/api/Book/list").status_code == 401
    assert client.get("/api/Book/list", headers={"X-Tenant-Id": "not-a-number"}).status_code == 400
    resp = client.get("/api/Book/list", headers={"X-Tenant-Id": "7"})
    assert resp.status_code == 200
    sql, params = captured[-1]
    assert "tenant_id = %s" in sql and params == (7,), "租户过滤必须参数化并绑定会话值"
    assert "t_book" in sql


def test_list_without_database_uri_fails_loudly(fake_psycopg, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URI")
    main = _exec_main(generate_app_bundle(_load(), package_name="library_smoke"))
    resp = TestClient(main.app).get("/api/Book/list", headers={"X-Tenant-Id": "1"})
    assert resp.status_code == 500
