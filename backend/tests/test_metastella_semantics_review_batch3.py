"""审计修复批④：B-I3 密钥扫描补漏 / B-I6 同版本换内容无限重发布。"""

from pathlib import Path

import pytest

from app.modules.metastella_semantics import (
    ModelPackageAlreadyPublishedError,
    check_family,
    load_model_family,
    publish_package,
)

PACKAGE = Path(__file__).parents[1] / "semantic_packages" / "library_smoke"


@pytest.fixture(autouse=True)
def _reset_registry():
    from app.modules.metastella_semantics.publish import _reset_registry_for_tests

    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


def _load() -> dict:
    return load_model_family(PACKAGE, manifest_name="manifest.yaml")


# ---- B-I3 ----


def test_secret_in_string_list_detected() -> None:
    family = _load()
    family["OBJECT"]["aggregates"][0]["tags"] = ["核心域", "sk-abcdefghij1234567890"]
    with pytest.raises(Exception, match="密钥"):
        check_family(family, raise_on_error=True)


def test_secret_under_sensitive_key_detected() -> None:
    family = _load()
    family["OBJECT"]["_probe"] = {"api_key": "ABCDEFGH12345678"}
    with pytest.raises(Exception, match="密钥"):
        check_family(family, raise_on_error=True)


def test_placeholder_under_sensitive_key_allowed() -> None:
    family = _load()
    family["OBJECT"]["_probe"] = {"api_key": "{{API_KEY}}", "password": "<占位符>"}
    check_family(family, raise_on_error=True)  # 不抛=通过


# ---- B-I6 ----


def test_same_version_new_content_cannot_republish() -> None:
    f1 = _load()
    publish_package(f1, package_name="vchk_pkg")
    f2 = _load()
    f2["OBJECT"]["domain"] = "图书管理（内容变更，版本未动）"
    with pytest.raises(ModelPackageAlreadyPublishedError, match="版本"):
        publish_package(f2, package_name="vchk_pkg")


def test_bumped_version_new_content_publishes() -> None:
    f1 = _load()
    publish_package(f1, package_name="vchk2_pkg")
    f2 = _load()
    f2["OBJECT"]["domain"] = "图书管理（变更）"
    for doc in f2.values():
        doc["schema_version"] = "1.0.1"
    record = publish_package(f2, package_name="vchk2_pkg")
    assert record["schema_version"] == "1.0.1"
