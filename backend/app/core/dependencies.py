import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, Request, WebSocket
from redis.asyncio.client import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import RET, RedisInitKeyConfig
from app.config.setting import settings
from app.core.base_schema import AuthSchema, CoreUserSchema
from app.core.database import async_db_session
from app.core.exceptions import CustomException
from app.core.logger import logger
from app.core.redis_crud import RedisCURD
from app.core.security import OAuth2Schema, decode_access_token
from app.core.tenancy import current_superadmin, current_tenant


async def db_getter() -> AsyncGenerator[AsyncSession, None]:
    """数据库会话 — 请求级生命周期管理。

    一个 HTTP 请求内所有 SQL 共享同一个事务：要么全成功，要么全失败。
    读操作也走这个事务（牺牲一点 MVCC 隔离换取读已写一致性）。
    """
    async with async_db_session() as session, session.begin():
        yield session


async def redis_getter(request: Request) -> Redis:
    """获取Redis连接

    参数:
    - request (Request): 请求对象

    返回:
    - Redis: Redis连接
    """
    return request.app.state.redis


async def get_current_user(
    db: AsyncSession = Depends(db_getter),
    redis: Redis = Depends(redis_getter),
    token: str = Depends(OAuth2Schema),
) -> AuthSchema:
    """获取当前用户"""
    return await _authenticate(token, db, redis)


async def get_current_user_allow_pending(
    db: AsyncSession = Depends(db_getter),
    redis: Redis = Depends(redis_getter),
    token: str = Depends(OAuth2Schema),
) -> AuthSchema:
    """临时(pending)会话专用：仅 select-tenant 等极少数端点使用（REQUIREMENTS v3.6）。"""
    return await _authenticate(token, db, redis, allow_pending=True)


WS_TOKEN_SUBPROTOCOL = "access_token"


def get_websocket_token(websocket: WebSocket) -> tuple[str | None, str | None]:
    """解析 WebSocket 握手携带的令牌。

    优先读取 Sec-WebSocket-Protocol 中的 "access_token.<jwt>"：令牌不出现在 URL 中，
    不会进入网关/服务的 access log。小程序等无法自定义子协议的客户端仍可用 ?token= 兜底。

    参数:
    - websocket (WebSocket): WebSocket 连接对象。

    返回:
    - tuple[str | None, str | None]: (令牌, 握手需回显的子协议)；无令牌时返回 (None, None)。
    """
    for proto in websocket.headers.get("sec-websocket-protocol", "").split(","):
        proto = proto.strip()
        if proto.startswith(f"{WS_TOKEN_SUBPROTOCOL}."):
            token = proto[len(f"{WS_TOKEN_SUBPROTOCOL}.") :]
            if token:
                return token, WS_TOKEN_SUBPROTOCOL
    return websocket.query_params.get("token"), None


async def websocket_authenticate(websocket: WebSocket) -> tuple[AuthSchema, str | None]:
    """WebSocket 握手认证：解析令牌并校验，失败抛 CustomException。

    返回:
    - tuple[AuthSchema, str | None]: (认证信息, 握手需回显的子协议)。
    """
    token, subprotocol = get_websocket_token(websocket)
    if not token:
        raise CustomException(msg="未提供认证令牌")
    async with async_db_session() as db:
        auth = await _authenticate(token, db, websocket.app.state.redis)
    return auth, subprotocol


async def _authenticate(
    token: str,
    db: AsyncSession,
    redis: Redis,
    *,
    allow_pending: bool = False,
) -> AuthSchema:
    """核心认证逻辑（HTTP 与 WebSocket 共享）。

    allow_pending=True 仅供 select-tenant 流程使用（pending 会话唯一可访问端点）。
    """
    if not token:
        raise CustomException(msg="认证已失效", code=RET.UNAUTHORIZED.code)

    # 处理Bearer token（兼容无空格/无前缀输入，避免 IndexError）
    if token.startswith("Bearer"):
        token = token[len("Bearer") :].strip()
        if not token:
            raise CustomException(msg="认证已失效", code=RET.UNAUTHORIZED.code)

    # 滑动模式下跳过 JWT exp 校验，由 Redis session TTL 决定实际有效期
    payload = decode_access_token(token, verify_exp=not settings.TOKEN_SLIDING_EXPIRE)
    if not payload or payload.is_refresh:
        raise CustomException(msg="非法凭证", code=RET.INVALID_CREDENTIALS.code)

    session_id = payload.sub
    if not session_id:
        raise CustomException(msg="认证已失效", code=RET.UNAUTHORIZED.code)

    session_key = f"{RedisInitKeyConfig.USER_SESSION.key}:{session_id}"
    raw = await RedisCURD(redis).get(session_key)
    if not raw:
        raise CustomException(msg="认证已失效", code=RET.UNAUTHORIZED.code)
    user_info = json.loads(raw)

    # 校验 session 数据完整性
    if not user_info.get("session_id"):
        raise CustomException(msg="认证已失效", code=RET.UNAUTHORIZED.code)

    # 滑动过期续期：以 USER_SESSION 为存活判据与续期主体，且受绝对上限约束
    if settings.TOKEN_SLIDING_EXPIRE:
        crud = RedisCURD(redis)
        session_ttl = await crud.ttl(key=session_key)
        if session_ttl == -1:
            # 历史数据无 TTL：补设兜底过期，防止永不过期的会话
            await crud.expire(key=session_key, expire=settings.REFRESH_TOKEN_EXPIRE_SECONDS)
        elif session_ttl > 0 and session_ttl < settings.REFRESH_TOKEN_EXPIRE_SECONDS // 2:
            created_at = user_info.get("created_at")
            expired = False
            if created_at:
                try:
                    age = (datetime.now(UTC) - datetime.fromisoformat(str(created_at))).total_seconds()
                    expired = age >= settings.SESSION_MAX_LIFETIME_SECONDS
                except ValueError:
                    expired = True
            else:
                # 存量会话无 created_at：补写当前时间作为兜底起点，不误杀在线用户
                user_info["created_at"] = datetime.now(UTC).isoformat()
                await crud.set(
                    key=session_key,
                    value=json.dumps(user_info, ensure_ascii=False, default=str),
                    expire=settings.REFRESH_TOKEN_EXPIRE_SECONDS,
                )
            if expired:
                await crud.delete(session_key)
                raise CustomException(msg="会话超过最大存活时长，请重新登录", code=RET.UNAUTHORIZED.code)
            # 续期必须落在存活判据（USER_SESSION）上，否则续期无效、判据形同虚设
            await crud.expire(key=session_key, expire=settings.REFRESH_TOKEN_EXPIRE_SECONDS)
            await crud.expire(
                key=f"{RedisInitKeyConfig.REFRESH_TOKEN.key}:{session_id}",
                expire=settings.REFRESH_TOKEN_EXPIRE_SECONDS,
            )

    username = user_info.get("user_name")
    if not username:
        raise CustomException(msg="认证已失效", code=RET.UNAUTHORIZED.code)

    user_status = user_info.get("user_status", 0)
    user_id = user_info.get("user_id")

    if user_status == 1:
        raise CustomException(msg="用户已被停用", code=RET.UNAUTHORIZED.code)

    if not user_id:
        raise CustomException(msg="认证已失效", code=RET.UNAUTHORIZED.code)

    # 租户门控（W2·11c）：pending=登录未绑定租户的多租户中间态；ENFORCE off 放行只留痕（11d 挂列回填后全量）
    tenant_id = user_info.get("tenant_id")
    is_super_admin = bool(user_info.get("is_super_admin", user_info.get("is_superuser", False)))
    tenant_pending = bool(user_info.get("tenant_pending")) and not is_super_admin
    if tenant_pending and settings.TENANT_ENFORCE and not allow_pending:
        raise CustomException(msg="会话未绑定租户，请先选择租户", code=RET.FORBIDDEN.code)

    # 每请求查库校验用户仍存在且未删除：token 只证明签发时身份，不证明现在。
    # 身份存在性查询按主键、**必须先于租户上下文设置**——否则多租户用户选定非主租户后，
    # 本查询会被会话租户过滤而查不到自己 → 每请求 401 自锁（阶段审计 A-C1）。
    from app.modules.system.user.model import UserModel  # 延迟导入：core 导入期不依赖业务层（守卫不变式 3）

    user_obj = (
        (
            await db.execute(select(UserModel).where(UserModel.id == user_id, UserModel.is_deleted == False))  # noqa: E712
        )
        .scalars()
        .first()
    )
    if not user_obj:
        raise CustomException(msg="用户不存在", code=RET.UNAUTHORIZED.code)

    current_tenant.set(tenant_id)
    current_superadmin.set(is_super_admin)

    user = CoreUserSchema.model_validate(user_obj)
    return AuthSchema(
        user=user,
        permissions=user_info.get("permissions", []),
        menu_ids=user_info.get("menu_ids", []),
        tenant_id=tenant_id,
        is_super_admin=is_super_admin,
        tenant_pending=tenant_pending,
    )


class AuthPermission:
    """权限验证类"""

    def __init__(
        self,
        permissions: list[str] | None = None,
    ) -> None:
        """初始化权限验证

        参数:
        - permissions (list[str] | None): 权限标识列表。
        """
        self.permissions = permissions or []

    async def __call__(self, auth: AuthSchema = Depends(get_current_user)) -> AuthSchema:
        """调用权限验证

        参数:
        - auth (AuthSchema): 认证信息对象。

        返回:
        - AuthSchema: 已认证的权限信息对象。
        """
        user = auth.user
        if user.id is None or user.is_superuser:
            return auth

        if not self.permissions:
            return auth

        if "*" in self.permissions or "*:*:*" in self.permissions:
            return auth

        user_permissions = set[Any](auth.permissions)

        if not user_permissions:
            raise CustomException(msg="无权限操作", code=RET.FORBIDDEN.code)

        if not any(perm in user_permissions for perm in self.permissions):
            logger.error(f"用户缺少任何所需的权限: {self.permissions}")
            raise CustomException(msg="无权限操作", code=RET.NO_PERMISSION.code)

        return auth
