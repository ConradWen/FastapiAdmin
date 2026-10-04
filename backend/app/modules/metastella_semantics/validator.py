"""model_type 分派校验入口（§12 validator 跨模型一致性硬门禁的当前落点）。"""

from __future__ import annotations

from typing import Any

from .errors import UnknownModelTypeError
from .registry import REGISTRY
from .schema_version import extract_schema_version


def validate_model(doc: dict[str, Any]) -> None:
    """执行 D11.01 前置版本校验，并按注册表分派对应模型 validator。"""
    extract_schema_version(doc, "validate_model")
    model_type = doc.get("model_type")
    if model_type not in REGISTRY:
        raise UnknownModelTypeError(f"model_type={model_type!r} 不在九类注册表（§0.2）")
    spec = REGISTRY[model_type]
    if spec.validate is None:
        return None
    return spec.validate(doc)
