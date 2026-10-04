"""m2-minset 工单 07：生成物应用骨架构建器单测（TDD RED 阶段）。

确定性生成：同包→同文件集（字节级）。产物=可运行 FastAPI 应用（health+聚合路由面）。
DB 冒烟（迁移后起服）在 docker 环节做，本测试只测生成面与 health 路由。
"""

import types
from pathlib import Path

from app.modules.metastella_semantics import generate_app_bundle, load_model_family

PACKAGE = Path(__file__).parents[1] / "semantic_packages" / "library_smoke"
MANIFEST = "manifest.yaml"


def _load() -> dict:
    return load_model_family(PACKAGE, manifest_name=MANIFEST)


def _exec_main(bundle: dict[str, str]) -> types.ModuleType:
    main = types.ModuleType("gen_main")
    exec(compile(bundle["main.py"], "main.py", "exec"), main.__dict__)  # noqa: S102 — 生成物自足模板
    return main


def test_bundle_is_deterministic() -> None:
    assert generate_app_bundle(_load(), package_name="library_smoke") == generate_app_bundle(
        _load(), package_name="library_smoke"
    )


def test_bundle_python_files_compile() -> None:
    bundle = generate_app_bundle(_load(), package_name="library_smoke")
    for name, src in bundle.items():
        if name.endswith(".py"):
            compile(src, name, "exec")


def test_bundle_app_serves_health() -> None:
    from fastapi.testclient import TestClient

    main = _exec_main(generate_app_bundle(_load(), package_name="library_smoke"))
    resp = TestClient(main.app).get("/health")
    assert resp.status_code == 200
    assert resp.json()["package"] == "library_smoke"


def test_bundle_has_aggregate_list_routes() -> None:
    bundle = generate_app_bundle(_load(), package_name="library_smoke")
    assert "/api/Book/list" in bundle["main.py"]
    assert "/api/BorrowRecord/list" in bundle["main.py"]
