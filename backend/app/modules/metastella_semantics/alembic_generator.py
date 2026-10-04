"""Alembic 迁移脚本生成器（D11.04：仅由生成器确定性产出；D11.02：版本钉语义包指纹）。

首通口径：单包全量建表迁移（upgrade=执行 generate_ddl 产物，downgrade=逆序 DROP）。
包间 diff 增量迁移（D11.04 全义）=M2 中期生成链深化。
"""

from __future__ import annotations

from typing import Any

from .ddl_generator import generate_ddl
from .publish import compute_package_fingerprint


def generate_migration(family: dict[str, Any]) -> str:
    """由语义包族确定性生成 Alembic revision 脚本文本。

    同内容必同输出：DDL 与 downgrade 均按聚合 alias 显式排序；revision id=指纹前 12 位。
    """
    fingerprint = compute_package_fingerprint(family)
    ddl = generate_ddl(family)
    tables = [
        line.split("CREATE TABLE ")[1].split(" (")[0]
        for line in ddl.splitlines()
        if line.startswith("CREATE TABLE ")
    ]
    drops = "\n".join(f'    op.execute("DROP TABLE IF EXISTS {t} CASCADE")' for t in reversed(tables))
    body = "\n".join(f'    op.execute("""{stmt.strip()}""")' for stmt in ddl.split(";") if stmt.strip())

    return f'''"""MetaStella 生成迁移——语义包 {fingerprint[:12]}（D11.02 钉指纹；D11.04 生成器产物）"""

revision = "{fingerprint[:12]}"
down_revision = None
branch_labels = None
depends_on = None

fingerprint = "{fingerprint}"


def upgrade() -> None:
{body}


def downgrade() -> None:
{drops}
'''
