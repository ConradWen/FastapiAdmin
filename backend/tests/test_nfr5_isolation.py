"""W2·11e NFR-5 全查询路径隔离专项：跨租户读/写不得越权（真实 ORM 会话，非 mock）。

覆盖 §12.1 之外的**读隔离主命题**：
- SELECT 经 do_orm_execute 自动注入本租户；count/select_from 同样生效
- UPDATE/DELETE 经 DML 注入锁定本租户
- 超管放行全量
- 共享读模型（Dict 类）ORM 层跳过，CRUD 层补 `本租户 OR 默认租户`（tenant_read_condition）
"""

from __future__ import annotations

import pytest
from sqlalchemy import Integer, MetaData, String, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.tenancy import (
    TenantMixin,
    set_current_tenant,
    tenant_read_condition,
)


class Base(DeclarativeBase):
    metadata = MetaData()


class TenantStub(Base):
    __tablename__ = "platform_tenant"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), default="t")


class Doc(Base, TenantMixin):
    __tablename__ = "t_doc_test"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(32))


class SharedDoc(Base, TenantMixin):
    """共享读模型样例（如字典）：ORM 层跳过过滤，CRUD 层补 本租户 OR 默认租户。"""

    __platform_data_shared__ = True
    __tablename__ = "t_shared_doc_test"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(32))


class NotTenant(Base):
    __tablename__ = "t_plain_test"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)


@pytest.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def _seed(session: AsyncSession) -> None:
    with set_current_tenant(1):
        session.add_all([Doc(title="a1"), Doc(title="a2")])
    with set_current_tenant(2):
        session.add(Doc(title="b1"))
    await session.commit()


async def _seed_shared(session: AsyncSession) -> None:
    with set_current_tenant(1):
        session.add(SharedDoc(title="platform"))
    with set_current_tenant(2):
        session.add(SharedDoc(title="mine"))
    with set_current_tenant(3):
        session.add(SharedDoc(title="other"))
    await session.commit()


async def test_select_isolated(session: AsyncSession) -> None:
    await _seed(session)
    with set_current_tenant(1):
        titles = sorted(d.title for d in (await session.execute(select(Doc))).scalars())
        assert titles == ["a1", "a2"]
    with set_current_tenant(2):
        titles = [d.title for d in (await session.execute(select(Doc))).scalars()]
        assert titles == ["b1"]


async def test_count_isolated(session: AsyncSession) -> None:
    await _seed(session)
    with set_current_tenant(1):
        n = (await session.execute(select(func.count()).select_from(Doc))).scalar()
        assert n == 2


async def test_update_scoped_to_tenant(session: AsyncSession) -> None:
    await _seed(session)
    with set_current_tenant(1):
        await session.execute(update(Doc).values(title="X"))
        await session.commit()
    with set_current_tenant(None, is_superadmin=True):
        got = {d.title for d in (await session.execute(select(Doc))).scalars()}
        assert got == {"X", "b1"}  # 租户1 全改；租户2 不受越权影响


async def test_delete_scoped_to_tenant(session: AsyncSession) -> None:
    await _seed(session)
    with set_current_tenant(2):
        await session.execute(delete(Doc))
        await session.commit()
    with set_current_tenant(None, is_superadmin=True):
        assert (await session.execute(select(func.count()).select_from(Doc))).scalar() == 2


async def test_superadmin_sees_all(session: AsyncSession) -> None:
    await _seed(session)
    with set_current_tenant(None, is_superadmin=True):
        assert (await session.execute(select(func.count()).select_from(Doc))).scalar() == 3


async def test_shared_read_seen_platform_plus_own(session: AsyncSession) -> None:
    await _seed_shared(session)
    with set_current_tenant(2):
        cond = tenant_read_condition(SharedDoc)
        titles = sorted(
            d.title for d in (await session.execute(select(SharedDoc).where(cond))).scalars()
        )
        assert titles == ["mine", "platform"]  # 他租户(3)行不可见，平台租户(1)可见


async def test_nonshared_read_strict_current(session: AsyncSession) -> None:
    await _seed(session)
    with set_current_tenant(2):
        cond = tenant_read_condition(Doc)  # CRUD 二次确认与 ORM 注入同语义
        titles = [d.title for d in (await session.execute(select(Doc).where(cond))).scalars()]
        assert titles == ["b1"]


def test_condition_none_for_superadmin_and_plain() -> None:
    with set_current_tenant(None, is_superadmin=True):
        assert tenant_read_condition(Doc) is None
    assert tenant_read_condition(NotTenant) is None  # 非租户模型无条件
