"""W2·工单 11a 租户核心：上下文 + TenantMixin + 写侧 fail-closed + 读侧过滤 helper。

REQUIREMENTS v3.6：`tenant_id` 行级隔离；超管不受过滤；ORM `do_orm_execute` 全自动注入=11b，
本批提供显式 `apply_tenant_filter`（CRUD 层二次确认的同语义入口）。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from sqlalchemy import Integer, event
from sqlalchemy.orm import Mapped, mapped_column

current_tenant: ContextVar[int | None] = ContextVar("current_tenant", default=None)
current_superadmin: ContextVar[bool] = ContextVar("current_superadmin", default=False)


class TenantMixin:
    """租户列（写侧由 before_flush 事件自动填充；读侧配合 apply_tenant_filter）。"""

    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)


@contextmanager
def set_current_tenant(tenant_id: int | None, *, is_superadmin: bool = False) -> Iterator[None]:
    """设置当前租户上下文（FastAPI 依赖/服务层入口用）。"""
    tok_t = current_tenant.set(tenant_id)
    tok_s = current_superadmin.set(is_superadmin)
    try:
        yield
    finally:
        current_tenant.reset(tok_t)
        current_superadmin.reset(tok_s)


def apply_tenant_filter(stmt: Any, model: type) -> Any:
    """读侧过滤：超管或无上下文放行，否则追加 `WHERE tenant_id = 当前租户`。"""
    tenant_id = current_tenant.get()
    if tenant_id is None or current_superadmin.get():
        return stmt
    return stmt.where(model.tenant_id == tenant_id)


@event.listens_for(TenantMixin, "init", propagate=True)
def _fill_tenant_on_init(target: TenantMixin, args: Any, kwargs: Any) -> None:
    """写侧 fail-closed：构造即捕获租户上下文（构造发生在请求上下文内，add/commit 可延后）。"""
    if getattr(target, "tenant_id", None) is not None:
        return
    tenant_id = current_tenant.get()
    if tenant_id is None:
        if current_superadmin.get():
            raise RuntimeError("超管写入租户资源必须显式指定 tenant_id")
        raise RuntimeError("写入租户资源缺少租户上下文（NFR-5 fail-closed）")
    target.__dict__["tenant_id"] = tenant_id
