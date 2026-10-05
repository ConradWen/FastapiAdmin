"""W2·11d-v 多租户登录决议 + select-tenant 会话改写（纯逻辑单测；端点/DB 接线随实现）。

规格（REQUIREMENTS v3.6）：单租户直落正式会话；多租户临时会话(tenant_pending) 仅可选租户；
select-tenant 校验归属后改写会话 tenant_id 并清除 pending。
"""

import pytest

from app.core.tenancy import resolve_login_tenant
from app.modules.system.auth.service import LoginService


@pytest.mark.parametrize(
    ("is_superuser", "tenant_ids", "expected"),
    [
        (True, set(), (None, False)),  # 超管不受租户绑定
        (True, {2, 3}, (None, False)),
        (False, {1}, (1, False)),  # 单租户直落
        (False, {2, 5}, (None, True)),  # 多租户临时会话
        (False, set(), (None, True)),  # 无租户=fail-closed 也走 pending
    ],
)
def test_resolve_login_tenant(is_superuser: bool, tenant_ids: set[int], expected: tuple[int | None, bool]) -> None:
    assert resolve_login_tenant(is_superuser=is_superuser, tenant_ids=tenant_ids) == expected


def test_apply_selected_tenant_clears_pending() -> None:
    session_dict = {"tenant_id": None, "tenant_pending": True}
    LoginService._apply_selected_tenant(session_dict, tenant_id=5, allowed={2, 5})
    assert session_dict["tenant_id"] == 5
    assert session_dict["tenant_pending"] is False


def test_apply_selected_tenant_rejects_foreign_tenant() -> None:
    session_dict = {"tenant_id": None, "tenant_pending": True}
    with pytest.raises(Exception, match="租户"):
        LoginService._apply_selected_tenant(session_dict, tenant_id=99, allowed={2, 5})
