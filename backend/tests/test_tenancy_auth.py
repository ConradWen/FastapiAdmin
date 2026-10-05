"""W2·工单 11c：Auth 链租户面（session claims + _authenticate pending 403 + ContextVar 绑定）。

灰度门 settings.TENANT_ENFORCE：off（默认，11d 挂列回填前）pending 不拦截只留痕；on 才 403。
select-tenant 端点随 platform_tenant 表（11d）落地。
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.common.enums import RET  # noqa: F401 — 断言面备用
from app.config.setting import settings
from app.core.base_schema import JWTPayloadSchema
from app.core.dependencies import _authenticate
from app.core.exceptions import CustomException
from app.core.security import create_access_token
from app.modules.system.auth.service import LoginService


def _user(*, tenant_id=None, is_superuser=False) -> SimpleNamespace:
    kw = {
        "id": 1,
        "is_superuser": is_superuser,
        "status": 0,
        "name": "u",
        "username": "u",
        "dept_id": None,
        "mobile": None,
        "email": None,
        "gender": None,
        "avatar": None,
        "last_login": None,
    }
    kw["tenant_id"] = tenant_id
    return SimpleNamespace(**kw)


def _session_dict(*, tenant_id=None, is_superuser=False) -> dict:
    return LoginService._build_session_dict(
        user=_user(tenant_id=tenant_id, is_superuser=is_superuser),
        session_id="s-1",
        permissions=[],
        menu_ids=[],
        request_ip="127.0.0.1",
        login_location=None,
        ua_result=MagicMock(os=MagicMock(family="t"), user_agent=MagicMock(family="b")),
        login_type="PC",
    )


def test_session_dict_carries_tenant_claims() -> None:
    s = _session_dict(tenant_id=7)
    assert s["tenant_id"] == 7
    assert s["tenant_pending"] is False
    assert s["is_super_admin"] is False


def test_session_dict_user_without_tenant_is_pending() -> None:
    s = _session_dict(tenant_id=None)
    assert s["tenant_id"] is None
    assert s["tenant_pending"] is True


def test_session_dict_superuser_never_pending() -> None:
    s = _session_dict(tenant_id=None, is_superuser=True)
    assert s["tenant_pending"] is False


def _fake_db(user_obj: object):
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = user_obj
    db.execute.return_value = result
    return db


def _fake_redis(session_payload: dict):
    import json

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=json.dumps(session_payload))
    redis.ttl = AsyncMock(return_value=3600)
    redis.delete = AsyncMock()
    redis.set = AsyncMock()
    redis.expire = AsyncMock()
    return redis


def _token() -> str:
    return create_access_token(
        JWTPayloadSchema(sub="s-1", exp=datetime.now(UTC) + timedelta(minutes=5))
    )


async def test_pending_session_blocked_when_enforce_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TENANT_ENFORCE", True)
    session = _session_dict(tenant_id=None)
    with pytest.raises(CustomException) as exc:
        await _authenticate(_token(), _fake_db(_user()), _fake_redis(session))
    assert "租户" in exc.value.msg


async def test_pending_session_passes_when_enforce_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TENANT_ENFORCE", False)
    session = _session_dict(tenant_id=None)
    auth = await _authenticate(_token(), _fake_db(_user()), _fake_redis(session))
    assert auth.tenant_pending is True
    assert auth.tenant_id is None


async def test_normal_session_binds_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TENANT_ENFORCE", True)
    session = _session_dict(tenant_id=7)
    auth = await _authenticate(_token(), _fake_db(_user(tenant_id=7)), _fake_redis(session))
    assert auth.tenant_id == 7
    assert auth.tenant_pending is False
