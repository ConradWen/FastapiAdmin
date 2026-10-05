"""MU 界面模型 validator（v9 §8.2 元素表关键项 + D8.04 elementId 对齐）。

本批口径（08c 已扩）：屏幕/元素/操作点结构面 + actionPoint.elementId 必须存在于 elements
（D8.04）；layout ASCII 方括号 token 必须存在于 elements（翻页/数字豁免，§8.7-8）；
io/required 与 M1 属性逐项联查=后续批（依赖 canonical dataBinding）。
"""

from __future__ import annotations

import re
from typing import Any

from .errors import ModelStructureError

_SCREEN_TYPES = {"WORKBENCH", "LIST", "SINGLE_FORM", "MASTER_DETAIL_FORM", "QUERY_LIST"}
_ELEMENT_TYPES = {
    "TEXTBOX",
    "TEXTAREA",
    "COMBO",
    "DATEPICKER",
    "POPUP_SELECT",
    "NUMBER",
    "CHECKBOX",
    "BUTTON",
    "GRID",
    "LABEL",
}
_IO_TYPES = {"I", "O", "I_O"}
_LAYOUT_TOKEN_RE = re.compile(r"\[([^\][|]+?)\]")
_PAGINATION_RE = re.compile(r"^(\d+|>|»|<|<<|\.\.+)$")


def validate_ui_model(doc: dict[str, Any]) -> None:
    screens = doc.get("screens")
    if not isinstance(screens, list) or not screens:
        raise ModelStructureError("MU 必须声明 screens 列表（v9 §8.2.3）")

    screen_ids = {s.get("id") for s in screens if isinstance(s, dict)}
    seen_action_ids: set[str] = set()

    for screen in screens:
        if not isinstance(screen, dict):
            raise ModelStructureError("MU screens 只能包含映射对象")
        sid = screen.get("id")
        _require_string(screen, "name", f"屏幕 {sid}")
        stype = screen.get("screenType")
        if stype not in _SCREEN_TYPES:
            raise ModelStructureError(
                f"屏幕 {sid}: screenType={stype!r} 须为 {sorted(_SCREEN_TYPES)}（v9 §8.2.3）"
            )

        elements = screen.get("elements", [])
        if not isinstance(elements, list):
            raise ModelStructureError(f"屏幕 {sid}: elements 必须是列表")
        element_ids: set[str] = set()
        for element in elements:
            if not isinstance(element, dict):
                raise ModelStructureError(f"屏幕 {sid}: elements 项必须是映射")
            eid = element.get("id")
            _require_string(element, "label", f"屏幕 {sid} 元素 {eid}")
            if element.get("type") not in _ELEMENT_TYPES:
                raise ModelStructureError(
                    f"屏幕 {sid} 元素 {eid}: type={element.get('type')!r} 须为十类控件（v9 §8.2.6）"
                )
            if element_ids and eid in element_ids:
                raise ModelStructureError(f"屏幕 {sid}: 元素 id 必须唯一: {eid}")
            element_ids.add(str(eid))
            if "io" in element and element["io"] not in _IO_TYPES:
                raise ModelStructureError(f"屏幕 {sid} 元素 {eid}: io 须为 I/O/I_O（v9 §8.2.4）")
            if "required" in element and not isinstance(element["required"], bool):
                raise ModelStructureError(f"屏幕 {sid} 元素 {eid}: required 须为布尔（v9 §8.2.4）")

        layout = screen.get("layout", "")
        if isinstance(layout, str) and layout.strip():
            for raw_token in _LAYOUT_TOKEN_RE.findall(layout):
                token = raw_token.strip().rstrip("_.")
                if not token or _PAGINATION_RE.match(token):
                    continue
                if token not in element_ids:
                    raise ModelStructureError(
                        f"屏幕 {sid}: layout 控件 {token!r} 不在 elements 中（D8.04/§8.7-8）"
                    )

        for menu in screen.get("menus", []) or []:
            if not isinstance(menu, dict):
                raise ModelStructureError(f"屏幕 {sid}: menus 项必须是映射")
            for sub in menu.get("subMenus", []) or []:
                if isinstance(sub, dict) and sub.get("screenRef") not in screen_ids:
                    raise ModelStructureError(
                        f"菜单 {menu.get('menuId')}: screenRef={sub.get('screenRef')} 无对应屏幕（§8.7-9）"
                    )

        for ap in screen.get("actionPoints", []) or []:
            if not isinstance(ap, dict):
                raise ModelStructureError(f"屏幕 {sid}: actionPoints 项必须是映射")
            apid = ap.get("id")
            if apid in seen_action_ids:
                raise ModelStructureError(f"操作点 id 必须唯一: {apid}")
            seen_action_ids.add(str(apid))
            _require_string(ap, "name", f"操作点 {apid}")
            if not ap.get("behaviorRef"):
                raise ModelStructureError(f"操作点 {apid}: behaviorRef 必填——按钮→行为唯一衔接（v9 §8.2.5）")
            element_id = ap.get("elementId")
            if element_id and element_id not in element_ids:
                raise ModelStructureError(
                    f"操作点 {apid}: elementId={element_id!r} 不在屏幕 {sid} elements 中（D8.04）"
                )


def _require_string(obj: dict[str, Any], key: str, where: str) -> None:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ModelStructureError(f"{where}: 字段 {key} 必须是非空字符串")
