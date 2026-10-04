"""m2-minset 工单 04：语义包发布状态机单测（TDD RED 阶段）。

覆盖：D11.02 canonical_json 指纹（SHA-256 可复算）/D11.03 版本演进/草稿→发布不可变（F-3）/
重发布同指纹拒绝/发布快照留痕。
"""

import json
from pathlib import Path

import pytest

from app.modules.metastella_semantics import (
    ModelPackageAlreadyPublishedError,
    compute_package_fingerprint,
    load_model_family,
    publish_package,
)

PACKAGE = Path(__file__).parents[1] / "semantic_packages" / "library_smoke"
MANIFEST = "manifest.yaml"


@pytest.fixture(autouse=True)
def _isolated_publish_registry():
    """进程内发布注册表逐测试清空（测试隔离；生产注册表随进程生命周期）。"""
    from app.modules.metastella_semantics.publish import _reset_registry_for_tests

    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


def _load() -> dict:
    return load_model_family(PACKAGE, manifest_name=MANIFEST)


def test_fingerprint_is_stable_sha256() -> None:
    family = _load()
    fp1 = compute_package_fingerprint(family)
    fp2 = compute_package_fingerprint(_load())
    assert fp1 == fp2
    assert len(fp1) == 64
    int(fp1, 16)  # 纯 hex


def test_fingerprint_changes_when_content_changes() -> None:
    family = _load()
    fp_before = compute_package_fingerprint(family)
    family["OBJECT"]["domain"] = "图书管理（改）"
    assert compute_package_fingerprint(family) != fp_before


def test_fingerprint_key_order_insensitive() -> None:
    family = _load()
    fp1 = compute_package_fingerprint(family)
    reordered = {k: dict(reversed(list(v.items()))) for k, v in family.items()}
    assert compute_package_fingerprint(reordered) == fp1


def test_publish_draft_returns_fingerprint_and_snapshot() -> None:
    family = _load()
    record = publish_package(family, package_name="library_smoke")
    assert record["status"] == "PUBLISHED"
    assert record["fingerprint"] == compute_package_fingerprint(family)
    assert record["schema_version"] == "1.0.0"
    assert record["package_name"] == "library_smoke"
    assert record["models"] == {"OBJECT": None, "BEHAVIOR": None, "RULE": None, "ACTOR": None, "FLOW": None, "UI": None}


def test_publish_is_immutable_same_fingerprint_rejected() -> None:
    family = _load()
    record = publish_package(family, package_name="library_smoke")
    with pytest.raises(ModelPackageAlreadyPublishedError, match=record["fingerprint"]):
        publish_package(family, package_name="library_smoke")


def test_new_content_republish_allowed_after_publish(tmp_path: Path) -> None:
    """内容变化→新指纹可再发布（F-3 不可变指同指纹，非同包名永久锁死）。"""
    family = _load()
    publish_package(family, package_name="library_smoke")
    family["OBJECT"]["domain"] = "图书管理（增补）"
    record2 = publish_package(family, package_name="library_smoke")
    assert record2["status"] == "PUBLISHED"
    assert record2["fingerprint"] != compute_package_fingerprint(_load())


def test_publish_record_json_serializable(tmp_path: Path) -> None:
    family = _load()
    record = publish_package(family, package_name="library_smoke")
    dumped = json.dumps(record, ensure_ascii=False)
    loaded = json.loads(dumped)
    assert loaded["fingerprint"] == record["fingerprint"]
