"""工单 12（B-C3/D1.07 落地）：字典表物化 + 业务列存文字 code + 复合外键；Enum 合成域；AggregateRootRef FK。

判据用**真实 PostgreSQL 执行**（非字符串断言）：把生成的 DDL 跑进一个临时 schema，
证明① 合法文字码能插入、② 非法码被外键拦下、③ 中文 label 存得下（旧 int 列做不到）。
"""

import os

import pytest

from app.modules.metastella_semantics import generate_ddl_statements, load_model_family
from app.modules.metastella_semantics.ddl_generator import generate_ddl

PACKAGE = os.path.join(os.path.dirname(__file__), "..", "semantic_packages", "library_smoke")

DSN = os.environ.get(
    "METASTELLA_LEDGER_DSN", "postgresql://metastella:metastella_dev@127.0.0.1:55432/metastella"
)


def _family() -> dict:
    return load_model_family(PACKAGE, manifest_name="manifest.yaml")


def _pg_available() -> bool:
    try:
        import psycopg

        with psycopg.connect(DSN, connect_timeout=3):
            return True
    except Exception:  # noqa: BLE001 — 探测失败即判不可达
        return False


pytestmark = pytest.mark.skipif(not _pg_available(), reason="PostgreSQL 不可达")


@pytest.fixture()
def schema():
    """在临时 schema 里执行生成 DDL，测试后 DROP。"""
    import psycopg

    name = "audit12"
    with psycopg.connect(DSN) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {name} CASCADE")
        conn.execute(f"CREATE SCHEMA {name}")
        conn.execute(f"SET search_path TO {name}")
        for stmt in generate_ddl_statements(_family()):
            conn.execute(f"SET search_path TO {name}")
            conn.execute(stmt)
        conn.commit()
    yield name
    with psycopg.connect(DSN) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {name} CASCADE")
        conn.commit()


def _run(conn, sql):
    conn.execute("SET search_path TO audit12")
    return conn.execute(sql)


def _fetch(conn, sql):
    conn.execute("SET search_path TO audit12")
    return conn.execute(sql).fetchone()


def test_dictionary_tables_materialized_and_fk_enforced(schema) -> None:
    import psycopg

    with psycopg.connect(DSN) as conn:
        # ① 合法文字码（BOOK_CATEGORY/LITERATURE 已在 t_dict_data 种子中）→ 可插入
        _run(
            conn,
            "INSERT INTO t_book (id, book_no, title, category_code, status, price, tenant_id) "
            "VALUES (1,'B1','三体','LITERATURE','在架',59.0,1)",
        )
        conn.commit()
        got = _fetch(conn, "SELECT category_code, status FROM t_book WHERE id=1")
        assert got == ("LITERATURE", "在架")  # 存的是文字，不是 int

    with psycopg.connect(DSN) as conn:
        # ② 非法分类码 → 外键必须拦下
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            _run(
                conn,
                "INSERT INTO t_book (id, book_no, title, category_code, status, price, tenant_id) "
                "VALUES (2,'B2','x','NOT_A_CATEGORY','在架',1.0,1)",
            )
    with psycopg.connect(DSN) as conn:
        # ③ 非法枚举值 → 合成枚举域外键同样拦下
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            _run(
                conn,
                "INSERT INTO t_book (id, book_no, title, category_code, status, price, tenant_id) "
                "VALUES (3,'B3','x','LITERATURE','银河状态',1.0,1)",
            )


def test_labels_are_storable_and_editable(schema) -> None:
    """v9 设计初衷：label 可改且不影响业务数据（旧 int 列根本存不了中文 label）。"""
    import psycopg

    with psycopg.connect(DSN) as conn:
        _run(
            conn,
            "INSERT INTO t_book (id, book_no, title, category_code, status, price, tenant_id) "
            "VALUES (1,'B1','三体','LITERATURE','在架',59.0,1)",
        )
        conn.commit()
        label = _fetch(conn, "SELECT label FROM t_dict_data WHERE type_code='BOOK_CATEGORY' AND code='LITERATURE'")
        assert label is not None and label[0] == "文学"
        _run(conn, "UPDATE t_dict_data SET label='文学作品' WHERE type_code='BOOK_CATEGORY' AND code='LITERATURE'")
        conn.commit()
        still = _fetch(conn, "SELECT title FROM t_book WHERE id=1")
        assert still[0] == "三体"  # 改 label 不动业务存量行


def test_aggregate_ref_has_fk(schema) -> None:
    """AggregateRootRef→bigint 但缺 FK（评审 B-C3 附带）：非法引用应被拦。"""
    import psycopg

    with psycopg.connect(DSN) as conn:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            _run(
                conn,
                "INSERT INTO t_borrow_record (id, borrow_no, book_id, reader_id, borrow_date, due_date, borrow_status, tenant_id) "
                "VALUES (1,'JY1',9999,1,'2026-01-01','2026-01-31','借出中',1)",
            )


def test_ddl_still_deterministic() -> None:
    assert generate_ddl(_family()) == generate_ddl(_family())
    stmts = generate_ddl_statements(_family())
    assert any(s.startswith("CREATE TABLE t_dict_type") for s in stmts)
    assert any(s.startswith("CREATE TABLE t_dict_data") for s in stmts)
