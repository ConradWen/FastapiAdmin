"""schema_version 前置校验（D11.01/D11.03：semver 三段；发布单元=语义包，版本=包级）。"""

from __future__ import annotations

import re

from .errors import (
    BadSchemaVersionError,
    MissingSchemaVersionError,
    ModelFamilyInconsistencyError,
)

_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def extract_schema_version(doc: dict, source: str) -> str:
    """取 schema_version 首字段；缺失/格式错即防御级异常（error 级阻断）。"""
    if not isinstance(doc, dict):
        raise MissingSchemaVersionError(f"{source}: 元文件不是映射（无法承载 schema_version）")
    version = doc.get("schema_version")
    if version is None:
        raise MissingSchemaVersionError(f"{source}: 缺 schema_version 首字段（D11.01）")
    if not isinstance(version, str) or not _SEMVER.match(version):
        raise BadSchemaVersionError(f"{source}: schema_version={version!r} 非 <major>.<minor>.<patch> 格式（D11.01）")
    return version


def check_family_consistency(versions: dict[str, str]) -> None:
    """D11.01：族内所有文件 schema_version 必须相同（发布单元=语义包）。"""
    distinct = set(versions.values())
    if len(distinct) > 1:
        detail = ", ".join(f"{name}={ver}" for name, ver in versions.items())
        raise ModelFamilyInconsistencyError(f"语义包族 schema_version 不一致（发布单元=包级）: {detail}")
