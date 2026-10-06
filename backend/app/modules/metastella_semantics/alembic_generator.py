"""Alembic 迁移脚本生成器（D11.04：仅由生成器确定性产出；D11.02：版本钉语义包指纹）。

首通口径：单包全量建表迁移（upgrade=逐语句 op.execute，downgrade=逆序 DROP）。
包间 diff 增量迁移（D11.04 全义）=M2 中期生成链深化。

安全纪律（阶段审计 B-C1 修复）：生成器把语义包视为**不可信输入**——
每条语句经 `repr()` 作为 Python 字面量嵌入（三引号/换行/分号一律无法越狱成顶层代码），
且直接迭代结构化语句列表（不对 DDL 文本做分号切分回拼）。
"""

from __future__ import annotations

from typing import Any

from .ddl_generator import generate_ddl_statements
from .publish import compute_package_fingerprint


def _created_tables(statements: list[str]) -> list[str]:
    """从 CREATE TABLE 语句按创建顺序提取表名（downgrade 逆序删，保证与 upgrade 对称，字典表不漏删）。"""
    out: list[str] = []
    for stmt in statements:
        head = stmt.lstrip().splitlines()[0]
        if head.startswith("CREATE TABLE "):
            out.append(head[len("CREATE TABLE ") :].split(" ")[0].rstrip("(").strip())
    return out


def generate_migration(family: dict[str, Any]) -> str:
    """由语义包族确定性生成 Alembic revision 脚本文本（同内容必同输出）。"""
    fingerprint = compute_package_fingerprint(family)
    statements = generate_ddl_statements(family)
    tables = _created_tables(statements)

    body = "\n".join(f"    op.execute({stmt!r})" for stmt in statements)
    drops = "\n".join(f'    op.execute("DROP TABLE IF EXISTS {t} CASCADE")' for t in reversed(tables))

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
