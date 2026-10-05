"""M2 行为模型 validator（v9 §3.2/§3.4 关键约束 + D2.01/02/04）。"""

from __future__ import annotations

import re
from typing import Any

from .errors import ModelStructureError

_BEHAVIOR_TYPES = {"COMMAND", "QUERY"}
_TRIGGER_TYPES = {"USER_ACTION", "SYSTEM"}
_BEHAVIOR_ID_RE = re.compile(r"^[A-Z][A-Za-z0-9]*_[a-z][A-Za-z0-9]*$")  # {Entity}_{action}（D2.02 前提）


def validate_behavior_model(doc: dict[str, Any]) -> None:
    behaviors = doc.get("behaviors")
    if not isinstance(behaviors, list) or not behaviors:
        raise ModelStructureError("M2 必须声明 behaviors 列表（v9 §3.2）")

    by_id: dict[str, dict[str, Any]] = {}
    for b in behaviors:
        if not isinstance(b, dict):
            raise ModelStructureError("M2 behaviors 只能包含映射对象")
        bid = b.get("id")
        if not isinstance(bid, str) or not _BEHAVIOR_ID_RE.match(bid):
            raise ModelStructureError(
                f"行为 id={bid!r} 不符 {{Entity}}_{{action}} 约定（D2.02：endpoint 确定性推导前提）"
            )
        if bid in by_id:
            raise ModelStructureError(f"行为 id 必须唯一: {bid}")
        by_id[bid] = b
        _require_string(b, "name", f"行为 {bid}")

        behavior_type = _require_string(b, "behaviorType", f"行为 {bid}")
        if behavior_type not in _BEHAVIOR_TYPES:
            raise ModelStructureError(f"行为 {bid}: behaviorType={behavior_type!r} 须为 COMMAND/QUERY")
        trigger = _require_string(b, "triggerType", f"行为 {bid}")
        if trigger not in _TRIGGER_TYPES:
            raise ModelStructureError(f"行为 {bid}: triggerType={trigger!r} 须为 USER_ACTION/SYSTEM")

        pre = b.get("preconditions", [])
        post = b.get("postconditions", [])
        sync = b.get("syncTriggers", [])
        for name, value in (("preconditions", pre), ("postconditions", post), ("syncTriggers", sync)):
            if not isinstance(value, list):
                raise ModelStructureError(f"行为 {bid}: {name} 必须是列表")

        if behavior_type == "QUERY":
            if post or sync:
                raise ModelStructureError(f"行为 {bid}: QUERY 只读——postconditions/syncTriggers 必须为空（v9 §3.2）")
            if b.get("idempotencyKey") or b.get("appliedRules"):
                raise ModelStructureError(f"行为 {bid}: QUERY 不得挂幂等键/规则改写面（D2.01/§3.2）")
        else:
            if "idempotencyKey" in b and not isinstance(b["idempotencyKey"], str):
                raise ModelStructureError(f"行为 {bid}: idempotencyKey 须为表达式字符串（D2.01）")

        for ref in b.get("appliedRules", []) or []:
            if not isinstance(ref, str):
                raise ModelStructureError(f"行为 {bid}: appliedRules 必须是规则 id 字符串列表")

    for b in behaviors:
        for trigger in b.get("syncTriggers", []) or []:
            if not isinstance(trigger, dict):
                raise ModelStructureError(f"行为 {b['id']}: syncTriggers 项必须是映射")
            ref = trigger.get("behaviorRef")
            if not ref:
                raise ModelStructureError(f"行为 {b['id']}: syncTriggers.behaviorRef 必填（v9 §3.2.2）")
            if ref not in by_id:
                raise ModelStructureError(f"行为 {b['id']}: syncTriggers 指向不存在行为 {ref}（族内检查兜底）")
            if b.get("ownerEntity") == by_id[ref].get("ownerEntity"):
                raise ModelStructureError(
                    f"行为 {b['id']} 与 {ref} 同聚合（{b.get('ownerEntity')}）——syncTriggers 必须跨聚合（v9 §3.2.2-4）"
                )
            if "ruleRef" in trigger and not isinstance(trigger["ruleRef"], str):
                raise ModelStructureError(f"行为 {b['id']}: syncTriggers.ruleRef 须为字符串")


def _require_string(obj: dict[str, Any], key: str, where: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ModelStructureError(f"{where}: 字段 {key} 必须是非空字符串")
    return value
