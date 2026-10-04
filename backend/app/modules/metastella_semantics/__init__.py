"""MetaStella 语义引擎（元模型规范 v1 实现）。

依据：docs/03-架构/元模型规范v1.md（ADR-0039 定版）；P-13 最小集=M1/M2/M3/M5/M6/MU（D13.01）。
边界：本模块不侵入上游任何文件目录（新链独立，R-8 约束）；AI 不进编译核心（规范 §12.2）。
"""

from .errors import (
    BadSchemaVersionError,
    MissingSchemaVersionError,
    ModelFamilyInconsistencyError,
    UnknownModelTypeError,
)
from .loader import load_model_family, load_model_file
from .registry import MINIMAL_SET
from .schema_version import extract_schema_version

__all__ = [
    "load_model_family",
    "load_model_file",
    "extract_schema_version",
    "MINIMAL_SET",
    "BadSchemaVersionError",
    "MissingSchemaVersionError",
    "ModelFamilyInconsistencyError",
    "UnknownModelTypeError",
]
