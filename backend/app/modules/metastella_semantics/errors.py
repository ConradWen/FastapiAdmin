"""防御级错误族（§12.2：error 阻断发布；全部可机检）。"""

from __future__ import annotations


class SemanticSchemaError(Exception):
    """语义包族任何阻断级错误的基类。"""


class MissingSchemaVersionError(SemanticSchemaError):
    """D11.01：元文件缺 schema_version 首字段。"""


class BadSchemaVersionError(SemanticSchemaError):
    """D11.01：schema_version 语义错误。"""


class ModelFamilyInconsistencyError(SemanticSchemaError):
    """D11.01：语义包族内 schema_version 不一致（发布单元=语义包，版本=包级）。"""


class UnknownModelTypeError(SemanticSchemaError):
    """§0.2：model_type 不在九类注册表中。"""


class ModelStructureError(SemanticSchemaError):
    """各 §章结构级错误基类（第二章起细化为具体拦截）。"""


class SemanticPackageError(SemanticSchemaError):
    """语义包发布状态机错误基类（D11.02/F-3）。"""


class ModelPackageAlreadyPublishedError(SemanticPackageError):
    """同指纹语义包已发布（F-3 内容不可变——重发布须出新版本）。"""
