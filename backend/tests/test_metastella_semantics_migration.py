"""m2-minset 工单 06：Alembic 迁移生成链单测。

D11.04 纪律：迁移脚本=仅由生成器从语义包确定性产出（Alembic），版本钉语义包指纹。
首通口径：单包全量迁移；包间 diff 增量迁移挂 M2 中期。
阶段审计 B-C1 修复批：防注入（语义包=不可信输入）。
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
    assert generate_migration(_load()) == generate_migration(_load())


def test_revision_id_pinned_to_fingerprint() -> None:
    """D11.02 同构纪律：迁移版本钉语义包指纹。"""
    family = _load()
    fp = compute_package_fingerprint(family)
    assert fp in generate_migration(family), "迁移脚本未钉语义包指纹"


def test_migration_is_valid_python_with_upgrade_downgrade() -> None:
    source = generate_migration(_load())
    compile(source, "<migration>", "exec")  # 语法合法
    assert "def upgrade()" in source
    assert "def downgrade()" in source


def test_migration_body_creates_tables() -> None:
    source = generate_migration(_load())
    assert "CREATE TABLE t_book" in source
    assert "DROP TABLE IF EXISTS t_book" in source  # downgrade 面


# ---- 阶段审计 B-C1：迁移脚本防注入（语义包是不可信输入）----


class _RecordingOp:
    def __init__(self) -> None:
        self.executed: list[str] = []

    def execute(self, sql: str) -> None:
        self.executed.append(sql)


def _run_upgrade(script: str) -> _RecordingOp:
    recorder = _RecordingOp()
    ns: dict = {"op": recorder}
    exec(compile(script, "<gen-migration>", "exec"), ns)  # noqa: S102 — 受控生成脚本，正是要证它无顶层逃逸
    ns["upgrade"]()
    return recorder


def test_hostile_default_value_cannot_escape_into_python() -> None:
    """defaultValue 含三引号/换行/伪语句：只允许作为 SQL 数据存在，不得越狱成顶层 Python。"""
    family = _load()
    hostile = 'evil"""\nos.system("echo PWNED")\nimport sys\n"""'
    family["OBJECT"]["aggregates"][0]["attributes"][0]["defaultValue"] = hostile
    script = generate_migration(family)

    ns: dict = {"op": _RecordingOp()}
    exec(compile(script, "<gen-migration>", "exec"), ns)  # noqa: S102
    assert "os" not in ns and "sys" not in ns, "注入语句逃逸成了顶层代码"

    op = _run_upgrade(script)
    assert len(op.executed) == 3, f"语句数应为 3 张表，实到 {len(op.executed)}（; 切碎或注入）"
    assert all(s.lstrip().startswith("CREATE TABLE") for s in op.executed)
    assert any("PWNED" in s for s in op.executed), "敌意值应作为 DEFAULT 数据原样保留"


def test_semicolon_in_default_keeps_statement_count() -> None:
    family = _load()
    family["OBJECT"]["aggregates"][0]["attributes"][1]["defaultValue"] = "a;b;DROP TABLE x"
    op = _run_upgrade(generate_migration(family))
    assert len(op.executed) == 3
    assert any("a;b;DROP TABLE x" in s for s in op.executed)
