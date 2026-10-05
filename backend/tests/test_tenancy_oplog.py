"""W2·11d-iii 回归：操作日志后台写在无租户上下文（公开路由）时落默认租户，不得静默失败。"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.core.router_class as router_class_mod
from app.core.base_model import MappedBase
from app.core.tenancy import DEFAULT_TENANT_ID, current_tenant
from app.utils.import_util import ImportUtil

LOG_DATA = {
    "username": "anonymous",
    "request_path": "/api/v1/system/auth/login",
    "request_method": "POST",
    "request_payload": "{}",
    "response_code": 200,
    "response_json": "{}",
    "process_time": "10ms",
    "description": "登录",
    "request_ip": "127.0.0.1",
}


async def test_oplog_public_route_falls_back_to_default_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    ImportUtil.find_models(MappedBase)  # 确保全模型入 metadata 后建表
    async with engine.begin() as conn:
        await conn.run_sync(MappedBase.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(router_class_mod, "async_db_session", maker)

    assert current_tenant.get() is None  # 前提：无上下文
    await router_class_mod._write_operation_log_async(LOG_DATA)

    from app.modules.system.log.model import OperationLogModel

    async with maker() as session:
        rows = (await session.execute(select(OperationLogModel))).scalars().all()
    assert len(rows) == 1, "公开路由审计写入被静默吞掉"
    assert rows[0].tenant_id == DEFAULT_TENANT_ID
    await engine.dispose()
