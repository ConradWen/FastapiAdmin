"""语义包发布状态机（D11.02 指纹 / D11.03 版本演进 / F-3 不可变 / §12 发布前必跑校验）。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from .errors import (
    ModelPackageAlreadyPublishedError,
    ModelStructureError,
    SemanticSchemaError,
)
from .family_checks import check_family
from .publish_ledger import is_published, record_publish
from .validator import validate_model


def canonical_json(obj: Any) -> str:
    """canonical_json：键排序+紧凑分隔+UTF-8（D11.02 指纹的确定性序列化面）。

    YAML 原生类型（date/datetime 等）经 default=str 规范化；键序比较失败等
    不可序列化输入抛 SemanticSchemaError（error 级），不裸穿 TypeError。
    """
    try:
        return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    except TypeError as exc:
        raise SemanticSchemaError(f"语义包内容不可确定性序列化（D11.02）: {exc}") from exc


def compute_package_fingerprint(family: dict[str, Any]) -> str:
    """语义包指纹 = canonical_json(全模型文件) 的 SHA-256（D11.02；manifest 非模型文件不入指纹面）。"""
    return hashlib.sha256(canonical_json(family).encode("utf-8")).hexdigest()


def publish_package(
    family: dict[str, Any],
    *,
    package_name: str,
    published_by: str = "system",
    ledger_conn: Any | None = None,
) -> dict[str, Any]:
    """草稿→发布状态机：**先过 §12 校验门禁**，再指纹钉死+快照留痕（F-3 不可变）。

    - 任何模型结构错误（ModelStructureError 等 SemanticSchemaError 子类）→ 阻断发布；
    - 占位章 validator 未落地（NotImplementedError）→ 不阻断，但发布记录显式留痕
      validators_pending（诚实边界，M2~MU 深度校验随后续批次补）；
    - schema_version 从族内容取（D11.01 族一致），不作调用方参数——杜绝台账失真。
    """
    pending: list[str] = []
    for model_type in sorted(family):
        try:
            validate_model(family[model_type])
        except NotImplementedError:
            pending.append(model_type)

    family_result = check_family(family, package=package_name, raise_on_error=True)

    versions = {doc.get("schema_version") for doc in family.values()}
    if len(versions) != 1 or not versions.pop():
        raise ModelStructureError("发布前族内 schema_version 必须一致且存在（D11.01）")

    fingerprint = compute_package_fingerprint(family)
    if ledger_conn is not None and is_published(ledger_conn, package_name, fingerprint):
        raise ModelPackageAlreadyPublishedError(
            f"语义包 {package_name} 指纹 {fingerprint} 已在台账发布（F-3 持久不可变）"
        )
    existing = _REGISTRY.get((package_name, fingerprint))
    if existing is not None:
        raise ModelPackageAlreadyPublishedError(
            f"语义包 {package_name} 指纹 {fingerprint} 已发布于 "
            f"{existing['published_at']}（F-3 内容不可变——重发布须出新 schema_version）"
        )

    record: dict[str, Any] = {
        "package_name": package_name,
        "schema_version": _family_version(family),
        "fingerprint": fingerprint,
        "status": "PUBLISHED",
        "published_at": datetime.now(UTC).isoformat(),
        "published_by": published_by,
        "model_types": sorted(family),
        "validators_pending": pending,
        "family_warnings": family_result.warnings,
        "models": dict.fromkeys(family),
    }
    _REGISTRY[(package_name, fingerprint)] = record
    if ledger_conn is not None:
        # record_publish 内部映射竞态→ModelPackageAlreadyPublishedError（F-3 单一事实源=台账）
        record_publish(ledger_conn, record)
    return record


def _family_version(family: dict[str, Any]) -> str:
    for doc in family.values():
        return str(doc["schema_version"])
    raise ModelStructureError("空族不可发布")


def _reset_registry_for_tests() -> None:
    """测试隔离钩子（仅测试调用；生产进程内注册表随进程生命周期）。"""
    _REGISTRY.clear()


_REGISTRY: dict[tuple[str, str], dict[str, Any]] = {}
