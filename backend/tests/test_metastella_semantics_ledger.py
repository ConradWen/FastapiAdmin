"""m2-minset W2a：发布台账持久化单测（F-3 跨重启；metastella-pg 直连）。

无 PG 可达时整文件 skip（CI 无库环境不假绿）。
"""

import os

import pytest

DSN = os.environ.get("METASTELLA_LEDGER_DSN", "postgresql://metastella:metastella_dev@127.0.0.1:55432/metastella")

pytest.importorskip("psycopg")

import psycopg  # noqa: E402

from app.modules.metastella_semantics import (  # noqa: E402
    ModelPackageAlreadyPublishedError,
    compute_package_fingerprint,
    load_model_family,
    publish_package,
)
from app.modules.metastella_semantics.publish_ledger import (  # noqa: E402
    ensure_ledger,
    is_published,
    record_publish,
)

try:
    _probe = psycopg.connect(DSN, connect_timeout=3)
    _probe.close()
    PG_OK = True
except Exception:  # noqa: BLE001
    PG_OK = False

pytestmark = pytest.mark.skipif(not PG_OK, reason="metastella-pg 不可达（127.0.0.1:55432）")


@pytest.fixture(scope="module")
def pkg():
    from pathlib import Path

    d = Path(__file__).parents[1] / "semantic_packages" / "library_smoke"
    return load_model_family(d, manifest_name="manifest.yaml")


@pytest.fixture()
def conn():
    c = psycopg.connect(DSN)
    ensure_ledger(c)
    c.execute("DELETE FROM metastella_publish_ledger WHERE package_name LIKE 'w2a_test_%'")
    c.commit()
    yield c
    c.close()


def test_record_then_conflict_f3(conn, pkg) -> None:
    record = publish_package(pkg, package_name="w2a_test_f3")
    fp = record["fingerprint"]
    record_publish(conn, record)
    assert is_published(conn, "w2a_test_f3", fp)
    with pytest.raises(ModelPackageAlreadyPublishedError):
        record_publish(conn, record)


def test_ledger_survives_new_connection(conn, pkg) -> None:
    """F-3 跨重启面：新连接读台账即判重（进程内注册表失忆不再是漏口）。"""
    record = publish_package(pkg, package_name="w2a_test_restart")
    record_publish(conn, record)
    conn.commit()
    with psycopg.connect(DSN) as fresh:
        assert is_published(fresh, "w2a_test_restart", record["fingerprint"])


def test_publish_package_wires_ledger_when_given(conn, pkg) -> None:
    record = publish_package(pkg, package_name="w2a_test_wire", ledger_conn=conn)
    assert compute_package_fingerprint(pkg) == record["fingerprint"]
    assert is_published(conn, "w2a_test_wire", record["fingerprint"])
    with pytest.raises(ModelPackageAlreadyPublishedError):
        publish_package(pkg, package_name="w2a_test_wire", ledger_conn=conn)
