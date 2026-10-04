"""YAML 语义包族 loader（§0.3/§11；零 LLM——确定性解析面）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .errors import ModelStructureError, UnknownModelTypeError
from .registry import REGISTRY
from .schema_version import check_family_consistency, extract_schema_version
from .validator import validate_model


def _load_yaml(path: Path) -> dict:
    """读取单个 YAML 元文件 → dict（§0.3：YAML 族一律元文件）。"""
    with path.open(encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    if not isinstance(doc, dict):
        raise ModelStructureError(f"{path.name}: 非映射结构的 YAML 元文件")
    return doc


def load_model_file(path: str | Path, *, validate: bool = False) -> tuple[dict, str, str]:
    """单文件装载：返回 (doc, model_type, schema_version)，并做前置校验。

    validate=True 时按注册表分派模型 validator（发布前硬门禁；默认关闭保持纯装载语义）。
    """
    p = Path(path)
    doc = _load_yaml(p)
    version = extract_schema_version(doc, p.name)
    model_type = doc.get("model_type")
    if model_type not in REGISTRY:
        raise UnknownModelTypeError(f"{p.name}: model_type={model_type!r} 不在九类注册表（§0.2）")
    if validate:
        validate_model(doc)
    return doc, model_type, version


def load_model_family(
    directory: str | Path,
    manifest_name: str = "manifest.json",
    *,
    validate: bool = False,
) -> dict[str, Any]:
    """装载语义包族：manifest.json 声明全部模型文件（§0.3 发布单元=语义包不可拆）→
    返回 {model_type: doc}；校验族版本一致（D11.01）。
    """
    d = Path(directory)
    manifest_path = d / manifest_name
    manifest = _load_yaml(manifest_path)  # manifest 本身是 JSON-compatible YAML
    manifest_version = extract_schema_version(manifest, manifest_path.name)  # §0.3：每文件首字段
    files = manifest.get("model_files")
    if not isinstance(files, list) or not files:
        raise ModelStructureError(f"{manifest_path.name}: 缺 model_files 声明（族=manifest 全量不可拆）")

    family: dict[str, Any] = {}
    versions: dict[str, str] = {manifest_name: manifest_version}
    for fname in files:
        doc, model_type, version = load_model_file(d / str(fname), validate=validate)
        if model_type in family:
            raise ModelStructureError(f"重复 model_type={model_type}（族内应一型一件）")
        family[model_type] = doc
        versions[str(fname)] = version
    check_family_consistency(versions)
    return family
