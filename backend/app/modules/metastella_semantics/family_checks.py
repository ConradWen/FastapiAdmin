"""族级跨模型机检（§12.1 清单中最小集相关项；error 阻断发布，warning 留痕）。

§12.2 防御分级：引用断链/权限越界/角色环/密钥明文/审批单边=error；表达式双定义=warning。
纯确定性 Python（AI 不进编译核心）。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .errors import ModelStructureError
from .m2_validator import endpoint_from_behavior_id

_PACKAGE_RE = re.compile(r"^PERM-[A-Z][A-Z0-9]*(-[A-Z0-9]+)+$")
_HUMAN_TASK_TYPES = {"HUMAN_TASK", "APPROVAL_TASK"}
# 密钥零落盘：键值对形态 + 已知令牌前缀（安全架构 §1；命中即 error）
_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?key|private[_-]?key)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*(?!<|\{\{|占位|placeholder)\S+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}"),
    re.compile(r"\b(ghp|gho|xoxb|xoxp)-[A-Za-z0-9]{16,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{6,}"),  # JWT
)
# 敏感键名（值为字面量即疑密钥；占位符形态豁免）
_SENSITIVE_KEY_RE = re.compile(r"(?i)^(api[_-]?key|secret[_-]?key|access[_-]?key|private[_-]?key|password|passwd|pwd|token)$")
_PLACEHOLDER_RE = re.compile(r"(^\s*(<[^>]*>|\{\{.*\}\}|\$\{[^}]*\}|待填|占位.*|placeholder.*|your[_-].*)\s*$)", re.I)


def _looks_like_secret_value(value: str) -> bool:
    return bool(value.strip()) and not _PLACEHOLDER_RE.match(value) and len(value.strip()) >= 8


@dataclass
class FamilyCheckResult:
    package: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def check_family(
    family: Mapping[str, Any],
    *,
    package: str = "unknown",
    raise_on_error: bool = False,
) -> FamilyCheckResult:
    """跑族级机检；返回分级结果。raise_on_error=True 时首个 error 即抛 ModelStructureError。"""
    result = FamilyCheckResult(package=package)
    _check_references(family, result)
    _check_api_surface(family, result)
    _check_databinding(family, result)
    _check_permissions(family, result)
    _check_roles(family, result)
    _check_flow(family, result)
    _check_expressions(family, result)
    _check_secrets(family, result)

    if raise_on_error and result.errors:
        raise ModelStructureError(result.errors[0])
    return result


# ---- 引用完整性（v9 §1.4 / F-2） ----


def _check_references(family: Mapping[str, Any], result: FamilyCheckResult) -> None:
    m1_aliases = {
        agg.get("alias")
        for agg in family.get("OBJECT", {}).get("aggregates", [])
        if isinstance(agg, dict)
    }
    behaviors = [b for b in family.get("BEHAVIOR", {}).get("behaviors", []) if isinstance(b, dict)]
    behavior_ids = {b.get("id") for b in behaviors}
    rule_ids = {r.get("id") for r in family.get("RULE", {}).get("rules", []) if isinstance(r, dict)}
    actor_codes = _iter_permission_codes(family)

    for b in behaviors:
        owner = b.get("ownerEntity")
        if owner and m1_aliases and owner not in m1_aliases:
            result.errors.append(f"引用完整性：行为 {b.get('id')} ownerEntity={owner} 不存在于 M1 聚合（§12）")
        for ref in b.get("appliedRules", []) or []:
            if ref not in rule_ids:
                result.errors.append(f"引用完整性：行为 {b.get('id')} appliedRules 引用不存在规则 {ref}（§12）")
        for trigger in b.get("syncTriggers", []) or []:
            if isinstance(trigger, dict) and trigger.get("ruleRef") and trigger["ruleRef"] not in rule_ids:
                result.errors.append(
                    f"引用完整性：行为 {b.get('id')} syncTriggers.ruleRef={trigger['ruleRef']} 不存在（v9 §3.2.2-2）"
                )
        for perm in b.get("requiredPermissions", []) or []:
            code = perm.get("code") if isinstance(perm, dict) else perm
            if not code:
                result.errors.append(f"权限位：行为 {b.get('id')} requiredPermissions 项缺 code（D5.02）")

    for rule in family.get("RULE", {}).get("rules", []):
        if not isinstance(rule, dict):
            continue
        for ref in rule.get("reusedBy", []) or []:
            if ref not in behavior_ids:
                result.errors.append(
                    f"引用完整性：规则 {rule.get('id')} reusedBy 引用不存在行为 {ref}（§12）"
                )

    action_point_refs: set[Any] = set()
    for screen in family.get("UI", {}).get("screens", []):
        if not isinstance(screen, dict):
            continue
        screen_ids = {s.get("id") for s in family.get("UI", {}).get("screens", []) if isinstance(s, dict)}
        for menu in screen.get("menus", []) or []:
            if not isinstance(menu, dict):
                continue
            for sub in menu.get("subMenus", []) or []:
                if isinstance(sub, dict) and sub.get("screenRef") not in screen_ids:
                    result.errors.append(
                        f"引用完整性：菜单 {menu.get('menuId')} screenRef={sub.get('screenRef')} 无对应屏幕（§12）"
                    )
        for ap in screen.get("actionPoints", []) or []:
            if not isinstance(ap, dict):
                continue
            action_point_refs.add(ap.get("behaviorRef"))
            if ap.get("behaviorRef") not in behavior_ids:
                result.errors.append(
                    f"引用完整性：操作点 {ap.get('id')} behaviorRef={ap.get('behaviorRef')} 不存在（§12）"
                )
            for pref in ap.get("permissionRef", []) or []:
                code = pref.get("code") if isinstance(pref, dict) else pref
                if code and code not in actor_codes:
                    result.errors.append(
                        f"引用完整性：操作点 {ap.get('id')} permissionRef={code} 不存在于 M5 权限集（v9 §8.2.5）"
                    )

    # v9 §3.4-1 可追溯门禁：USER_ACTION 行为必须有界面入口（禁孤儿行为）
    for b in behaviors:
        if b.get("triggerType") == "USER_ACTION" and b.get("id") not in action_point_refs:
            result.errors.append(
                f"可追溯门禁：行为 {b.get('id')}（USER_ACTION）未被任何 MU 操作点引用——孤儿行为（v9 §3.4）"
            )

    for flow in family.get("FLOW", {}).get("flows", []):
        if not isinstance(flow, dict):
            continue
        for step in flow.get("steps", []) or []:
            if not isinstance(step, dict):
                continue
            ref = step.get("behaviorRef")
            if ref and ref not in behavior_ids:
                result.errors.append(f"引用完整性：流程 {flow.get('id')} 活动 {step.get('id')} behaviorRef={ref} 不存在（§12）")


# ---- 行为-API 面（D2.02：endpoint 由 behavior id 钉死推导，族内唯一） ----


def _check_api_surface(family: Mapping[str, Any], result: FamilyCheckResult) -> None:
    seen: dict[str, str] = {}
    for b in family.get("BEHAVIOR", {}).get("behaviors", []):
        if not isinstance(b, dict) or not isinstance(b.get("id"), str):
            continue
        ep = endpoint_from_behavior_id(b["id"])
        if ep in seen:
            result.errors.append(
                f"行为-API 面（D2.02）：行为 {b['id']} 与 {seen[ep]} 推导出同一 endpoint {ep}——API 面撞车"
            )
        seen[ep] = b["id"]


# ---- 权限位（D2.05/D5.02） ----


def _iter_permission_codes(family: Mapping[str, Any]) -> set[str]:
    codes: set[str] = set()
    for actor in family.get("ACTOR", {}).get("actors", []):
        if not isinstance(actor, dict):
            continue
        for perm in actor.get("permissions", []) or []:
            if isinstance(perm, dict) and perm.get("code"):
                codes.add(str(perm["code"]))
    return codes


def _check_permissions(family: Mapping[str, Any], result: FamilyCheckResult) -> None:
    actor_codes = _iter_permission_codes(family)
    for actor in family.get("ACTOR", {}).get("actors", []):
        if not isinstance(actor, dict):
            continue
        for perm in actor.get("permissions", []) or []:
            code = perm.get("code") if isinstance(perm, dict) else perm
            if code and not _PACKAGE_RE.match(str(code)):
                result.errors.append(
                    f"权限位格式：PERM 码 {code} 不符 PERM-{{Domain}}-{{Action}}（D5.02）"
                )
    for b in family.get("BEHAVIOR", {}).get("behaviors", []):
        if not isinstance(b, dict):
            continue
        for perm in b.get("requiredPermissions", []) or []:
            code = perm.get("code") if isinstance(perm, dict) else perm
            if not code:
                continue
            if not _PACKAGE_RE.match(str(code)):
                result.errors.append(
                    f"权限位格式：行为 {b.get('id')} 权限 {code} 不符 PERM-{{Domain}}-{{Action}}（D5.02）"
                )
            elif actor_codes and code not in actor_codes:
                result.errors.append(
                    f"权限位：行为 {b.get('id')} 要求 {code}，M5 权限集合中不存在（D2.05）"
                )


# ---- 角色引用与继承（D5.04；M6 强制角色约束） ----


def _check_roles(family: Mapping[str, Any], result: FamilyCheckResult) -> None:
    actor_ids = {a.get("id") for a in family.get("ACTOR", {}).get("actors", []) if isinstance(a, dict)}

    edges: dict[str, list[str]] = {}
    for actor in family.get("ACTOR", {}).get("actors", []):
        if isinstance(actor, dict):
            edges[str(actor.get("id"))] = [str(x) for x in actor.get("inherits", []) or []]

    for node in edges:
        for ref in edges[node]:
            if actor_ids and ref not in actor_ids:
                result.errors.append(f"角色引用：{node} 继承的 {ref} 不存在（D5.04）")

    # 环检测（三色 DFS）
    WHITE, GRAY, BLACK = 0, 1, 2
    color = dict.fromkeys(edges, WHITE)

    def visit(nid: str, depth: int, path: list[str]) -> None:
        state = color.get(nid, BLACK)
        if state == GRAY:
            result.errors.append(f"角色继承环：{' -> '.join([*path, nid])}（D5.04）")
            return
        if state == BLACK:
            return
        color[nid] = GRAY
        if depth > 3:
            result.errors.append(f"角色继承链深度超过 3：{' -> '.join([*path, nid])}（D5.04）")
        for parent in edges.get(nid, []):
            visit(parent, depth + 1, [*path, nid])
        color[nid] = BLACK

    for node in edges:
        if color[node] == WHITE:
            visit(node, 1, [])

    for flow in family.get("FLOW", {}).get("flows", []):
        if not isinstance(flow, dict):
            continue
        for step in flow.get("steps", []) or []:
            if not isinstance(step, dict):
                continue
            if step.get("stepType") not in _HUMAN_TASK_TYPES:
                continue
            if step.get("actorId"):
                result.errors.append(
                    f"角色引用：人工任务 {step.get('id')} 使用 actorId/自由文本参与人（v9 §6 强制经 roleRef）"
                )
            role = step.get("roleRef")
            if not role:
                result.errors.append(
                    f"角色引用：人工任务 {step.get('id')} 缺 roleRef——参与人只能引用 M5 角色（v9 §6）"
                )
            elif actor_ids and role not in actor_ids:
                result.errors.append(
                    f"角色引用：流程活动 {step.get('id')} roleRef={role} 不存在于 M5（§12）"
                )


# ---- 流程结构（D6.05 审批双出边） ----


def _check_flow(family: Mapping[str, Any], result: FamilyCheckResult) -> None:
    for flow in family.get("FLOW", {}).get("flows", []):
        if not isinstance(flow, dict):
            continue
        steps = {s.get("id"): s for s in flow.get("steps", []) or [] if isinstance(s, dict)}
        transitions = [t for t in flow.get("transitions", []) or [] if isinstance(t, dict)]

        step_ids = set(steps)
        for t in transitions:
            for key in ("from", "to"):
                if t.get(key) not in step_ids:
                    result.errors.append(
                        f"引用完整性：流程 {flow.get('id')} 转移 {t.get(key)}={t.get(key)} 无对应活动（§12）"
                    )

        for sid, step in steps.items():
            if step.get("stepType") != "APPROVAL_TASK":
                continue
            outcomes = {str(t.get("outcome", "")).lower() for t in transitions if t.get("from") == sid}
            missing = {"approve", "reject"} - outcomes
            if missing:
                result.errors.append(
                    f"审批双出边（D6.05）：APPROVAL_TASK {sid} 缺 {'/'.join(sorted(missing))} 出边"
                )


# ---- dataBinding 引用可解析（§8.7-1）+ io/required 对齐（D8.04） ----


def _check_databinding(family: Mapping[str, Any], result: FamilyCheckResult) -> None:
    attrs: dict[str, dict[str, bool]] = {}  # alias -> {attr: required}
    for agg in family.get("OBJECT", {}).get("aggregates", []):
        if not isinstance(agg, dict):
            continue
        attrs[str(agg.get("alias"))] = {
            str(a.get("name")): bool(a.get("required")) for a in agg.get("attributes", []) if isinstance(a, dict)
        }

    bound_required: set[tuple[str, str]] = set()
    for screen in family.get("UI", {}).get("screens", []):
        if not isinstance(screen, dict):
            continue
        for element in screen.get("elements", []) or []:
            if not isinstance(element, dict):
                continue
            binding = element.get("dataBinding")
            if not isinstance(binding, str) or not binding:
                continue
            alias, _, attr = binding.partition(".")
            eid = f"屏幕 {screen.get('id')} 元素 {element.get('id')}"
            if alias not in attrs:
                result.errors.append(f"引用完整性：{eid} dataBinding={binding!r} 聚合 {alias} 不存在（§8.7-1）")
                continue
            if attr not in attrs[alias]:
                result.errors.append(f"引用完整性：{eid} dataBinding={binding!r} 属性不存在（§8.7-1）")
                continue
            m1_required = attrs[alias][attr]
            elem_required = element.get("required") is True
            io = element.get("io")
            if elem_required and not m1_required:
                result.errors.append(
                    f"io/required 对齐（D8.04）：{eid} 标 required 但 M1 属性 {binding} 非必填"
                )
            if m1_required and io in {"I", "I_O"} and not elem_required:
                result.errors.append(
                    f"io/required 对齐（D8.04）：M1 属性 {binding} 必填但输入元素未标 required"
                )
            if m1_required and io in {"I", "I_O"}:
                bound_required.add((alias, attr))

    for alias, attr_map in attrs.items():
        for attr, required in attr_map.items():
            if required and (alias, attr) not in bound_required:
                result.warnings.append(
                    f"dataBinding 缺口（§8.7-1）：M1 必填属性 {alias}.{attr} 未被任何输入元素绑定"
                )


# ---- 表达式语体一致性（D3.01/D6.03，warning 级） ----


def _check_expressions(family: Mapping[str, Any], result: FamilyCheckResult) -> None:
    sites: dict[str, list[str]] = {}

    def collect(expr: object, loc: str) -> None:
        if isinstance(expr, str) and expr.strip():
            sites.setdefault(expr.strip(), []).append(loc)

    for b in family.get("BEHAVIOR", {}).get("behaviors", []):
        if not isinstance(b, dict):
            continue
        for cond in b.get("preconditions", []) or []:
            if isinstance(cond, dict):
                collect(cond.get("expression"), f"BEHAVIOR/{b.get('id')}")
    for flow in family.get("FLOW", {}).get("flows", []):
        if not isinstance(flow, dict):
            continue
        for t in flow.get("transitions", []) or []:
            if isinstance(t, dict):
                collect(t.get("conditionExpression"), f"FLOW/{flow.get('id')}")
        for step in flow.get("steps", []) or []:
            if isinstance(step, dict):
                collect(step.get("conditionExpression"), f"FLOW/{flow.get('id')}")

    for expr, locs in sites.items():
        if len(set(locs)) > 1:
            result.warnings.append(
                f"表达式语体一致性（D3.01）：同一表达式 {expr!r} 出现在 {sorted(set(locs))}——"
                "疑似双定义，建议抽 M3 规则"
            )


# ---- 密钥零落盘（安全架构 §1） ----


def _check_secrets(family: Mapping[str, Any], result: FamilyCheckResult) -> None:
    seen: set[str] = set()

    def flag(path: str, why: str) -> None:
        if path not in seen:
            seen.add(path)
            result.errors.append(f"密钥零落盘：{path} {why}（安全架构 §1——镜像/模型内禁密钥）")

    def scan_value(value: str, path: str) -> None:
        for pattern in _SECRET_PATTERNS:
            if pattern.search(value):
                flag(path, "出现疑似密钥字面值")

    def walk(node: object, path: str) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                kpath = f"{path}.{key}"
                if isinstance(value, str):
                    scan_value(value, kpath)
                    if _SENSITIVE_KEY_RE.match(str(key)) and _looks_like_secret_value(value):
                        flag(kpath, f"敏感键 {key} 携带字面值")
                else:
                    walk(value, kpath)
        elif isinstance(node, list | tuple):
            for i, item in enumerate(node):
                if isinstance(item, str):
                    scan_value(item, f"{path}[{i}]")
                else:
                    walk(item, f"{path}[{i}]")

    walk(dict(family), "$")
