"""审计修复批②：租户认证/隔离关键路径行为测试（真实 sqlite 会话，非 mock）。

覆盖根因级修复：
- 根因-A：`_tenant_models` 判据错（继承的 `__abstract__` 全 True）→ do_orm_execute 注入恒空、
  读隔离整体失效。改判"有真实 mapper/表"。
- A-C1：身份存在性查询须先于租户上下文设置（否则多租户选非主租户→查不到自己→401 自锁）。
- A-C2：共享读模型写侧守卫（批量 DML + flush 对象路径）。
"""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from sqlalchemy import func, select, update

from app.core.base_schema import JWTPayloadSchema
from app.core.database import async_db_session
from app.core.dependencies import _authenticate
from app.core.security import create_access_token
from app.core.tenancy import _tenant_models, set_current_tenant
from app.modules.system.dict.model import DictTypeModel
from app.modules.system.user.model import UserModel


async def _normal_user_id() -> int:
    async with async_db_session() as db:
        uid = (
            await db.execute(select(UserModel.id).where(UserModel.is_superuser == False).limit(1))  # noqa: E712
        ).scalar()
        if uid is not None:
            return int(uid)
        with set_current_tenant(1):
            row = UserModel(username="ac1u", name="审计用户", password="x", is_superuser=False)
        db.add(row)
        await db.commit()
        return int(row.id)


async def test_tenant_models_actually_resolves_platform_models(test_client) -> None:
    names = {m.__name__ for m in _tenant_models(include_shared=True)}
    assert {"UserModel", "RoleModel", "DictTypeModel"} <= names, sorted(names)
    sel = {m.__name__ for m in _tenant_models(include_shared=False)}
    assert "DictTypeModel" not in sel  # 共享读模型由 CRUD 层负责，ORM SELECT 不注入


async def test_select_injection_filters_real_model(test_client) -> None:
    async with async_db_session() as db:
        assert (await db.execute(select(func.count()).select_from(UserModel))).scalar() >= 1
    async with async_db_session() as db:
        with set_current_tenant(999):
            rows = (await db.execute(select(UserModel))).scalars().all()
    assert rows == [], "会话租户 999 不得读到真实租户行（注入未生效=回归）"


async def test_existence_query_not_filtered_by_session_tenant(test_client) -> None:
    """A-C1：绑定到非主租户(999)的会话，用户存在性校验仍须命中（修复前=401 自锁）。"""
    uid = await _normal_user_id()
    session = {
        "session_id": "ac1",
        "user_id": uid,
        "tenant_id": 999,
        "is_super_admin": False,
        "tenant_pending": False,
        "user_status": 0,
        "user_name": "ac1u",
        "name": "审计用户",
        "permissions": [],
        "menu_ids": [],
    }
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=json.dumps(session))
    redis.ttl = AsyncMock(return_value=3600)
    redis.expire = AsyncMock(return_value=True)
    redis.set = AsyncMock(return_value=True)
    token = create_access_token(JWTPayloadSchema(sub="ac1", exp=datetime.now(UTC) + timedelta(hours=1)))
    async with async_db_session() as db:
        auth = await _authenticate(f"Bearer {token}", db, redis)
    assert auth.user.id == uid
    assert auth.tenant_id == 999


async def test_shared_model_bulk_update_blocked(test_client) -> None:
    async with async_db_session() as db:
        n = (await db.execute(select(func.count()).select_from(DictTypeModel).where(DictTypeModel.tenant_id == 1))).scalar()
        assert n > 0
    async with async_db_session() as db:
        with set_current_tenant(2):
            result = await db.execute(update(DictTypeModel).values(description="HACKED-T2"))
            await db.commit()
    assert result.rowcount == 0, f"共享模型批量 update 未锁租户（命中 {result.rowcount}）"


async def test_dict_cache_key_is_tenant_scoped(test_client) -> None:
    """A-C3：字典缓存键带租户维度，跨租户刷新不得互相污染平台桶。"""
    from app.core.tenancy import DEFAULT_TENANT_ID
    from app.modules.system.dict.service import _dict_cache_key

    with set_current_tenant(DEFAULT_TENANT_ID):
        k_platform = _dict_cache_key("sex")
    with set_current_tenant(2):
        k_t2 = _dict_cache_key("sex")
    assert k_platform != k_t2
    assert k_platform.endswith(f":{DEFAULT_TENANT_ID}:sex") and k_t2.endswith(":2:sex")
    """flush 对象路径（CRUD.update 式）写守卫：租户2 不得改平台(tenant1)字典行。"""
    async with async_db_session() as db:
        row = (await db.execute(select(DictTypeModel).where(DictTypeModel.tenant_id == 1).limit(1))).scalars().first()
        assert row is not None
    async with async_db_session() as db:
        with set_current_tenant(2):
            obj = (await db.execute(select(DictTypeModel).where(DictTypeModel.id == row.id))).scalars().first()
            assert obj is not None, "共享读应可见平台行"
            obj.description = "OBJ-HACK"
            blocked = False
            try:
                await db.commit()
            except Exception:  # noqa: BLE001
                blocked = True
                await db.rollback()
    assert blocked, "对象路径改写平台字典行未被写守卫拦截（A-C2）"
    async with async_db_session() as db:
        hacked = (await db.execute(select(func.count()).select_from(DictTypeModel).where(DictTypeModel.description == "OBJ-HACK"))).scalar()
    assert hacked == 0
