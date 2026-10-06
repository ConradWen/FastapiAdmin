"""语义包发布状态机（D11.02 指纹 / D11.03 版本演进 / F-3 不可变 / §12 发布前必跑校验）。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

from .errors import (
    ModelPackageAlreadyPublishedError,
    ModelStructureError,
    SemanticSchemaError,
)
from .family_checks import check_family
from .publish_ledger import is_published, record_publish, version_conflict
from .registry import MINIMAL_SET
from .validator import validate_model


def _tag_yaml_scalars(obj: Any) -> Any:
    """把 YAML 原生标量（date/datetime）转成带类型标签的结构，保 canonical_json **单射**。

    否则 `date(2026,1,1)` 与字符串 `"2026-01-01"` 经 default=str 后同字节 → 同指纹，
    F-3 会把语义不同的包误判"已发布"（阶段审计 B-I7）。
    """
    if isinstance(obj, Mapping):
        return {k: _tag_yaml_scalars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_tag_yaml_scalars(v) for v in obj]
    if isinstance(obj, bool) or obj is None or isinstance(obj, str | int | float):
        return obj
    if isinstance(obj, datetime):
        return {"__yaml__": "datetime", "value": obj.isoformat()}
    if isinstance(obj, date):
        return {"__yaml__": "date", "value": obj.isoformat()}
    return obj


def canonical_json(obj: Any) -> str:
    """canonical_json：类型标签化 + 键排序 + 紧凑分隔 + UTF-8（D11.02 确定性序列化面）。

    不可序列化输入（混合类型键等）抛 SemanticSchemaError（error 级），不裸穿 TypeError。
    """
    try:
        return json.dumps(
            _tag_yaml_scalars(obj), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        )
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
    missing = MINIMAL_SET - set(family)
    if missing:
        raise ModelStructureError(
            f"族缺最小集成员（D13.01/§0.3 发布单元=语义包不可拆）：{sorted(missing)}"
        )
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
    schema_version = _family_version(family)
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
    # D11.06/B-I6：同 (包, 版本) 已有不同内容 → 拒（版本须单调，杜绝同版本静默覆盖历史）。
    if ledger_conn is not None:
        prior = version_conflict(ledger_conn, package_name, schema_version, fingerprint)
        if prior is not None:
            raise ModelPackageAlreadyPublishedError(
                f"语义包 {package_name} 版本 {schema_version} 已发布过不同内容（旧指纹 {prior[:12]}）"
                "——请递增 schema_version（D11.03/06）"
            )
    for (pkg, prior_fp), rec in _REGISTRY.items():
        if pkg == package_name and prior_fp != fingerprint and rec["schema_version"] == schema_version:
            raise ModelPackageAlreadyPublishedError(
                f"语义包 {package_name} 版本 {schema_version} 已发布过不同内容（旧指纹 {rec['fingerprint'][:12]}）"
                "——请递增 schema_version（D11.03/06）"
            )

    record: dict[str, Any] = {
        "package_name": package_name,
        "schema_version": schema_version,
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
