"""M3 规则模型 validator（v9 §4.3 元素表+被动调用原则）。"""

from __future__ import annotations

import re
from typing import Any

from .errors import ModelStructureError

_RULE_TYPES = {"VALIDATION", "CALCULATION", "DERIVATION", "TRANSFORMATION", "RISK"}
_RULE_ID_RE = re.compile(r"^RULE(-[A-Z0-9]+)+$")


def validate_rule_model(doc: dict[str, Any]) -> None:
    rules = doc.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ModelStructureError("M3 必须声明 rules 列表（v9 §4.3）")

    seen_ids: set[str] = set()
    for rule in rules:
        if not isinstance(rule, dict):
            raise ModelStructureError("M3 rules 只能包含映射对象")
        rid = rule.get("id")
        if not isinstance(rid, str) or not _RULE_ID_RE.match(rid):
            raise ModelStructureError(f"规则 id={rid!r} 不符 RULE-{{Domain}}-{{Seq}} 约定（v9 §4.3.1）")
        if rid in seen_ids:
            raise ModelStructureError(f"规则 id 必须唯一: {rid}")
        seen_ids.add(rid)

        _require_string(rule, "name", f"规则 {rid}")
        rule_type = rule.get("ruleType")
        if not isinstance(rule_type, str) or rule_type not in _RULE_TYPES:
            raise ModelStructureError(
                f"规则 {rid}: ruleType={rule_type!r} 必填且须为五类之一 {sorted(_RULE_TYPES)}（v9 §4.3.1）"
            )
        _require_string(rule, "expression", f"规则 {rid}")
        _require_string(rule, "version", f"规则 {rid}")

        params = rule.get("inputParams", [])
        if not isinstance(params, list):
            raise ModelStructureError(f"规则 {rid}: inputParams 必须是列表")
        for p in params:
            if not isinstance(p, dict):
                raise ModelStructureError(f"规则 {rid}: inputParams 项必须是映射")
            _require_string(p, "name", f"规则 {rid} 输入参数")
            _require_string(p, "type", f"规则 {rid} 输入参数 {p.get('name')}")

        if isinstance(rule.get("reusedBy"), list):
            for ref in rule["reusedBy"]:
                if not isinstance(ref, str):
                    raise ModelStructureError(f"规则 {rid}: reusedBy 必须是行为 id 字符串列表")

        # 被动调用原则：规则永不改状态（v9 §4.1）
        if any(key in rule for key in ("postconditions", "stateChanges", "producedEvents")):
            raise ModelStructureError(
                f"规则 {rid}: 规则只判断不改状态——出现状态变更/事件字段违反被动调用原则（v9 §4.1）"
            )


def _require_string(obj: dict[str, Any], key: str, where: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ModelStructureError(f"{where}: 字段 {key} 必须是非空字符串")
    return value
