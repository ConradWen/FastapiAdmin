"""W2·工单 11a 租户核心（TenantMixin+上下文+写侧 fail-closed+读侧过滤 helper）。

REQUIREMENTS v3.6：tenant_id 行级隔离；超管不受过滤；ORM 事件自动注入留 11b。
"""

import pytest
from sqlalchemy import Integer, MetaData, String, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.tenancy import (
    TenantMixin,
    apply_tenant_filter,
    current_tenant,
    set_current_tenant,
)


class Base(DeclarativeBase):
    metadata = MetaData()


class Widget(Base, TenantMixin):
    __tablename__ = "t_widget_test"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(32))


@pytest.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def test_write_requires_tenant_context(session) -> None:
    with pytest.raises(RuntimeError, match="租户"):
        session.add(Widget(name="ghost"))
        await session.flush()


async def test_auto_fill_and_filter(session) -> None:
    with set_current_tenant(1):
        session.add(Widget(name="a1"))
        session.add(Widget(name="a2"))
    with set_current_tenant(2):
        session.add(Widget(name="b1"))
    await session.commit()

    from sqlalchemy import select

    with set_current_tenant(2):
        rows = (await session.execute(apply_tenant_filter(select(Widget), Widget))).scalars().all()
        assert sorted(r.name for r in rows) == ["b1"]

    with set_current_tenant(1):
        rows = (await session.execute(apply_tenant_filter(select(Widget), Widget))).scalars().all()
        assert sorted(r.name for r in rows) == ["a1", "a2"]


async def test_superadmin_sees_all(session) -> None:
    with set_current_tenant(1):
        session.add(Widget(name="t1"))
    await session.commit()
    with set_current_tenant(None, is_superadmin=True):
        rows = (await session.execute(select(Widget))).scalars().all()
        assert len(rows) == 1
        q = apply_tenant_filter(select(Widget), Widget)
        rows2 = (await session.execute(q)).scalars().all()
        assert len(rows2) == 1


def test_context_var_default_none() -> None:
    assert current_tenant.get() is None
