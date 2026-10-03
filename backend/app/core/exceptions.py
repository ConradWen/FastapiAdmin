from functools import wraps
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from app.common.enums import RET, EnvironmentEnum
from app.common.response import ErrorResponse
from app.config.setting import settings
from app.core.logger import logger


def require_superadmin(func):
    """装饰器：仅超级管理员可调用 Service 方法。

    自动校验 ``self.auth.user.is_superuser`` 属性，非超管直接抛出 403。
    适用于实例方法（``Service(auth).xxx(...)``），由 ``self.auth`` 取认证上下文。

    用法:
        class XxxService:
            def __init__(self, auth: AuthSchema) -> None:
                self.auth = auth

            @require_superadmin
            async def create(self, data: ...) -> ...:
                ...
    """

    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        if not self.auth.user or not self.auth.user.is_superuser:
            raise CustomException(msg="仅平台管理员可操作")
        return await func(self, *args, **kwargs)

    return wrapper


# starlette 新版本把 HTTP_422_UNPROCESSABLE_ENTITY 标为弃用，这里取新常量并兼容旧版本，
# 避免模块导入期就打 DeprecationWarning
_HTTP_422: int = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)

# 业务错误码 → HTTP 状态码。只映射语义明确的码；其余业务异常统一按 _DEFAULT_BUSINESS_STATUS 返回。
# 说明：历史上 CustomException 的 status_code 默认 500，导致「验证码过期」「参数校验失败」这类
# 客户端错误也返回 500 —— 前端无法区分「我错了」与「服务器坏了」，监控/告警也被污染。
_CODE_TO_HTTP_STATUS: dict[int, int] = {
    RET.BAD_REQUEST.code: status.HTTP_400_BAD_REQUEST,
    RET.UNAUTHORIZED.code: status.HTTP_401_UNAUTHORIZED,
    RET.FORBIDDEN.code: status.HTTP_403_FORBIDDEN,
    RET.NOT_FOUND.code: status.HTTP_404_NOT_FOUND,
    RET.CONFLICT.code: status.HTTP_409_CONFLICT,
    RET.UNPROCESSABLE_ENTITY.code: _HTTP_422,
    RET.TOO_MANY_REQUESTS.code: status.HTTP_429_TOO_MANY_REQUESTS,
    RET.SERVICE_UNAVAILABLE.code: status.HTTP_503_SERVICE_UNAVAILABLE,
    RET.DATAEXIST.code: status.HTTP_409_CONFLICT,
    RET.PARAMERR.code: status.HTTP_400_BAD_REQUEST,
    RET.TIMEOUT.code: status.HTTP_504_GATEWAY_TIMEOUT,
    RET.RATE_LIMIT_EXCEEDED.code: status.HTTP_429_TOO_MANY_REQUESTS,
    # 认证类业务码（对应前端 ResultEnum）
    RET.INVALID_TOKEN.code: status.HTTP_401_UNAUTHORIZED,
    RET.EXPIRED_TOKEN.code: status.HTTP_401_UNAUTHORIZED,
    RET.INVALID_CREDENTIALS.code: status.HTTP_401_UNAUTHORIZED,
    RET.TOKEN_EXPIRED.code: status.HTTP_401_UNAUTHORIZED,
    RET.NO_PERMISSION.code: status.HTTP_403_FORBIDDEN,
    # 显式声明为服务端错误的码（供内部包装器使用，如 CRUD「xx失败」兜底）
    RET.SERVERERR.code: status.HTTP_500_INTERNAL_SERVER_ERROR,
}

# 未映射业务码的默认状态：业务异常按「客户端请求错误」处理（而不是 500）
_DEFAULT_BUSINESS_STATUS: int = status.HTTP_400_BAD_REQUEST


def resolve_http_status(code: int | None) -> int:
    """把业务错误码解析为 HTTP 状态码。

    参数:
    - code (int | None): 业务错误码。

    返回:
    - int: 对应的 HTTP 状态码；未映射的码返回 _DEFAULT_BUSINESS_STATUS。
    """
    if code is None:
        return _DEFAULT_BUSINESS_STATUS
    return _CODE_TO_HTTP_STATUS.get(int(code), _DEFAULT_BUSINESS_STATUS)


class CustomException(Exception):
    """业务异常。

    ``status_code`` 未显式传入时按 ``code`` 推导（见 :func:`resolve_http_status`），
    默认 400（客户端可修正）而非 500；只有确属服务端故障的场景才应显式传 500，
    或使用 ``code=RET.SERVERERR.code``。
    """

    def __init__(
        self,
        msg: str = RET.EXCEPTION.msg,
        code: int = RET.EXCEPTION.code,
        status_code: int | None = None,
        data: Any | None = None,
        success: bool = False,
    ) -> None:
        super().__init__(msg)
        self.status_code = status_code if status_code is not None else resolve_http_status(code)
        self.code = code
        self.msg = msg
        self.data = data
        self.success = success

    def __str__(self) -> str:
        return self.msg


def handle_exception(app: FastAPI) -> None:
    @app.exception_handler(CustomException)
    async def custom_exception_handler(request: Request, exc: CustomException) -> JSONResponse:
        # 4xx 是「客户端可修正」的业务结果，5xx 才是服务端故障：分级记录，
        # 避免每个校验失败都打 ERROR 把真正的故障信号淹没。
        log = logger.error if exc.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR else logger.warning
        log(
            "[自定义异常] {} {} | code={} | status={} | msg={} | data={}",
            request.method,
            request.url.path,
            exc.code,
            exc.status_code,
            exc.msg,
            exc.data,
        )
        # 生产环境不外泄 data（可能含 SQL 字段、约束名等内部细节）
        expose_data = exc.data if settings.ENVIRONMENT != EnvironmentEnum.PROD else None
        return ErrorResponse(msg=exc.msg, code=exc.code, status_code=exc.status_code, data=expose_data)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        logger.error(
            "[HTTP异常] {} {} | status_code={} | detail={}",
            request.method,
            request.url.path,
            exc.status_code,
            exc.detail,
        )
        return ErrorResponse(msg=exc.detail, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        msg = errors[0].get("msg", str(errors[0])) if errors else "请求参数验证失败"
        if msg.startswith("Value error"):
            msg = msg[11:].lstrip(" ,")
        logger.error(
            "[参数验证异常] {} {} | errors={}",
            request.method,
            request.url.path,
            errors,
        )
        return ErrorResponse(msg=str(msg), status_code=_HTTP_422, data=errors)

    @app.exception_handler(ResponseValidationError)
    async def response_validation_handler(request: Request, exc: ResponseValidationError) -> JSONResponse:
        logger.error(
            "[响应验证异常] {} {} | errors={}",
            request.method,
            request.url.path,
            exc.errors(),
        )
        return ErrorResponse(msg="服务器响应格式错误", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, data=exc.body)

    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        exc_type = type(exc).__name__

        if isinstance(exc, IntegrityError):
            detail = str(exc.orig) if exc.orig else str(exc)
            expose_detail = detail if settings.ENVIRONMENT != EnvironmentEnum.PROD else None
            if "connect" in detail or "connection" in detail:
                return ErrorResponse(msg="数据库连接失败", status_code=status.HTTP_403_SERVICE_UNAVAILABLE, data=expose_detail)
            if "Duplicate entry" in detail:
                return ErrorResponse(msg="数据重复，请检查唯一字段", status_code=status.HTTP_409_CONFLICT, data=expose_detail)
            if "foreign key constraint" in detail:
                return ErrorResponse(msg="存在关联数据，无法删除", status_code=status.HTTP_409_CONFLICT, data=expose_detail)
            if "cannot be null" in detail:
                return ErrorResponse(msg="必填字段缺失", status_code=status.HTTP_409_CONFLICT, data=expose_detail)
            return ErrorResponse(msg="数据已存在或违反完整性约束", status_code=status.HTTP_409_CONFLICT, data=expose_detail)

        logger.error("[数据库异常] {} {} | type={} | detail={}", request.method, request.url.path, exc_type, exc)
        data = str(exc) if settings.ENVIRONMENT != EnvironmentEnum.PROD else None
        return ErrorResponse(msg=f"数据库操作失败: {exc_type}", status_code=status.HTTP_400_BAD_REQUEST, data=data)

    @app.exception_handler(ValueError)
    async def value_exception_handler(request: Request, exc: ValueError) -> JSONResponse:
        logger.error("[值异常] {} {} | msg={}", request.method, request.url.path, exc)
        return ErrorResponse(msg=str(exc), status_code=status.HTTP_400_BAD_REQUEST)

    @app.exception_handler(Exception)
    async def all_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        exc_type = type(exc).__name__
        logger.error(
            "[未捕获异常] {} {} | type={} | detail={}",
            request.method,
            request.url.path,
            exc_type,
            exc,
        )
        return ErrorResponse(msg="服务器内部错误", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
