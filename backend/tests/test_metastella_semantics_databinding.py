"""m2-minset 工单 09：dataBinding 引用可解析（§8.7-1）+ io/required 与 M1 对齐（D8.04）TDD RED。

dataBinding=`{AggregateAlias}.{attributeName}`；io∈{I,I_O} 的元素绑 M1 必填属性时元素 required 必须为真；
required=True 的元素 io 不得为纯 O；io=O（输出）可绑非必填属性。
"""

from pathlib import Path

import pytest

from app.modules.metastella_semantics import check_family, load_model_family, validate_model

PACKAGE = Path(__file__).parents[1] / "semantic_packages" / "library_smoke"
MANIFEST = "manifest.yaml"


def _load() -> dict:
    return load_model_family(PACKAGE, manifest_name=MANIFEST)


def test_corpus_family_still_green_after_databinding() -> None:
    result = check_family(_load(), package="library_smoke")
    assert result.errors == [], result.errors


def test_data_binding_path_must_resolve_to_m1() -> None:
    family = _load()
    screen = next(s for s in family["UI"]["screens"] if s["id"] == "SCREEN-BOOK-LIST")
    book_no = next(e for e in screen["elements"] if e["id"] == "bookNo")
    book_no["dataBinding"] = "Book.ghostField"
    with pytest.raises(Exception, match="ghostField"):
        check_family(family, raise_on_error=True)


def test_data_binding_bad_shape_rejected() -> None:
    family = _load()
    screen = next(s for s in family["UI"]["screens"] if s["id"] == "SCREEN-BOOK-LIST")
    title = next(e for e in screen["elements"] if e["id"] == "title")
    title["dataBinding"] = "justaname"
    with pytest.raises(Exception, match="dataBinding"):
        check_family(family, raise_on_error=True)


def test_required_element_bound_to_optional_attr_rejected() -> None:
    """M1 属性非必填但元素标 required=True——双源漂移（D8.04）。"""
    family = _load()
    screen = next(s for s in family["UI"]["screens"] if s["id"] == "SCREEN-BOOK-LIST")
    listed = next(e for e in screen["elements"] if e["id"] == "listedAt")
    listed["dataBinding"] = "Book.listedAt"
    listed["io"] = "I"
    listed["required"] = True
    with pytest.raises(Exception, match="required"):
        check_family(family, raise_on_error=True)


def test_output_element_must_not_be_required() -> None:
    family = _load()
    screen = next(s for s in family["UI"]["screens"] if s["id"] == "SCREEN-BOOK-LIST")
    grid = next(e for e in screen["elements"] if e["id"] == "grid")
    grid["required"] = True
    with pytest.raises(Exception, match="required"):
        validate_model(family["UI"])


def test_missing_required_binding_warns() -> None:
    """M1 必填属性未有任何输入元素绑定=表单缺必填入口（warning 级留痕）。"""
    family = _load()
    for screen in family["UI"]["screens"]:
        for element in screen.get("elements", []):
            if element.get("dataBinding", "").startswith("Book.bookNo"):
                del element["dataBinding"]
    result = check_family(family)
    assert not result.errors
    assert any("bookNo" in w for w in result.warnings)
