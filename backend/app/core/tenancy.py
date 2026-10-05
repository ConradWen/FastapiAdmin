"""W2·工单 11a 租户核心：上下文 + TenantMixin + 写侧 fail-closed + 读侧过滤 helper。

REQUIREMENTS v3.6：`tenant_id` 行级隔离；超管不受过滤；ORM `do_orm_execute` 全自动注入=11b，
本批提供显式 `apply_tenant_filter`（CRUD 层二次确认的同语义入口）。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from sqlalchemy import ForeignKey, Integer, event
from sqlalchemy.orm import Mapped, Session, mapped_column, with_loader_criteria

current_tenant: ContextVar[int | None] = ContextVar("current_tenant", default=None)
current_superadmin: ContextVar[bool] = ContextVar("current_superadmin", default=False)

# 默认租户 id（种子/迁移回填/超管未指定归属的落点，三处同一语义）
DEFAULT_TENANT_ID = 1


class TenantMixin:
    """租户列（写侧由 init 事件自动填充；读侧配合 11b 全自动注入）。

    server_default='1' 使「给非空表加 NOT NULL 列」可行（存量行回填默认租户）；
    FK use_alter 让 create_all/迁移在两张表都在后再加约束（对齐 base_model dept_id 范式）。
    """

    tenant_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("platform_tenant.id", ondelete="RESTRICT", use_alter=True),
        nullable=False,
        server_default="1",
        index=True,
    )


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
            # 超管跨租户操作未指定归属 → 落默认租户（平台「租户选择器」=11d-ii 开通流程）
            tenant_id = DEFAULT_TENANT_ID
        else:
            raise RuntimeError("写入租户资源缺少租户上下文（NFR-5 fail-closed）")
    target.__dict__["tenant_id"] = tenant_id


def _tenant_subclasses(cls: type) -> list[type]:
    subs: list[type] = []
    for sub in cls.__subclasses__():
        if not getattr(sub, "__abstract__", False) and not getattr(sub, "__platform_data_shared__", False):
            subs.append(sub)
        subs.extend(_tenant_subclasses(sub))
    return subs


@event.listens_for(Session, "do_orm_execute")
def _inject_tenant_criteria(execute_state: Any) -> None:
    """读/改/删全自动注入（11b）：SELECT=with_loader_criteria（含关系）；
    ORM DML（update/delete）=对目标表显式追加 WHERE。超管/无上下文/共享读模型放行。"""
    tid = current_tenant.get()
    if tid is None or current_superadmin.get():
        return
    stmt = execute_state.statement
    if execute_state.is_select:
        for model in _tenant_subclasses(TenantMixin):
            stmt = stmt.options(with_loader_criteria(model, model.tenant_id == tid, include_aliases=True))
    elif execute_state.is_update or execute_state.is_delete:
        table_name = getattr(getattr(stmt, "table", None), "name", None)
        for model in _tenant_subclasses(TenantMixin):
            if table_name is not None and getattr(model, "__tablename__", None) == table_name:
                stmt = stmt.where(model.tenant_id == tid)
                break
    else:
        return
    execute_state.statement = stmt
