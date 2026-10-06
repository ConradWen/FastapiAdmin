"""工单 A-C4：per-tenant 复合唯一（REQUIREMENTS §21.4）。

真实 sqlite create_all 证明：
- 两个租户可用相同 role.code / dept.code / dict_type.dict_type；
- 同租户内重复被 DB 唯一约束拦下；
- 复合唯一键生效（不是全局唯一）。
"""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.base_model import MappedBase
from app.core.tenancy import set_current_tenant
from app.modules.system.dept.model import DeptModel
from app.modules.system.dict.model import DictTypeModel
from app.modules.system.role.model import RoleModel
from app.utils.import_util import ImportUtil


@pytest.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    ImportUtil.find_models(MappedBase)
    async with engine.begin() as conn:
        await conn.run_sync(MappedBase.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


def _role(tenant: int, code: str) -> RoleModel:
    with set_current_tenant(tenant):
        return RoleModel(name=f"角色{code}", code=code, status=0)


async def test_role_code_unique_per_tenant(session: AsyncSession) -> None:
    session.add_all([_role(1, "admin"), _role(2, "admin")])  # 跨租户同码 OK
    await session.commit()
    session.add(_role(1, "admin"))  # 同租户重复 → 违反复合唯一
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_dept_code_unique_per_tenant(session: AsyncSession) -> None:
    def dept(t: int, c: str) -> DeptModel:
        with set_current_tenant(t):
            return DeptModel(name=f"部门{c}", code=c, status=0)

    session.add_all([dept(1, "D1"), dept(2, "D1")])
    await session.commit()
    session.add(dept(1, "D1"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_dict_type_unique_per_tenant(session: AsyncSession) -> None:
    def dt(t: int, code: str) -> DictTypeModel:
        with set_current_tenant(t):
            return DictTypeModel(dict_name=f"名{code}", dict_type=code, status=0)

    session.add_all([dt(1, "sex"), dt(2, "sex")])
    await session.commit()
    session.add(dt(1, "sex"))
    with pytest.raises(IntegrityError):
        await session.commit()
