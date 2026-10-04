"""model_type 注册表与分派（§0.2 九类；最小集标注 D13.01）。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .m1_validator import validate_object_model


@dataclass(frozen=True)
class ModelTypeSpec:
    code: str
    minimal_set: bool  # D13.01：最小集六件；扩展族（ME/M7/MI/MM）为 W3 起成员
    validate: Callable[[dict], None] | None


def _not_implemented(doc: dict) -> None:  # noqa: ARG001 — 占位：M2~MU 深度校验随后续批次逐章落地
    raise NotImplementedError("该章 validator 尚未落地（M2~MU 深度校验批次补）")


REGISTRY: dict[str, ModelTypeSpec] = {
    spec.code: spec
    for spec in (
        ModelTypeSpec("OBJECT", True, validate_object_model),  # M1（工单 02）
        ModelTypeSpec("BEHAVIOR", True, _not_implemented),   # M2
        ModelTypeSpec("RULE", True, _not_implemented),       # M3
        ModelTypeSpec("ACTOR", True, _not_implemented),      # M5
        ModelTypeSpec("FLOW", True, _not_implemented),       # M6
        ModelTypeSpec("UI", True, _not_implemented),         # MU
        ModelTypeSpec("EVENT", False, _not_implemented),     # ME（扩展族）
        ModelTypeSpec("REPORT", False, _not_implemented),    # M7（扩展族）
        ModelTypeSpec("MASTER_DATA_MAPPING", False, _not_implemented),  # MM（扩展族）
    )
}

MINIMAL_SET = {code for code, spec in REGISTRY.items() if spec.minimal_set}
# §0.2 表列九类 model_type（MI 连接器属规范 §9 口径、九/十类歧义待用户裁定，暂不占码位——台账 P-13 登记）
if MINIMAL_SET != {"OBJECT", "BEHAVIOR", "RULE", "ACTOR", "FLOW", "UI"}:
    msg = f"最小集六件漂移（D13.01）: {sorted(MINIMAL_SET)}"
    raise ValueError(msg)
