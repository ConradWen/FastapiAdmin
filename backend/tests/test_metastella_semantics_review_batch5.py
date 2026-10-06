"""审计修复批⑤：B-I8 生成面缺口（entities 丢弃/ValueObject 类型集分裂） + B-I10 D8.04 控件映射机检。"""

from pathlib import Path

from app.modules.metastella_semantics import check_family, generate_ddl, load_model_family

PACKAGE = Path(__file__).parents[1] / "semantic_packages" / "library_smoke"


def _load() -> dict:
    return load_model_family(PACKAGE, manifest_name="manifest.yaml")


def _book(family: dict) -> dict:
    return family["OBJECT"]["aggregates"][0]


def _screen_elements(family: dict) -> list:
    return family["UI"]["screens"][1]["elements"]


# ---- B-I8a：ValueObject 类型集分裂（校验/发布过、generate_ddl 崩） ----


def test_valueobject_attribute_generates_jsonb_column() -> None:
    family = _load()
    _book(family)["attributes"].append(
        {"name": "cover", "label": "封面", "type": "ValueObject", "valueObjectRef": "Cover", "required": False}
    )
    ddl = generate_ddl(family)
    assert "cover" in ddl
    assert "jsonb" in ddl


def test_valueobject_attribute_passes_family_check() -> None:
    family = _load()
    _book(family)["attributes"].append(
        {"name": "cover", "label": "封面", "type": "ValueObject", "valueObjectRef": "Cover", "required": False}
    )
    result = check_family(family, raise_on_error=True)
    assert result.errors == []


# ---- B-I8b：子实体被生成器静默丢弃 → warning 留痕（生成面缺口） ----


def test_child_entities_emit_generation_gap_warning() -> None:
    family = _load()
    _book(family)["entities"] = [
        {
            "id": "ENT-BOOK-CHAPTER",
            "name": "章节",
            "alias": "Chapter",
            "attributes": [{"name": "seq", "label": "序号", "type": "Integer", "required": True}],
        }
    ]
    result = check_family(family, raise_on_error=False)
    joined = " ".join(result.warnings)
    assert "生成面缺口" in joined
    assert "Chapter" in joined


def test_no_entities_no_generation_gap_warning() -> None:
    family = _load()
    result = check_family(family, raise_on_error=False)
    assert not any("生成面缺口" in w for w in result.warnings)


# ---- B-I10：D8.04 控件映射机检（语义类型 → 控件类型） ----


def _bind(family: dict, attr: dict, control_type: str) -> None:
    _book(family)["attributes"].append(attr)
    _screen_elements(family).append(
        {
            "id": f"probe_{attr['name']}",
            "type": control_type,
            "label": attr["name"],
            "io": "I",
            "dataBinding": f"Book.{attr['name']}",
        }
    )


def test_enum_attr_bound_to_wrong_control_errors() -> None:
    family = _load()
    _bind(family, {"name": "probeEnum", "label": "枚举", "type": "Enum", "enumValues": ["a", "b"]}, "TEXTBOX")
    result = check_family(family, raise_on_error=False)
    assert any("控件映射" in e and "probeEnum" in e for e in result.errors)


def test_enum_attr_bound_to_combo_ok() -> None:
    family = _load()
    _bind(family, {"name": "probeEnum", "label": "枚举", "type": "Enum", "enumValues": ["a", "b"]}, "COMBO")
    result = check_family(family, raise_on_error=True)
    assert result.errors == []


def test_boolean_attr_bound_to_wrong_control_errors() -> None:
    family = _load()
    _bind(family, {"name": "probeBool", "label": "布尔", "type": "Boolean"}, "TEXTBOX")
    result = check_family(family, raise_on_error=False)
    assert any("控件映射" in e and "probeBool" in e for e in result.errors)


def test_boolean_attr_bound_to_checkbox_ok() -> None:
    family = _load()
    _bind(family, {"name": "probeBool", "label": "布尔", "type": "Boolean"}, "CHECKBOX")
    result = check_family(family, raise_on_error=True)
    assert result.errors == []


def test_aggregateref_bound_to_wrong_control_errors() -> None:
    family = _load()
    _bind(
        family,
        {"name": "probeRef", "label": "外键", "type": "AggregateRootRef", "targetAggregate": "Reader"},
        "COMBO",
    )
    result = check_family(family, raise_on_error=False)
    assert any("控件映射" in e and "probeRef" in e for e in result.errors)


def test_aggregateref_bound_to_popup_select_ok() -> None:
    family = _load()
    _bind(
        family,
        {"name": "probeRef", "label": "外键", "type": "AggregateRootRef", "targetAggregate": "Reader"},
        "POPUP_SELECT",
    )
    result = check_family(family, raise_on_error=True)
    assert result.errors == []


def test_datetime_bound_to_datepicker_ok() -> None:
    family = _load()
    _bind(family, {"name": "probeDT", "label": "时间", "type": "DateTime"}, "DATEPICKER")
    result = check_family(family, raise_on_error=True)
    assert result.errors == []


def test_unmapped_text_type_not_flagged() -> None:
    family = _load()
    _bind(family, {"name": "probeStr", "label": "文本", "type": "String"}, "TEXTBOX")
    result = check_family(family, raise_on_error=True)
    assert result.errors == []
