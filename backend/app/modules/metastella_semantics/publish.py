"""语义包发布状态机（D11.02 指纹 / D11.03 版本演进 / F-3 内容不可变）。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from .errors import SemanticPackageError


class ModelPackageAlreadyPublishedError(SemanticPackageError):
    """同指纹语义包已发布（F-3 内容不可变——重发布须出新版本）。"""


def canonical_json(obj: Any) -> str:
    """canonical_json：键排序+紧凑分隔符+UTF-8（D11.02 指纹的确定性序列化面）。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def compute_package_fingerprint(family: dict[str, Any]) -> str:
    """语义包指纹 = canonical_json(全模型文件) 的 SHA-256（D11.02）。

    family 形如 {model_type: doc}；按 model_type 键排序后整体序列化——
    键序/插入序无关，同内容必同指纹。
    """
    return hashlib.sha256(canonical_json(family).encode("utf-8")).hexdigest()


def publish_package(
    family: dict[str, Any],
    *,
    package_name: str,
    schema_version: str,
    published_by: str = "system",
) -> dict[str, Any]:
    """草稿→发布状态机：指纹钉死+快照留痕；同指纹重复发布拒绝（F-3）。

    返回发布记录（JSON 可序列化，可落 PG 发布台账）。
    """
    fingerprint = compute_package_fingerprint(family)
    existing = _REGISTRY.get((package_name, fingerprint))
    if existing is not None:
        raise ModelPackageAlreadyPublishedError(
            f"语义包 {package_name} 指纹 {fingerprint} 已发布于 "
            f"{existing['published_at']}（F-3 内容不可变——重发布须出新 schema_version）"
        )

    record: dict[str, Any] = {
        "package_name": package_name,
        "schema_version": schema_version,
        "fingerprint": fingerprint,
        "status": "PUBLISHED",
        "published_at": datetime.now(UTC).isoformat(),
        "published_by": published_by,
        "model_types": sorted(family),
        "models": dict.fromkeys(family),  # 快照占位：后续工单挂生成链产物
    }
    _REGISTRY[(package_name, fingerprint)] = record
    return record


def _reset_registry_for_tests() -> None:
    """测试隔离钩子（仅测试调用；生产进程内注册表随进程生命周期）。"""
    _REGISTRY.clear()


_REGISTRY: dict[tuple[str, str], dict[str, Any]] = {}
