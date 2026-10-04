"""M1 OBJECT 对象模型 validator（v9 第二章 + D1.01~D1.06）。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .errors import ModelStructureError

_ALLOWED_ATTRIBUTE_TYPES = {
    "String",
    "Text",
    "Integer",
    "Decimal",
    "Boolean",
    "Date",
    "DateTime",
    "JSON",
    "Enum",
    "Reference",
    "Attachment",
    "Money",
    "ValueObject",
    "AggregateRootRef",
    "DictionaryRef",
}
_ALLOWED_CONCURRENCY = {"optimistic_lock"}
_ENFORCED_AT = {"ON_CREATE", "ON_UPDATE", "ON_DELETE", "ALWAYS"}
_ENTITY_CARDINALITY = {"ONE", "ZERO_OR_ONE", "ONE_OR_MORE", "ZERO_OR_MORE"}
_ASSOCIATION_TYPES = {"REFERENCE", "DEPENDENCY"}
_ASSOCIATION_CARDINALITY = {"ONE_TO_ONE", "ONE_TO_MANY", "MANY_TO_ONE", "MANY_TO_MANY"}
_TENANT_ATTRIBUTE_NAMES = {"tenantId", "tenant_id"}


def validate_object_model(doc: dict[str, Any]) -> None:
    """校验 OBJECT 元文件；失败抛 ModelStructureError（error 级阻断发布）。"""
    if doc.get("model_type") != "OBJECT":
        _fail("OBJECT validator 只能校验 model_type=OBJECT 的元文件")

    aggregates = _require_list(doc, "aggregates", "OBJECT 根节点")
    if not aggregates:
        _fail("OBJECT 必须声明 aggregates（M1 聚合根集合）")

    aggregate_index = _build_aggregate_index(aggregates)
    dictionary_index = _build_dictionary_index(doc.get("data_dictionaries", []))
    _validate_associations(doc.get("aggregate_associations", []), aggregate_index)
    _validate_tenant_registry(doc, aggregate_index)

    for aggregate in aggregates:
        _validate_aggregate_body(aggregate, aggregate_index, dictionary_index)


def _build_aggregate_index(aggregates: Sequence[Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for aggregate in _iter_mappings(aggregates, "aggregates"):
        where = f"聚合 {aggregate.get('id', aggregate.get('name', '<unnamed>'))}"
        aggregate_id = _require_string(aggregate, "id", where)
        name = _require_string(aggregate, "name", where)
        alias = _require_string(aggregate, "alias", where)
        aggregate_type = _require_string(aggregate, "aggregateType", where)
        if aggregate_type != "AGGREGATE_ROOT":
            _fail(f"{where}: aggregateType={aggregate_type!r} 必须是 AGGREGATE_ROOT")
        for key, value in (("id", aggregate_id), ("name", name), ("alias", alias)):
            for existing in index.values():
                if existing[key] == value:
                    _fail(f"聚合 {key} 必须唯一: {value}")
        attribute_names = _attribute_names(aggregate.get("attributes", []), where)
        value_object_names = _names(aggregate.get("valueObjects", []), "valueObjects", where)
        index[aggregate_id] = {
            "id": aggregate_id,
            "name": name,
            "alias": alias,
            "aggregate": aggregate,
            "attribute_names": attribute_names,
            "value_object_names": value_object_names,
        }
    return index


def _build_dictionary_index(data_dictionaries: Any) -> dict[str, set[str]]:
    if not isinstance(data_dictionaries, list):
        _fail("data_dictionaries 必须是列表")

    index: dict[str, set[str]] = {}
    dictionary_ids: set[str] = set()
    for dictionary in _iter_mappings(data_dictionaries, "data_dictionaries"):
        dictionary_id = _require_string(dictionary, "id", "数据字典")
        _require_string(dictionary, "name", f"数据字典 {dictionary_id}")
        if dictionary_id in dictionary_ids:
            _fail(f"数据字典 id 必须唯一: {dictionary_id}")
        dictionary_ids.add(dictionary_id)

        type_codes: set[str] = set()
        types = _require_list(dictionary, "types", f"数据字典 {dictionary_id}")
        for type_obj in _iter_mappings(types, f"数据字典 {dictionary_id} 的 types"):
            type_code = _require_string(type_obj, "typeCode", f"数据字典 {dictionary_id} 的字典类型")
            _require_string(type_obj, "typeName", f"数据字典 {dictionary_id}.{type_code}")
            if type_code in type_codes:
                _fail(f"数据字典 {dictionary_id} 的 typeCode 必须唯一: {type_code}")
            type_codes.add(type_code)

            codes: set[str] = set()
            items = _require_list(type_obj, "items", f"数据字典 {dictionary_id}.{type_code}")
            for item in _iter_mappings(items, f"数据字典 {dictionary_id}.{type_code} 的 items"):
                code = _require_string(item, "code", f"数据字典 {dictionary_id}.{type_code}")
                _require_string(item, "label", f"字典项 {dictionary_id}.{type_code}.{code}")
                _require_optional_bool(item, "enabled", f"字典项 {code}")
                _require_optional_int(item, "sortOrder", f"字典项 {code}")
                if code in codes:
                    _fail(f"字典项 code 必须唯一: {dictionary_id}.{type_code}.{code}")
                codes.add(code)
        index[dictionary_id] = type_codes
    return index


def _validate_associations(associations: Any, aggregate_index: Mapping[str, Mapping[str, Any]]) -> None:
    if not isinstance(associations, list):
        _fail("aggregate_associations 必须是列表")

    seen_ids: set[str] = set()
    for association in _iter_mappings(associations, "aggregate_associations"):
        where = f"聚合间关联 {association.get('id', '<unnamed>')}"
        association_id = _require_string(association, "id", where)
        if association_id in seen_ids:
            _fail(f"聚合间关联 id 必须唯一: {association_id}")
        seen_ids.add(association_id)

        source = _require_string(association, "sourceAggregate", where)
        target = _require_string(association, "targetAggregate", where)
        _require_enum(association, "associationType", where, _ASSOCIATION_TYPES)
        _require_enum(association, "cardinality", where, _ASSOCIATION_CARDINALITY)
        _require_string(association, "sourceRole", where)
        _require_string(association, "targetRole", where)
        reference_field = _require_string(association, "referenceField", where)
        _require_existing_target(aggregate_index, source, where, "sourceAggregate")
        _require_existing_target(aggregate_index, target, where, "targetAggregate")

        source_attributes = aggregate_index[source]["attribute_names"]
        if reference_field not in source_attributes:
            _fail(f"{where}: referenceField={reference_field} 不存在于来源聚合 {source} 的 attributes 中")


def _validate_tenant_registry(doc: Mapping[str, Any], aggregate_index: Mapping[str, Mapping[str, Any]]) -> None:
    exemptions = doc.get("tenantScopedExemptions", [])
    if not isinstance(exemptions, list):
        _fail("tenantScopedExemptions 必须是列表（D1.03）")

    registered: set[str] = set()
    for exemption in _iter_mappings(exemptions, "tenantScopedExemptions"):
        aggregate_alias = _require_string(exemption, "aggregateAlias", "租户豁免登记")
        _require_string(exemption, "reason", f"租户豁免登记 {aggregate_alias}")
        _require_string(exemption, "nfr5Test", f"租户豁免登记 {aggregate_alias}")
        if aggregate_alias in registered:
            _fail(f"租户豁免登记 aggregateAlias 必须唯一: {aggregate_alias}")
        registered.add(aggregate_alias)

    unscoped = {
        info["alias"]
        for info in aggregate_index.values()
        if info["aggregate"].get("tenantScoped") is False
    }
    if unscoped != registered:
        _fail(
            "D1.03: tenantScoped=false 的聚合必须与显式租户豁免登记表完全一致: "
            f"未登记={sorted(unscoped - registered)}, 多余登记={sorted(registered - unscoped)}"
        )


def _validate_aggregate_body(
    aggregate: Mapping[str, Any],
    aggregate_index: Mapping[str, Mapping[str, Any]],
    dictionary_index: Mapping[str, set[str]],
) -> None:
    aggregate_id = _require_string(aggregate, "id", "聚合")
    where = f"聚合 {aggregate_id}"
    value_object_names = aggregate_index[aggregate_id]["value_object_names"]
    _require_list(aggregate, "attributes", where)
    _validate_attributes(
        aggregate.get("attributes", []),
        where,
        aggregate_index,
        dictionary_index,
        value_object_names,
        is_root=True,
    )
    _validate_unique_attribute_names(aggregate.get("attributes", []), where)

    for entity in _iter_mappings(aggregate.get("entities", []), f"{where} 的 entities"):
        _validate_entity(entity, where, aggregate_index, dictionary_index, value_object_names)

    for value_object in _iter_mappings(aggregate.get("valueObjects", []), f"{where} 的 valueObjects"):
        _validate_value_object(
            value_object,
            where,
            aggregate_index,
            dictionary_index,
            value_object_names,
        )

    invariant_names: set[str] = set()
    for invariant in _iter_mappings(aggregate.get("invariants", []), f"{where} 的 invariants"):
        invariant_name = _require_string(invariant, "name", f"{where} 的不变量")
        _require_string(invariant, "expression", f"不变量 {invariant_name}")
        _require_string(invariant, "violationMessage", f"不变量 {invariant_name}")
        _require_enum(invariant, "enforcedAt", f"不变量 {invariant_name}", _ENFORCED_AT)
        if invariant_name in invariant_names:
            _fail(f"{where}: 不变量 name 必须唯一: {invariant_name}")
        invariant_names.add(invariant_name)


def _validate_entity(
    entity: Mapping[str, Any],
    aggregate_where: str,
    aggregate_index: Mapping[str, Mapping[str, Any]],
    dictionary_index: Mapping[str, set[str]],
    value_object_names: set[str],
) -> None:
    name = _require_string(entity, "name", f"{aggregate_where} 的子实体")
    alias = _require_string(entity, "alias", f"{aggregate_where} 的子实体 {name}")
    local_id = _require_string(entity, "localId", f"子实体 {name}")
    where = f"{aggregate_where} 的子实体 {name}({alias})"
    _require_enum(entity, "cardinality", where, _ENTITY_CARDINALITY)
    _require_optional_bool(entity, "cascadeDelete", where)
    _require_list(entity, "attributes", where)

    attributes = entity.get("attributes", [])
    _validate_attributes(attributes, where, aggregate_index, dictionary_index, value_object_names, is_root=False)
    _validate_unique_attribute_names(attributes, where)
    if local_id not in _attribute_names(attributes, where):
        _fail(f"{where}: localId={local_id} 必须指向子实体 attributes 中的属性名")


def _validate_value_object(
    value_object: Mapping[str, Any],
    aggregate_where: str,
    aggregate_index: Mapping[str, Mapping[str, Any]],
    dictionary_index: Mapping[str, set[str]],
    value_object_names: set[str],
) -> None:
    name = _require_string(value_object, "name", f"{aggregate_where} 的值对象")
    alias = _require_string(value_object, "alias", f"{aggregate_where} 的值对象 {name}")
    where = f"{aggregate_where} 的值对象 {name}({alias})"
    _require_optional_bool(value_object, "immutable", where)
    _require_list(value_object, "attributes", where)

    attributes = value_object.get("attributes", [])
    _validate_attributes(attributes, where, aggregate_index, dictionary_index, value_object_names, is_root=False)
    _validate_unique_attribute_names(attributes, where)

    attribute_names = _attribute_names(attributes, where)
    equality_fields = value_object.get("equalityFields", [])
    if not isinstance(equality_fields, list):
        _fail(f"{where}: equalityFields 必须是列表")
    for field in equality_fields:
        if not isinstance(field, str):
            _fail(f"{where}: equalityFields 必须是字符串列表")
        if field not in attribute_names:
            _fail(f"{where}: equalityFields={field} 不存在于值对象 attributes 中")


def _validate_attributes(
    attributes: Sequence[Any],
    where: str,
    aggregate_index: Mapping[str, Mapping[str, Any]],
    dictionary_index: Mapping[str, set[str]],
    value_object_names: set[str],
    *,
    is_root: bool,
) -> None:
    for attribute in _iter_mappings(attributes, f"{where} 的 attributes"):
        _validate_attribute(
            attribute,
            where,
            aggregate_index,
            dictionary_index,
            value_object_names,
            is_root=is_root,
        )


def _validate_attribute(
    attribute: Mapping[str, Any],
    where: str,
    aggregate_index: Mapping[str, Mapping[str, Any]],
    dictionary_index: Mapping[str, set[str]],
    value_object_names: set[str],
    *,
    is_root: bool,
) -> None:
    name = _require_string(attribute, "name", f"{where} 的属性")
    label = _require_string(attribute, "label", f"{where} 的属性 {name}")
    data_type = _require_string(attribute, "type", f"{where} 的属性 {name}")
    attribute_where = f"{where} 的属性 {name}({label})"

    if name in _TENANT_ATTRIBUTE_NAMES:
        _fail(f"{attribute_where}: tenant_id 由生成物 ORM 层注入，M1 模型不得显式建模（D1.03）")
    if data_type not in _ALLOWED_ATTRIBUTE_TYPES:
        _fail(f"{attribute_where}: type={data_type} 不在 PostgreSQL 方言语义类型集（D1.02）")
    _require_optional_bool(attribute, "required", attribute_where)
    _require_optional_bool(attribute, "unique", attribute_where)
    if attribute.get("unique") is True and not is_root:
        _fail(f"{attribute_where}: unique 仅对聚合根属性有效（v9 M1 §2.3.4）")
    if name == "deleted" and data_type != "Boolean":
        _fail(f"{attribute_where}: D1.05 逻辑删除约定要求 deleted 属性类型为 Boolean")

    if "concurrency" in attribute:
        concurrency = attribute["concurrency"]
        if concurrency not in _ALLOWED_CONCURRENCY:
            _fail(f"{attribute_where}: concurrency={concurrency!r} 只允许 optimistic_lock（D1.04）")

    if data_type == "Enum":
        enum_values = _require_list(attribute, "enumValues", attribute_where)
        if not enum_values or not all(isinstance(item, str) for item in enum_values):
            _fail(f"{attribute_where}: type=Enum 时 enumValues 必须是非空字符串列表")

    if data_type == "AggregateRootRef":
        target = _require_string(attribute, "targetAggregate", attribute_where)
        _require_existing_target(aggregate_index, target, attribute_where, "targetAggregate")

    if data_type == "ValueObject":
        target = _require_string(attribute, "valueObjectRef", attribute_where)
        if target not in value_object_names:
            _fail(f"{attribute_where}: valueObjectRef={target} 不存在于当前聚合 valueObjects 中（引用完整性）")

    if data_type == "DictionaryRef":
        if "enumValues" in attribute:
            _fail(f"{attribute_where}: DictionaryRef 不得同时声明 enumValues（v9 M1 §2.3.4）")
        dictionary_ref = _require_mapping(attribute, "dictionaryRef", attribute_where)
        dictionary_id = _require_string(dictionary_ref, "dictionaryId", f"{attribute_where}.dictionaryRef")
        type_code = _require_string(dictionary_ref, "typeCode", f"{attribute_where}.dictionaryRef")
        if dictionary_id not in dictionary_index:
            _fail(f"{attribute_where}: dictionaryRef.dictionaryId={dictionary_id} 不存在（引用完整性）")
        if type_code not in dictionary_index[dictionary_id]:
            _fail(f"{attribute_where}: dictionaryRef.typeCode={type_code} 不存在（引用完整性）")

    for rule in _iter_mappings(attribute.get("refRules", []), f"{attribute_where}.refRules"):
        rule_name = _require_string(rule, "name", f"{attribute_where}.refRules")
        _require_string(rule, "expression", f"属性规则 {rule_name}")
        _require_string(rule, "violationMessage", f"属性规则 {rule_name}")
        _require_enum(rule, "enforcedAt", f"属性规则 {rule_name}", _ENFORCED_AT)


def _require_existing_target(
    aggregate_index: Mapping[str, Mapping[str, Any]],
    target: str,
    where: str,
    field_name: str,
) -> None:
    if target not in aggregate_index:
        _fail(f"{where}: {field_name}={target} 不存在于 M1 aggregates 中（引用完整性）")


def _validate_unique_attribute_names(attributes: Sequence[Any], where: str) -> None:
    seen: set[str] = set()
    for attribute in _iter_mappings(attributes, f"{where} 的 attributes"):
        name = attribute.get("name")
        if name in seen:
            _fail(f"{where}: 属性 name 必须唯一: {name}")
        seen.add(str(name))


def _attribute_names(attributes: Any, where: str) -> set[str]:
    if not isinstance(attributes, list):
        _fail(f"{where}: attributes 必须是列表")
    names: set[str] = set()
    for attribute in _iter_mappings(attributes, f"{where} 的 attributes"):
        if isinstance(attribute.get("name"), str):
            names.add(attribute["name"])
    return names


def _names(items: Any, key: str, where: str) -> set[str]:
    if not isinstance(items, list):
        _fail(f"{where}: {key} 必须是列表")
    names: set[str] = set()
    for item in _iter_mappings(items, f"{where} 的 {key}"):
        if isinstance(item.get("alias"), str):
            names.add(item["alias"])
        if isinstance(item.get("name"), str):
            names.add(item["name"])
    return names


def _require_string(obj: Mapping[str, Any], key: str, where: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        _fail(f"{where}: 字段 {key} 必须是非空字符串")
    return value


def _require_enum(obj: Mapping[str, Any], key: str, where: str, allowed: set[str]) -> str:
    value = _require_string(obj, key, where)
    if value not in allowed:
        _fail(f"{where}: {key}={value} 不在允许枚举值 {sorted(allowed)}")
    return value


def _require_list(obj: Mapping[str, Any], key: str, where: str) -> list[Any]:
    value = obj.get(key)
    if not isinstance(value, list):
        _fail(f"{where}: 字段 {key} 必须是列表")
    return value


def _require_mapping(obj: Mapping[str, Any], key: str, where: str) -> dict[str, Any]:
    value = obj.get(key)
    if not isinstance(value, dict):
        _fail(f"{where}: 字段 {key} 必须是映射")
    return value


def _require_optional_bool(obj: Mapping[str, Any], key: str, where: str) -> None:
    if key in obj and not isinstance(obj[key], bool):
        _fail(f"{where}: 字段 {key} 必须是布尔值")


def _require_optional_int(obj: Mapping[str, Any], key: str, where: str) -> None:
    if key in obj and (isinstance(obj[key], bool) or not isinstance(obj[key], int)):
        _fail(f"{where}: 字段 {key} 必须是整数")


def _iter_mappings(items: Any, where: str):
    if not isinstance(items, list):
        _fail(f"{where} 必须是列表")
    for item in items:
        if not isinstance(item, dict):
            _fail(f"{where} 只能包含映射对象")
        yield item


def _fail(message: str) -> None:
    raise ModelStructureError(message)
