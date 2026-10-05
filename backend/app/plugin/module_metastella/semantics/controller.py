"""metastella 语义引擎 API 骨架（m2-minset 工单 05b/08a/W2a）。

四端点消费 backend/semantic_packages/ 下的语义包；发布判重**单一事实源=PG 台账**
（env LEDGER_DSN 启用；未设退回进程内注册表——降级不吞发布）。
"""

import os
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter

from app.common.enums import RET
from app.common.response import SuccessResponse
from app.core.exceptions import CustomException
from app.modules.metastella_semantics import (
    ModelPackageAlreadyPublishedError,
    check_family,
    compute_package_fingerprint,
    generate_ddl,
    generate_migration,
    load_model_family,
    publish_package,
    validate_model,
)
from app.modules.metastella_semantics.errors import SemanticSchemaError
from app.modules.metastella_semantics.publish_ledger import ensure_ledger

MetastellaRouter = APIRouter(prefix="/packages", tags=["MetaStella 语义引擎"])

# app/plugin/module_metastella/semantics/controller.py → parents[4] = backend/
# semantic_packages/ 与 app/ 平级（backend/semantic_packages/library_smoke/...）
PACKAGES_ROOT = Path(__file__).parents[4] / "semantic_packages"
_MANIFEST = "manifest.yaml"

_ledger_state: dict[str, Any] = {"conn": None, "tried": False}


def _open_ledger():
    """台账连接（F-3 跨重启）：env LEDGER_DSN 设置即启用；未设/不可达退回进程内注册表（测试无库可跑）。"""
    if not _ledger_state["tried"]:
        _ledger_state["tried"] = True
        dsn = os.environ.get("LEDGER_DSN", "").strip()
        if dsn:
            try:
                import psycopg

                conn = psycopg.connect(dsn, connect_timeout=3)
                ensure_ledger(conn)
                _ledger_state["conn"] = conn
            except Exception:  # noqa: BLE001 — 台账缺席只降级不吞发布
                _ledger_state["conn"] = None
    return _ledger_state["conn"]


def _load_family_or_404(pkg: str) -> dict:
    pkg_dir = PACKAGES_ROOT / pkg
    manifest = pkg_dir / _MANIFEST
    if not manifest.is_file():
        raise CustomException(msg=f"语义包 {pkg} 不存在", code=RET.NOT_FOUND.code)
    try:
        return load_model_family(pkg_dir, manifest_name=_MANIFEST)
    except (SemanticSchemaError, FileNotFoundError, yaml.YAMLError) as exc:
        raise CustomException(msg=str(exc), code=RET.UNPROCESSABLE_ENTITY.code) from exc


def _validated_family_or_404(pkg: str) -> dict:
    """生成链门禁（阶段审计 B-C2）：DDL/迁移产物必须过与发布同一 §12 门禁——
    语义包是不可信输入，坏包不得变成 DDL/迁移/应用代码（'AI 不进编译核心'的前提）。"""
    family = _load_family_or_404(pkg)
    for model_type in sorted(family):
        try:
            validate_model(family[model_type])
        except NotImplementedError:
            continue  # 扩展族占位章：不阻断（发布记录里另有留痕）
        except SemanticSchemaError as exc:
            raise CustomException(msg=str(exc), code=RET.UNPROCESSABLE_ENTITY.code) from exc
    try:
        check_family(family, package=pkg, raise_on_error=True)
    except SemanticSchemaError as exc:
        raise CustomException(msg=str(exc), code=RET.UNPROCESSABLE_ENTITY.code) from exc
    return family


@MetastellaRouter.get("/{pkg}/manifest", summary="装载语义包族")
async def get_package_manifest_controller(pkg: str):
    family = _load_family_or_404(pkg)
    versions = {doc.get("schema_version") for doc in family.values()}
    return SuccessResponse(
        data={
            "package": pkg,
            "schema_version": versions.pop() if len(versions) == 1 else None,
            "model_types": sorted(family),
        },
        msg="装载成功",
    )


@MetastellaRouter.post("/{pkg}/validate", summary="校验语义包（发布前硬门禁）")
async def post_package_validate_controller(pkg: str):
    family = _load_family_or_404(pkg)
    errors: list[str] = []
    pending: list[str] = []
    for model_type in sorted(family):
        try:
            validate_model(family[model_type])
        except NotImplementedError:
            # 占位章（M2~MU）：结构已注册识别、深度校验未落地——显式留痕，不伪装通过
            pending.append(model_type)
        except SemanticSchemaError as exc:
            errors.append(f"{model_type}: {exc}")
    family_result = check_family(family, package=pkg)
    errors.extend(family_result.errors)
    return SuccessResponse(
        data={
            "package": pkg,
            "valid": not errors,
            "errors": errors,
            "validators_pending": pending,
            "family_warnings": family_result.warnings,
        },
        msg="校验完成",
    )


@MetastellaRouter.post("/{pkg}/publish", summary="发布语义包（先过校验门禁，指纹钉死 F-3）")
async def post_package_publish_controller(pkg: str):
    family = _load_family_or_404(pkg)
    try:
        record = publish_package(family, package_name=pkg, ledger_conn=_open_ledger())
    except ModelPackageAlreadyPublishedError as exc:
        raise CustomException(msg=str(exc), code=RET.CONFLICT.code) from exc
    except SemanticSchemaError as exc:
        raise CustomException(msg=str(exc), code=RET.UNPROCESSABLE_ENTITY.code) from exc
    return SuccessResponse(data=record, msg="发布成功")


@MetastellaRouter.post("/{pkg}/ddl", summary="生成 PG DDL（D1.06 确定性，过 §12 门禁）")
async def post_package_ddl_controller(pkg: str):
    family = _validated_family_or_404(pkg)
    return SuccessResponse(
        data={"package": pkg, "fingerprint": compute_package_fingerprint(family), "ddl": generate_ddl(family)},
        msg="生成成功",
    )


@MetastellaRouter.post("/{pkg}/migration", summary="生成 Alembic 迁移脚本（D11.04 生成器唯一出处，过 §12 门禁）")
async def post_package_migration_controller(pkg: str):
    family = _validated_family_or_404(pkg)
    return SuccessResponse(
        data={
            "package": pkg,
            "fingerprint": compute_package_fingerprint(family),
            "script": generate_migration(family),
        },
        msg="生成成功",
    )
