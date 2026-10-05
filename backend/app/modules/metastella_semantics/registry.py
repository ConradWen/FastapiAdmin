"""model_type 注册表与分派（§0.2 九类；最小集标注 D13.01）。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .m1_validator import validate_object_model
from .m2_validator import validate_behavior_model
from .m3_validator import validate_rule_model
from .m5_validator import validate_actor_model
from .m6_validator import validate_flow_model
from .mu_validator import validate_ui_model


@dataclass(frozen=True)
class ModelTypeSpec:
    code: str
    minimal_set: bool  # D13.01：最小集六件；扩展族（ME/M7/MI/MM）为 W3 起成员
    validate: Callable[[dict], None] | None


def _not_implemented(doc: dict) -> None:  # noqa: ARG001 — 占位：扩展族（W3）逐章落地
    raise NotImplementedError("扩展族章节 validator 未落地（W3 批次）")


REGISTRY: dict[str, ModelTypeSpec] = {
    spec.code: spec
    for spec in (
        ModelTypeSpec("OBJECT", True, validate_object_model),  # M1
        ModelTypeSpec("BEHAVIOR", True, validate_behavior_model),  # M2（工单 08b）
        ModelTypeSpec("RULE", True, validate_rule_model),  # M3
        ModelTypeSpec("ACTOR", True, validate_actor_model),  # M5
        ModelTypeSpec("FLOW", True, validate_flow_model),  # M6
        ModelTypeSpec("UI", True, validate_ui_model),  # MU
        ModelTypeSpec("EVENT", False, _not_implemented),  # ME（扩展族）
        ModelTypeSpec("REPORT", False, _not_implemented),  # M7（扩展族）
        ModelTypeSpec("MASTER_DATA_MAPPING", False, _not_implemented),  # MM（扩展族）
    )
}

MINIMAL_SET = {code for code, spec in REGISTRY.items() if spec.minimal_set}
# §0.2 表列九类 model_type（MI 连接器属规范 §9 口径、九/十类歧义待用户裁定，暂不占码位——台账 P-13 登记）
if MINIMAL_SET != {"OBJECT", "BEHAVIOR", "RULE", "ACTOR", "FLOW", "UI"}:
    msg = f"最小集六件漂移（D13.01）: {sorted(MINIMAL_SET)}"
    raise ValueError(msg)
