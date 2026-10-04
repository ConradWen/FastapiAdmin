"""m2-minset 工单 01：语义骨架模块单测（元模型规范 v1 骨架断言）。

覆盖：schema_version 前置校验（缺/错/边界）、model_type 分派、族装载与 D 一致性、最小集标记（D13.01）。
"""

from pathlib import Path

import pytest

from app.modules.metastella_semantics import (
    MINIMAL_SET,
    BadSchemaVersionError,
    MissingSchemaVersionError,
    ModelFamilyInconsistencyError,
    UnknownModelTypeError,
    load_model_family,
    load_model_file,
)

FIXTURES = Path(__file__).parent / "fixtures_metastella"


def _write(name: str, text: str) -> Path:
    FIXTURES.mkdir(exist_ok=True)
    p = FIXTURES / name
    p.write_text(text, encoding="utf-8")
    return p


def test_missing_schema_version_rejected(tmp_path: Path) -> None:
    p = tmp_path / "m1.yaml"
    p.write_text("model_type: OBJECT\naggregates: []\n", encoding="utf-8")
    with pytest.raises(MissingSchemaVersionError):
        load_model_file(p)


def test_bad_schema_version_rejected(tmp_path: Path) -> None:
    p = tmp_path / "m1.yaml"
    p.write_text("model_type: OBJECT\nschema_version: 1.0\n", encoding="utf-8")
    with pytest.raises(BadSchemaVersionError):
        load_model_file(p)


def test_schema_version_ok(tmp_path: Path) -> None:
    p = tmp_path / "m1.yaml"
    p.write_text("model_type: OBJECT\nschema_version: \"1.0.0\"\n", encoding="utf-8")
    _, mt, ver = load_model_file(p)
    assert mt == "OBJECT" and ver == "1.0.0"


def test_unknown_model_type_rejected(tmp_path: Path) -> None:
    p = tmp_path / "x.yaml"
    p.write_text("model_type: NOT_A_MODEL\nschema_version: \"1.0.0\"\n", encoding="utf-8")
    with pytest.raises(UnknownModelTypeError):
        load_model_file(p)


def test_minimal_set_marker_d13() -> None:
    assert MINIMAL_SET == {"OBJECT", "BEHAVIOR", "RULE", "ACTOR", "FLOW", "UI"}
    assert "EVENT" not in MINIMAL_SET and "REPORT" not in MINIMAL_SET


def test_family_load_and_consistency(tmp_path: Path) -> None:
    d = tmp_path
    (d / "manifest.json").write_text(
        "model_type: MANIFEST\nschema_version: \"1.0.0\"\nmodel_files: [m1.yaml, m2.yaml]\n",
        encoding="utf-8",
    )
    (d / "m1.yaml").write_text("model_type: OBJECT\nschema_version: \"1.0.0\"\n", encoding="utf-8")
    (d / "m2.yaml").write_text("model_type: BEHAVIOR\nschema_version: \"1.0.0\"\n", encoding="utf-8")
    family = load_model_family(d)
    assert set(family) == {"OBJECT", "BEHAVIOR"}


def test_family_inconsistent_version_rejected_d11(tmp_path: Path) -> None:
    d = tmp_path
    (d / "manifest.json").write_text(
        "model_type: MANIFEST\nschema_version: \"1.0.0\"\nmodel_files: [a.yaml, b.yaml]\n",
        encoding="utf-8",
    )
    (d / "a.yaml").write_text("model_type: OBJECT\nschema_version: \"1.0.0\"\n", encoding="utf-8")
    (d / "b.yaml").write_text("model_type: RULE\nschema_version: \"1.1.0\"\n", encoding="utf-8")
    with pytest.raises(ModelFamilyInconsistencyError):
        load_model_family(d)


def test_real_reference_example_loads() -> None:
    """上游客题全例（合同管理七类）装载冒烟——底稿样例为历史 v9 版式（version 字段），非规范元文件。

    规范 v1 钉 schema_version 首字段（D11.01），样例用 `version: "1.1"`——两者**有意不同**；
    规范族装载冒烟由图书考题族（工单 03 产物）承担，本测试仅显示差异登记（skip 说明）。
    """
    ref = Path("/home/jimmy/projects/Ryit/ontology-driven-dev/reference-example")
    if not ref.exists():
        pytest.skip("参考示例目录不存在（时点底稿，非本仓资产）")
    pytest.skip(
        "reference-example 为历史 v9 版式（version 字段），规范 v1 钉 schema_version（D11.01）——"
        "差异为规范有意裁定；族装载冒烟改由图书考题族承担（工单 03）"
    )


def _fixture_guard() -> None:
    """conftest 外的固定目录清理哨（不入库临时物）。"""
    if FIXTURES.exists() and not any(FIXTURES.iterdir()):
        FIXTURES.rmdir()
