"""M5 主体模型 validator（v9 §5.3 关键约束；本项目口径：actors 即角色位）。

canonical 四层（Actor/Role/Permission/Group）完整化挂后续批；本批钉最小可发布面：
id 唯一、name 必填、permissions[].code 形态（格式规则由族检 D5.02 统一守）。
"""

from __future__ import annotations

from typing import Any

from .errors import ModelStructureError


def validate_actor_model(doc: dict[str, Any]) -> None:
    actors = doc.get("actors")
    if not isinstance(actors, list) or not actors:
        raise ModelStructureError("M5 必须声明 actors（角色）列表（v9 §5.3）")

    seen: set[str] = set()
    for actor in actors:
        if not isinstance(actor, dict):
            raise ModelStructureError("M5 actors 只能包含映射对象")
        aid = actor.get("id")
        if not isinstance(aid, str) or not aid.strip():
            raise ModelStructureError(f"主体 id 必须非空字符串: {aid!r}")
        if aid in seen:
            raise ModelStructureError(f"主体 id 必须唯一: {aid}")
        seen.add(aid)

        name = actor.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ModelStructureError(f"主体 {aid}: name 必须是非空字符串")

        permissions = actor.get("permissions", [])
        if not isinstance(permissions, list):
            raise ModelStructureError(f"主体 {aid}: permissions 必须是列表")
        for perm in permissions:
            if not isinstance(perm, dict) or not isinstance(perm.get("code"), str):
                raise ModelStructureError(
                    f"主体 {aid}: permissions 项必须是含 code 字符串的映射（v9 §5.3.3）"
                )

        inherits = actor.get("inherits", [])
        if not isinstance(inherits, list) or not all(isinstance(x, str) for x in inherits):
            raise ModelStructureError(f"主体 {aid}: inherits 必须是角色 id 字符串列表（D5.04）")
