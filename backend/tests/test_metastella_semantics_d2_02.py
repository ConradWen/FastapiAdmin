"""m2-minset 工单 08c：D2.02 endpoint 推导一致性 + D8.04 layout 深对齐（TDD RED）。

§12「行为-API 面」：endpoint=/{entity-kebab}/{action-kebab} 由 behavior id 钉死推导；
id 的 {Entity} 段必须与 ownerEntity 一致，且族内 endpoint 唯一（禁两行为撞同一 API 面）。
§12「字段-io 对齐」深半：layout 括号 token 必须存在于 elements（翻页/数字豁免）。
"""

from pathlib import Path

import pytest

from app.modules.metastella_semantics import (
    ModelStructureError,
    check_family,
    endpoint_from_behavior_id,
    load_model_family,
    validate_model,
)

PACKAGE = Path(__file__).parents[1] / "semantic_packages" / "library_smoke"
MANIFEST = "manifest.yaml"


def _load() -> dict:
    return load_model_family(PACKAGE, manifest_name=MANIFEST)


# ---- D2.02 endpoint 推导 ----


def test_endpoint_derivation_rule_d2_02() -> None:
    assert endpoint_from_behavior_id("Book_borrowOut") == "/book/borrow-out"
    assert endpoint_from_behavior_id("BorrowRecord_queryHistory") == "/borrow-record/query-history"


def test_endpoint_id_entity_must_match_owner() -> None:
    doc = _load()["BEHAVIOR"]
    doc["behaviors"][0]["ownerEntity"] = "Reader"
    with pytest.raises(ModelStructureError, match="D2.02"):
        validate_model(doc)


def test_endpoint_unique_across_family() -> None:
    doc = _load()["BEHAVIOR"]
    clone = dict(doc["behaviors"][0])
    clone["id"] = "Book_borrowOUT"
    clone["ownerEntity"] = "Book"
    doc["behaviors"].append(clone)
    family = _load_with_behavior_doc(doc)
    # 给新行为挂界面入口，排除可追溯门禁干扰，让 endpoint 撞车面单独可见
    ap = {"id": "AP-DUP", "name": "重复入口", "behaviorRef": "Book_borrowOUT", "elementId": "搜索"}
    family["UI"]["screens"][0].setdefault("actionPoints", []).append(ap)
    with pytest.raises(ModelStructureError, match="endpoint"):
        check_family(family, raise_on_error=True)


def _load_with_behavior_doc(doc: dict) -> dict:
    family = _load()
    family["BEHAVIOR"] = doc
    return family


# ---- D8.04 layout 深对齐 ----


def test_layout_tokens_must_exist_in_elements() -> None:
    doc = _load()["UI"]
    screen = next(s for s in doc["screens"] if s["id"] == "SCREEN-BOOK-LIST")
    screen["layout"] = screen["layout"].replace("[借出]", "[删除]")
    with pytest.raises(ModelStructureError, match="删除"):
        validate_model(doc)


def test_pagination_tokens_exempt() -> None:
    doc = _load()["UI"]
    validate_model(doc)  # 现有语料含 [1] [2] >| 不得误报


def test_corpus_current_passes_08c() -> None:
    result = check_family(_load(), package="library_smoke")
    assert result.errors == [], result.errors
