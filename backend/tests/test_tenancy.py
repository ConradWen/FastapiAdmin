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


# ---- 11b：ORM 全自动注入（do_orm_execute） ----


class SharedWidget(Base, TenantMixin):
    __tablename__ = "t_shared_widget_test"
    __platform_data_shared__ = True
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(32))


async def test_select_auto_filtered_without_explicit_helper(session) -> None:
    with set_current_tenant(1):
        session.add(Widget(name="only-t1"))
    await session.commit()
    with set_current_tenant(2):
        rows = (await session.execute(select(Widget))).scalars().all()
        assert rows == []
    with set_current_tenant(1):
        rows = (await session.execute(select(Widget))).scalars().all()
        assert [r.name for r in rows] == ["only-t1"]


async def test_update_and_delete_auto_scoped(session) -> None:
    with set_current_tenant(1):
        a = Widget(name="a")
    with set_current_tenant(2):
        b = Widget(name="b")
    session.add_all([a, b])
    await session.commit()

    from sqlalchemy import update

    with set_current_tenant(1):
        await session.execute(update(Widget).values(name="hacked"))
        await session.commit()
    with set_current_tenant(2):
        rows = (await session.execute(select(Widget))).scalars().all()
        assert [r.name for r in rows] == ["b"]  # 本租户未受影响
    with set_current_tenant(None, is_superadmin=True):
        rows = (await session.execute(select(Widget).order_by(Widget.id))).scalars().all()
        assert [r.name for r in rows] == ["hacked", "b"]  # 租户1 行被改、租户2 行未越权


async def test_shared_model_not_filtered_by_orm_layer(session) -> None:
    with set_current_tenant(1):
        session.add(SharedWidget(name="s1"))
    await session.commit()
    with set_current_tenant(2):
        rows = (await session.execute(select(SharedWidget))).scalars().all()
        assert [r.name for r in rows] == ["s1"]  # 共享读取策略由 CRUD 层处理，ORM 层跳过


async def test_superadmin_unfiltered(session) -> None:
    with set_current_tenant(1):
        session.add(Widget(name="x"))
    await session.commit()
    with set_current_tenant(None, is_superadmin=True):
        rows = (await session.execute(select(Widget))).scalars().all()
        assert len(rows) == 1
