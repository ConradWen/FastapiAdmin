"""M6 流程模型 validator（v9 §6.3 元素表+§6.5 流程约束关键项）。"""

from __future__ import annotations

from typing import Any

from .errors import ModelStructureError

_FLOW_TYPES = {"COLLABORATION", "APPROVAL"}
_STEP_TYPES = {"START", "END", "SYSTEM", "HUMAN_TASK", "APPROVAL_TASK", "BEHAVIOR_CALL", "GATEWAY"}


def validate_flow_model(doc: dict[str, Any]) -> None:
    flows = doc.get("flows")
    if not isinstance(flows, list) or not flows:
        raise ModelStructureError("M6 必须声明 flows 列表（v9 §6.3.1）")

    seen_flow_ids: set[str] = set()
    for flow in flows:
        if not isinstance(flow, dict):
            raise ModelStructureError("M6 flows 只能包含映射对象")
        fid = flow.get("id")
        if not isinstance(fid, str) or not fid.strip():
            raise ModelStructureError(f"流程 id 必须非空: {fid!r}")
        if fid in seen_flow_ids:
            raise ModelStructureError(f"流程 id 必须唯一: {fid}")
        seen_flow_ids.add(fid)
        _require_string(flow, "name", f"流程 {fid}")

        flow_type = flow.get("flowType")
        if flow_type not in _FLOW_TYPES:
            raise ModelStructureError(f"流程 {fid}: flowType={flow_type!r} 须为 COLLABORATION/APPROVAL")

        steps = flow.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ModelStructureError(f"流程 {fid}: steps 必须是非空列表（v9 §6.3.1）")
        step_ids: set[str] = set()
        for step in steps:
            if not isinstance(step, dict):
                raise ModelStructureError(f"流程 {fid}: steps 项必须是映射")
            sid = step.get("id")
            if not isinstance(sid, str) or not sid.strip():
                raise ModelStructureError(f"流程 {fid}: 活动 id 必须非空")
            if sid in step_ids:
                raise ModelStructureError(f"流程 {fid}: 活动 id 必须唯一: {sid}")
            step_ids.add(sid)
            _require_string(step, "name", f"流程 {fid} 活动 {sid}")
            stype = step.get("stepType")
            if stype not in _STEP_TYPES:
                raise ModelStructureError(
                    f"流程 {fid} 活动 {sid}: stepType={stype!r} 须为 {sorted(_STEP_TYPES)}"
                )

        transitions = flow.get("transitions", [])
        if not isinstance(transitions, list):
            raise ModelStructureError(f"流程 {fid}: transitions 必须是列表")
        for t in transitions:
            if not isinstance(t, dict):
                raise ModelStructureError(f"流程 {fid}: transitions 项必须是映射")
            for key in ("from", "to"):
                endpoint = t.get(key)
                if endpoint not in step_ids:
                    raise ModelStructureError(
                        f"流程 {fid}: 转移 {key}={endpoint!r} 指向不存在活动（§6.5-2 可达性）"
                    )

        approval_ids = {s.get("id") for s in steps if isinstance(s, dict) and s.get("stepType") == "APPROVAL_TASK"}
        if flow_type == "APPROVAL" and not approval_ids:
            raise ModelStructureError(f"流程 {fid}: APPROVAL 流程必须含 APPROVAL_TASK 活动（D6.05）")


def _require_string(obj: dict[str, Any], key: str, where: str) -> None:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ModelStructureError(f"{where}: 字段 {key} 必须是非空字符串")
