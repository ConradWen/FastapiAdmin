"""m2-minset 工单 06：Alembic 迁移生成链首通单测（TDD RED 阶段）。

D11.04 纪律：迁移脚本=仅由生成器从语义包 diff 确定性产出（Alembic），版本钉语义包指纹。
首通口径：单包全量迁移（建表体）确定性可复算；包间 diff 增量迁移挂 M2 中期。
"""

from pathlib import Path

from app.modules.metastella_semantics import (
    compute_package_fingerprint,
    generate_migration,
    load_model_family,
)

PACKAGE = Path(__file__).parents[1] / "semantic_packages" / "library_smoke"
MANIFEST = "manifest.yaml"


def _load() -> dict:
    return load_model_family(PACKAGE, manifest_name=MANIFEST)


def test_same_package_generates_identical_migration() -> None:
    """D11.04 确定性：同包 N 次生成字节级一致。"""
    m1 = generate_migration(_load())
    m2 = generate_migration(_load())
    assert m1 == m2


def test_revision_id_pinned_to_fingerprint() -> None:
    """D11.02 同构纪律：迁移版本钉语义包指纹。"""
    family = _load()
    fp = compute_package_fingerprint(family)
    revision = generate_migration(family)
    assert fp in revision, "迁移脚本未钉语义包指纹"


def test_migration_is_valid_python_with_upgrade_downgrade() -> None:
    source = generate_migration(_load())
    compile(source, "<migration>", "exec")  # 语法合法
    assert "def upgrade()" in source
    assert "def downgrade()" in source


def test_migration_body_creates_tables() -> None:
    source = generate_migration(_load())
    assert "CREATE TABLE t_book" in source
    assert "DROP TABLE IF EXISTS t_book" in source  # downgrade 面
