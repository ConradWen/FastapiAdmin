"""metastella 语义引擎 API 骨架（m2-minset 工单 05b）。

四端点消费 backend/semantic_packages/ 下的语义包；发布判重**单一事实源在引擎层**
（publish_package 的注册表——控制器不再自判，杜绝双源）。PG 持久化台账挂 M2 中期。
"""

from pathlib import Path

import yaml
from fastapi import APIRouter

from app.common.enums import RET
from app.common.response import SuccessResponse
from app.core.exceptions import CustomException
from app.modules.metastella_semantics import (
    ModelPackageAlreadyPublishedError,
    compute_package_fingerprint,
    generate_ddl,
    load_model_family,
    publish_package,
    validate_model,
)
from app.modules.metastella_semantics.errors import SemanticSchemaError

MetastellaRouter = APIRouter(prefix="/packages", tags=["MetaStella 语义引擎"])

# app/plugin/module_metastella/semantics/controller.py → parents[4] = backend/
# semantic_packages/ 与 app/ 平级（backend/semantic_packages/library_smoke/...）
PACKAGES_ROOT = Path(__file__).parents[4] / "semantic_packages"
_MANIFEST = "manifest.yaml"


def _load_family_or_404(pkg: str) -> dict:
    pkg_dir = PACKAGES_ROOT / pkg
    manifest = pkg_dir / _MANIFEST
    if not manifest.is_file():
        raise CustomException(msg=f"语义包 {pkg} 不存在", code=RET.NOT_FOUND.code)
    try:
        return load_model_family(pkg_dir, manifest_name=_MANIFEST)
    except (SemanticSchemaError, FileNotFoundError, yaml.YAMLError) as exc:
        raise CustomException(msg=str(exc), code=RET.UNPROCESSABLE_ENTITY.code) from exc


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
    return SuccessResponse(
        data={"package": pkg, "valid": not errors, "errors": errors, "validators_pending": pending},
        msg="校验完成",
    )


@MetastellaRouter.post("/{pkg}/publish", summary="发布语义包（先过校验门禁，指纹钉死 F-3）")
async def post_package_publish_controller(pkg: str):
    family = _load_family_or_404(pkg)
    try:
        record = publish_package(family, package_name=pkg)
    except ModelPackageAlreadyPublishedError as exc:
        raise CustomException(msg=str(exc), code=RET.CONFLICT.code) from exc
    except SemanticSchemaError as exc:
        raise CustomException(msg=str(exc), code=RET.UNPROCESSABLE_ENTITY.code) from exc
    return SuccessResponse(data=record, msg="发布成功")


@MetastellaRouter.post("/{pkg}/ddl", summary="生成 PG DDL（D1.06 确定性）")
async def post_package_ddl_controller(pkg: str):
    family = _load_family_or_404(pkg)
    return SuccessResponse(
        data={"package": pkg, "fingerprint": compute_package_fingerprint(family), "ddl": generate_ddl(family)},
        msg="生成成功",
    )
