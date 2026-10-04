"""m2-minset 工单 02：M1 OBJECT validator 单测（TDD）。

覆盖：D1.01 版本、D1.02 PG 类型/引用、D1.03 租户注入与豁免登记、D1.04 并发扩展位、
以及 v9 M1 元素表的结构约束。loader 默认保持工单 01 行为；显式 validate=True 才进入发布前硬门禁。
"""

from copy import deepcopy
from pathlib import Path

import pytest

from app.modules.metastella_semantics import (
    MissingSchemaVersionError,
    ModelStructureError,
    load_model_file,
    validate_model,
)


def valid_object_doc() -> dict:
    return {
        "schema_version": "1.0.0",
        "model_type": "OBJECT",
        "domain": "图书管理",
        "aggregates": [
            {
                "id": "AGG-BOOK-001",
                "name": "图书",
                "alias": "Book",
                "aggregateType": "AGGREGATE_ROOT",
                "description": "可被借阅的图书聚合",
                "lifecycle": ["在架", "借出"],
                "tags": ["核心域"],
                "attributes": [
                    {
                        "name": "bookNo",
                        "label": "图书编号",
                        "type": "String",
                        "required": True,
                        "unique": True,
                    },
                    {
                        "name": "categoryCode",
                        "label": "图书分类",
                        "type": "DictionaryRef",
                        "required": True,
                        "dictionaryRef": {
                            "dictionaryId": "DICT-BOOK-001",
                            "typeCode": "BOOK_CATEGORY",
                        },
                    },
                    {
                        "name": "authorId",
                        "label": "作者",
                        "type": "AggregateRootRef",
                        "required": True,
                        "targetAggregate": "AGG-AUTHOR-001",
                    },
                    {
                        "name": "price",
                        "label": "售价",
                        "type": "Money",
                        "required": True,
                        "refRules": [
                            {
                                "name": "售价必须为正数",
                                "description": "售价必须大于 0",
                                "expression": "value > 0",
                                "violationMessage": "售价必须大于 0",
                                "enforcedAt": "ALWAYS",
                            }
                        ],
                    },
                ],
                "entities": [
                    {
                        "name": "馆藏副本",
                        "alias": "BookCopy",
                        "description": "图书的可借副本",
                        "localId": "copyId",
                        "cardinality": "ZERO_OR_MORE",
                        "cascadeDelete": True,
                        "attributes": [
                            {
                                "name": "copyId",
                                "label": "副本编号",
                                "type": "String",
                                "required": True,
                            }
                        ],
                    }
                ],
                "valueObjects": [
                    {
                        "name": "图书封面",
                        "alias": "Cover",
                        "description": "图书封面展示信息",
                        "immutable": True,
                        "equalityFields": ["isbn"],
                        "attributes": [
                            {
                                "name": "isbn",
                                "label": "ISBN",
                                "type": "String",
                                "required": True,
                            }
                        ],
                    }
                ],
                "invariants": [
                    {
                        "name": "图书编号非空",
                        "expression": "bookNo != ''",
                        "violationMessage": "图书编号不能为空",
                        "enforcedAt": "ON_CREATE",
                    }
                ],
            },
            {
                "id": "AGG-AUTHOR-001",
                "name": "作者",
                "alias": "Author",
                "aggregateType": "AGGREGATE_ROOT",
                "description": "作者聚合",
                "lifecycle": ["活跃"],
                "attributes": [
                    {
                        "name": "authorName",
                        "label": "作者姓名",
                        "type": "String",
                        "required": True,
                    }
                ],
                "entities": [],
                "valueObjects": [],
                "invariants": [],
            },
        ],
        "data_dictionaries": [
            {
                "id": "DICT-BOOK-001",
                "name": "图书基础字典",
                "types": [
                    {
                        "typeCode": "BOOK_CATEGORY",
                        "typeName": "图书分类",
                        "items": [
                            {
                                "code": "LITERATURE",
                                "label": "文学",
                                "enabled": True,
                                "sortOrder": 10,
                            }
                        ],
                    }
                ],
            }
        ],
        "aggregate_associations": [
            {
                "id": "ASSOC-BOOK-AUTHOR",
                "sourceAggregate": "AGG-BOOK-001",
                "targetAggregate": "AGG-AUTHOR-001",
                "associationType": "REFERENCE",
                "sourceRole": "所属作者",
                "targetRole": "撰写图书",
                "cardinality": "MANY_TO_ONE",
                "referenceField": "authorId",
            }
        ],
        "tenantScopedExemptions": [],
    }


def test_valid_object_model_passes() -> None:
    assert validate_model(valid_object_doc()) is None


def test_missing_schema_version_rejected_d1_01() -> None:
    doc = valid_object_doc()
    doc.pop("schema_version")
    with pytest.raises(MissingSchemaVersionError, match="D11.01"):
        validate_model(doc)


def test_missing_aggregates_rejected() -> None:
    doc = valid_object_doc()
    doc.pop("aggregates")
    with pytest.raises(ModelStructureError, match="aggregates"):
        validate_model(doc)


def test_duplicate_aggregate_id_rejected() -> None:
    doc = valid_object_doc()
    duplicate = deepcopy(doc["aggregates"][0])
    doc["aggregates"].append(duplicate)
    with pytest.raises(ModelStructureError, match="唯一"):
        validate_model(doc)


def test_unknown_attribute_type_rejected_d1_02() -> None:
    doc = valid_object_doc()
    doc["aggregates"][0]["attributes"][0]["type"] = "VARCHAR"
    with pytest.raises(ModelStructureError, match="D1.02"):
        validate_model(doc)


def test_tenant_id_attribute_rejected_d1_03() -> None:
    doc = valid_object_doc()
    doc["aggregates"][0]["attributes"].append(
        {"name": "tenantId", "label": "租户", "type": "String", "required": True}
    )
    with pytest.raises(ModelStructureError, match="D1.03"):
        validate_model(doc)


def test_tenant_scoped_false_requires_registry_d1_03() -> None:
    doc = valid_object_doc()
    doc["aggregates"][0]["tenantScoped"] = False
    with pytest.raises(ModelStructureError, match="D1.03"):
        validate_model(doc)

    doc = valid_object_doc()
    doc["aggregates"][0]["tenantScoped"] = False
    doc["tenantScopedExemptions"] = [
        {
            "aggregateAlias": "Book",
            "reason": "平台级共享图书元数据",
            "nfr5Test": "tests/generated/nfr5_book_shared.py",
        }
    ]
    assert validate_model(doc) is None


def test_enum_requires_values() -> None:
    doc = valid_object_doc()
    attr = doc["aggregates"][0]["attributes"][0]
    attr["type"] = "Enum"
    attr.pop("enumValues", None)
    with pytest.raises(ModelStructureError, match="enumValues"):
        validate_model(doc)


def test_aggregate_ref_target_must_exist() -> None:
    doc = valid_object_doc()
    doc["aggregates"][0]["attributes"][2]["targetAggregate"] = "AGG-MISSING-001"
    with pytest.raises(ModelStructureError, match="AGG-MISSING-001"):
        validate_model(doc)


def test_dictionary_ref_target_must_exist() -> None:
    doc = valid_object_doc()
    doc["aggregates"][0]["attributes"][1]["dictionaryRef"]["typeCode"] = "MISSING_TYPE"
    with pytest.raises(ModelStructureError, match="MISSING_TYPE"):
        validate_model(doc)


def test_dictionary_ref_cannot_have_enum_values() -> None:
    doc = valid_object_doc()
    doc["aggregates"][0]["attributes"][1]["enumValues"] = ["A"]
    with pytest.raises(ModelStructureError, match="DictionaryRef"):
        validate_model(doc)


def test_value_object_equality_field_must_exist() -> None:
    doc = valid_object_doc()
    doc["aggregates"][0]["valueObjects"][0]["equalityFields"] = ["missing"]
    with pytest.raises(ModelStructureError, match="missing"):
        validate_model(doc)


def test_association_reference_field_must_exist_in_source_attributes() -> None:
    doc = valid_object_doc()
    doc["aggregate_associations"][0]["referenceField"] = "missingId"
    with pytest.raises(ModelStructureError, match="missingId"):
        validate_model(doc)


def test_concurrency_valid_expansion_passes_d1_04() -> None:
    doc = valid_object_doc()
    doc["aggregates"][0]["attributes"][0]["concurrency"] = "optimistic_lock"
    assert validate_model(doc) is None


def test_concurrency_invalid_rejected_d1_04() -> None:
    doc = valid_object_doc()
    doc["aggregates"][0]["attributes"][0]["concurrency"] = "row_lock"
    with pytest.raises(ModelStructureError, match="D1.04"):
        validate_model(doc)


def test_loader_validate_flag_dispatches_registry(tmp_path: Path) -> None:
    p = tmp_path / "m1.yaml"
    p.write_text("model_type: OBJECT\nschema_version: \"1.0.0\"\n", encoding="utf-8")

    _, mt, version = load_model_file(p)
    assert mt == "OBJECT" and version == "1.0.0"

    with pytest.raises(ModelStructureError):
        load_model_file(p, validate=True)
