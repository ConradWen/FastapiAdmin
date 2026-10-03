"""错误码单一事实来源（t16）回归测试。

设计约定：
- HTTP 语义只由 ``RET.code → HTTP status``（``core/exceptions.py`` 的映射表）决定；
- 业务代码只传 ``code``；意外异常不在业务代码里包装，交给全局处理器映射为 5xx；
- 除 ``core/exceptions.py``（映射表与逃生口）外，``app/`` 下不得再出现 ``status_code=`` 传参。

本文件既锁语义（400/401/403/404/500），也加静态护栏防回潮。
"""

import ast
import json
import pathlib
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.common.enums import RET
from app.core.exceptions import CustomException, handle_exception, resolve_http_status
from app.core.logger import logger

_APP_DIR = pathlib.Path(__file__).resolve().parent.parent / "app"
_EXCEPTIONS_FILE = _APP_DIR / "core" / "exceptions.py"
_STATUS_KWARG = "status_code="
# 唯一允许的例外：FastAPI 路由装饰器的框架参数（如 @Router.post(..., status_code=201)），
# 与「业务错误码 → HTTP 语义」无关；去掉它会改变创建类接口的 HTTP 语义（201→200），故白名单放行。
_ROUTE_DECORATOR_LINE = re.compile(r"^\s*@\w+\.(get|post|put|patch|delete|head|options)\(")


# ── 1) 静态护栏：业务代码不得显式传 status_code ───────────────────────────────


def test_no_explicit_status_code_in_business_code() -> None:
    """app/ 下（除 core/exceptions.py）不得出现 status_code= 传参。"""
    violations: list[str] = []
    allowed: list[str] = []
    for path in sorted(_APP_DIR.rglob("*.py")):
        if path == _EXCEPTIONS_FILE:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _STATUS_KWARG not in line:
                continue
            record = f"{path.relative_to(_APP_DIR.parent)}:{lineno}: {line.strip()[:120]}"
            if _ROUTE_DECORATOR_LINE.match(line):
                allowed.append(record)  # FastAPI 路由装饰器参数（框架语义，非业务错误码）
                continue
            violations.append(record)
    assert violations == [], f"业务代码出现显式 status_code 传参（应改为 code=... 或 CustomException.internal）：{violations}"
    assert allowed, "白名单为空：若路由装饰器写法变化请同步更新本测试"


def test_no_custom_exception_passes_status_code() -> None:
    """更精确的护栏：CustomException 调用点一律不传 status_code（除 exceptions.py 自身）。"""
    offenders: list[str] = []
    call_re = re.compile(r"CustomException(?:\.\w+)?\(")
    for path in sorted(_APP_DIR.rglob("*.py")):
        if path == _EXCEPTIONS_FILE:
            continue
        text = path.read_text(encoding="utf-8")
        for match in call_re.finditer(text):
            depth, index = 0, match.end() - 1
            while index < len(text):
                if text[index] == "(":
                    depth += 1
                elif text[index] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                index += 1
            call = text[match.start() : index + 1]
            if _STATUS_KWARG in call:
                offenders.append(f"{path.relative_to(_APP_DIR.parent)}:{text[: match.start()].count(chr(10)) + 1}")
    assert offenders == [], f"CustomException 仍显式传 status_code：{offenders}"


# ── 2) 映射表是唯一事实来源 ──────────────────────────────────────────────────


def test_mapping_table_is_explicit_for_default_business_code() -> None:
    """默认业务码 RET.EXCEPTION(-1) 显式登记为 400（不再依赖隐式兜底）。"""
    assert resolve_http_status(RET.EXCEPTION.code) == 400
    assert CustomException(msg="验证码已过期，请刷新").status_code == 400


def test_mapping_covers_http_like_codes() -> None:
    """凡是「数值本身就是 HTTP 状态码」的 RET 成员，映射结果必须与自身一致。"""
    for member in RET:
        if 400 <= member.code <= 599:
            assert resolve_http_status(member.code) == member.code, f"{member.name}({member.code}) 映射错位"


def test_no_internal_entry_and_unexpected_errors_use_global_handler() -> None:
    """t19：internal() 语义入口已删除；意外异常交给全局处理器给 5xx + 通用文案。"""
    assert not hasattr(CustomException, "internal")
    assert resolve_http_status(RET.SERVERERR.code) == 500  # 码仍在映射表内，供显式声明服务端故障的业务码使用

    app = FastAPI()
    handle_exception(app)

    @app.get("/unexpected")
    async def _unexpected() -> None:
        raise RuntimeError("统计失败: 连接断开 connection lost")

    response = TestClient(app, raise_server_exceptions=False).get("/unexpected")
    assert response.status_code == 500
    body = response.json()
    assert body["msg"] == "服务器内部错误"
    assert "connection lost" not in json.dumps(body, ensure_ascii=False)


def test_unmapped_code_falls_back_to_client_error_net() -> None:
    """未登记 code 的安全网仍是 400（仅兜底，不应作为正常路径）。"""
    assert resolve_http_status(999999) == 400
    assert resolve_http_status(None) == 400


# ── 3) 语义不变（HTTP 层实测） ───────────────────────────────────────────────


def _semantic_probe_app() -> FastAPI:
    app = FastAPI()
    handle_exception(app)

    @app.get("/captcha-expired")
    async def _captcha() -> None:
        raise CustomException(msg="验证码已过期，请刷新")

    @app.get("/forbidden")
    async def _forbidden() -> None:
        raise CustomException(msg="无权限操作", code=RET.NO_PERMISSION.code)

    @app.get("/token-expired")
    async def _token() -> None:
        raise CustomException(msg="认证已失效", code=RET.TOKEN_EXPIRED.code)

    @app.get("/not-found")
    async def _not_found() -> None:
        raise CustomException(msg="该数据不存在", code=RET.NOT_FOUND.code)

    @app.get("/internal")
    async def _internal() -> None:
        # 意外异常：不包装，直接冒泡给全局处理器（t19）
        raise RuntimeError("统计失败: 模拟底层驱动故障")

    return app


@pytest.mark.parametrize(
    ("path", "expected_status", "expected_code"),
    [
        ("/captcha-expired", 400, RET.EXCEPTION.code),
        ("/forbidden", 403, RET.NO_PERMISSION.code),
        ("/token-expired", 401, RET.TOKEN_EXPIRED.code),
        ("/not-found", 404, RET.NOT_FOUND.code),
        ("/internal", 500, RET.ERROR.code),
    ],
)
def test_semantics_unchanged_via_mapping(path: str, expected_status: int, expected_code: int) -> None:
    """验证码/参数→400、无权限→403、令牌→401、资源不存在→404、内部故障→500，且响应体结构不变。"""
    client = TestClient(_semantic_probe_app(), raise_server_exceptions=False)
    response = client.get(path)
    assert response.status_code == expected_status, response.text
    body = response.json()
    assert set(body) >= {"code", "msg", "data", "status_code", "success"}
    assert body["code"] == expected_code
    assert body["status_code"] == expected_status
    assert body["msg"]  # 诊断信息不丢
    assert body["success"] is False


# ── 4) t19：业务异常透传 + 意外异常冒泡（AST 护栏） ───────────────────────────


def test_internal_faults_are_not_wrapped_locally() -> None:
    """132 处局部包装已清除：app/ 下不再出现 internal() 语义入口或 status_code 传参。"""
    offenders: list[str] = []
    for path in sorted(_APP_DIR.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "CustomException.internal" in text or "def internal(" in text:
            offenders.append(str(path.relative_to(_APP_DIR.parent)))
    assert offenders == [], f"仍存在局部包装入口：{offenders}"


def test_business_error_passes_through_try_and_stays_4xx() -> None:
    """try 内抛出的业务 400 穿过「日志 + raise」的宽泛 except 后仍是 400。"""
    app = FastAPI()
    handle_exception(app)

    async def _service() -> None:
        raise CustomException(msg="请求参数错误")

    @app.get("/passthrough")
    async def _passthrough() -> None:
        try:
            await _service()
        except CustomException:
            raise
        except Exception as exc:
            logger.exception("处理请求失败")
            raise exc

    response = TestClient(app, raise_server_exceptions=False).get("/passthrough")
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["msg"] == "请求参数错误"
    assert body["code"] == RET.EXCEPTION.code


# 宽泛 except 若「构造新的 CustomException」抛出，必须先有 `except CustomException: raise`
_BROAD = {"Exception", "BaseException"}


def _is_custom_exception_name(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "CustomException"
    if isinstance(node, ast.Attribute):
        return node.attr == "CustomException"
    if isinstance(node, ast.Tuple):
        return any(_is_custom_exception_name(e) for e in node.elts)
    return False


def _is_broad_handler(handler: ast.ExceptHandler) -> bool:
    t = handler.type
    if t is None:
        return True
    if isinstance(t, ast.Name):
        return t.id in _BROAD
    if isinstance(t, ast.Tuple):
        return any(isinstance(e, ast.Name) and e.id in _BROAD for e in t.elts)
    return False


def test_ast_guard_broad_except_requires_custom_exception_passthrough() -> None:
    """AST 护栏：宽泛 except 若转换异常，必须前置 `except CustomException: raise`（防语义反转回潮）。"""
    offenders: list[str] = []
    for path in sorted(_APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            guarded = any(
                h.type is not None
                and _is_custom_exception_name(h.type)
                and any(isinstance(stmt, ast.Raise) and stmt.exc is None for stmt in h.body)
                for h in node.handlers
            )
            for handler in node.handlers:
                if not _is_broad_handler(handler) or guarded:
                    continue
                for inner in ast.walk(handler):
                    if (
                        isinstance(inner, ast.Raise)
                        and isinstance(inner.exc, ast.Call)
                        and getattr(inner.exc.func, "id", None) == "CustomException"
                    ):
                        offenders.append(f"{path.relative_to(_APP_DIR.parent)}:{inner.lineno}")
    assert offenders == [], f"宽泛 except 转换业务异常却缺守卫（应加 except CustomException: raise）：{offenders}"
