"""MetaStella 语义引擎（元模型规范 v1 实现）。

依据：docs/03-架构/元模型规范v1.md（ADR-0039 定版）；P-13 最小集=M1/M2/M3/M5/M6/MU（D13.01）。
边界：本模块不侵入上游任何文件目录（新链独立，R-8 约束）；AI 不进编译核心（规范 §12.2）。
"""

from .alembic_generator import generate_migration
from .app_generator import generate_app_bundle
from .ddl_generator import generate_ddl, generate_ddl_statements
from .errors import (
    BadSchemaVersionError,
    MissingSchemaVersionError,
    ModelFamilyInconsistencyError,
    ModelStructureError,
    SemanticPackageError,
    UnknownModelTypeError,
)
from .family_checks import FamilyCheckResult, check_family
from .loader import load_model_family, load_model_file
from .m2_validator import endpoint_from_behavior_id
from .publish import ModelPackageAlreadyPublishedError, compute_package_fingerprint, publish_package
from .registry import MINIMAL_SET
from .schema_version import extract_schema_version
from .validator import validate_model

__all__ = [
    "load_model_family",
    "load_model_file",
    "extract_schema_version",
    "validate_model",
    "compute_package_fingerprint",
    "publish_package",
    "generate_ddl",
    "generate_ddl_statements",
    "generate_migration",
    "generate_app_bundle",
    "endpoint_from_behavior_id",
    "check_family",
    "FamilyCheckResult",
    "MINIMAL_SET",
    "BadSchemaVersionError",
    "MissingSchemaVersionError",
    "ModelFamilyInconsistencyError",
    "ModelStructureError",
    "SemanticPackageError",
    "ModelPackageAlreadyPublishedError",
    "UnknownModelTypeError",
]
