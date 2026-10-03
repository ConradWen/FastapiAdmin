"""安全默认值与异常状态码回归测试。

覆盖 backend/audit-security.md 的 S9/S10 与 backend/audit-backend.md 的 H1/H5 同类根因：
- 业务异常按自身状态码返回：客户端可修正类（参数/验证码/权限/不存在）为 4xx；
- 「包装底层异常」的内部故障（DB/驱动/Redis/SDK）显式为 500，不得降级成 4xx（否则监控误判）；
- 定时任务代码块执行默认关闭，关闭时给出明确失败原因（而非静默执行/静默跳过）；
- 生产环境 CORS 不再回落为通配 ``["*"]``（与 ``ALLOW_CREDENTIALS=True`` 组合会放行任意站点带凭据跨域）。
"""

import pathlib
import re
from datetime import datetime
from types import SimpleNamespace

import pytest
from apscheduler.triggers.date import DateTrigger
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.common.enums import RET, EnvironmentEnum
from app.config.setting import Settings, settings
from app.core.ap_scheduler import SchedulerUtil
from app.core.exceptions import CustomException, handle_exception, resolve_http_status
from app.core.middlewares import CustomCORSMiddleware
from app.modules.task.cronjob.node.service import _add_job_with_trigger

# ── 1. 业务异常按自身状态码返回（默认 4xx） ──────────────────────────────────


def test_custom_exception_defaults_to_4xx() -> None:
    """未显式指定状态码时按业务错误处理，而不是 500。"""
    exc = CustomException(msg="验证码已过期，请刷新")
    assert exc.status_code == 400
    assert exc.code == RET.EXCEPTION.code  # 业务码保持不变（响应体结构兼容）
    assert exc.success is False


def test_custom_exception_status_resolution() -> None:
    """显式状态码优先；否则按业务码映射；未知码回落 400。"""
    assert CustomException(msg="x", status_code=403).status_code == 403
    assert CustomException(msg="x", status_code=500).status_code == 500
    assert CustomException(msg="x", code=RET.UNAUTHORIZED.code).status_code == 401
    assert CustomException(msg="x", code=RET.NOT_FOUND.code).status_code == 404
    assert CustomException(msg="x", code=RET.NO_PERMISSION.code).status_code == 403
    assert CustomException(msg="x", code=RET.TOO_MANY_REQUESTS.code).status_code == 429
    assert CustomException(msg="x", code=RET.SERVERERR.code).status_code == 500
    assert resolve_http_status(None) == 400
    assert resolve_http_status(999999) == 400


def _exception_probe_app() -> FastAPI:
    """最小应用：注册与生产一致的异常处理器。"""
    app = FastAPI()
    handle_exception(app)

    @app.get("/captcha-expired")
    async def _captcha_expired() -> None:
        raise CustomException(msg="验证码已过期，请刷新")

    @app.get("/forbidden")
    async def _forbidden() -> None:
        raise CustomException(msg="无权限操作", code=RET.NO_PERMISSION.code, status_code=403)

    @app.get("/boom")
    async def _boom() -> None:
        raise RuntimeError("unexpected server failure")

    return app


def test_captcha_expired_returns_4xx_with_stable_body() -> None:
    """实测回归：验证码过期返回 400（此前为 500），响应体结构保持既有约定。"""
    client = TestClient(_exception_probe_app(), raise_server_exceptions=False)
    response = client.get("/captcha-expired")
    assert response.status_code == 400, response.text
    body = response.json()
    assert set(body) >= {"code", "msg", "data", "status_code", "success"}
    assert body["msg"] == "验证码已过期，请刷新"
    assert body["success"] is False
    assert body["status_code"] == 400


def test_explicit_status_code_is_honored_by_handler() -> None:
    """显式状态码仍按原样返回（403 不被 400 覆盖）。"""
    client = TestClient(_exception_probe_app(), raise_server_exceptions=False)
    response = client.get("/forbidden")
    assert response.status_code == 403, response.text
    assert response.json()["code"] == RET.NO_PERMISSION.code


def test_unhandled_exception_still_returns_500() -> None:
    """未捕获的服务端异常仍然是 500（本次修改没有把真正的故障降级成 4xx）。"""
    client = TestClient(_exception_probe_app(), raise_server_exceptions=False)
    response = client.get("/boom")
    assert response.status_code == 500, response.text


# ── 2. 定时任务代码块执行默认关闭 ────────────────────────────────────────────


def test_scheduler_code_exec_default_is_false() -> None:
    """配置默认值必须是 False（只在显式配置为 true 时启用）。"""
    assert Settings.model_fields["SCHEDULER_ALLOW_CODE_EXEC"].default is False


def test_task_wrapper_refuses_code_block_with_clear_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """关闭时代码块任务在**执行入口**失败，并给出可理解的拒绝原因。"""
    monkeypatch.setattr(settings, "SCHEDULER_ALLOW_CODE_EXEC", False)
    with pytest.raises(RuntimeError) as excinfo:
        SchedulerUtil._task_wrapper("job-1", "def handler(*args, **kwargs):\n    return 'executed'\n")
    message = str(excinfo.value)
    assert "SCHEDULER_ALLOW_CODE_EXEC" in message
    assert "拒绝执行" in message


def test_task_wrapper_runs_only_when_explicitly_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """显式开启后代码块才被执行（证明开关语义正确、不是"永远拒绝"）。"""
    monkeypatch.setattr(settings, "SCHEDULER_ALLOW_CODE_EXEC", True)
    result = SchedulerUtil._task_wrapper("job-2", "def handler(*args, **kwargs):\n    return 'executed'\n")
    assert result == "executed"


def test_task_wrapper_without_code_block_still_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """内置函数型任务（无用户代码块）不受该开关影响。"""
    monkeypatch.setattr(settings, "SCHEDULER_ALLOW_CODE_EXEC", False)
    assert SchedulerUtil._task_wrapper("job-3", None) is None


def test_registering_code_block_job_reports_clear_error_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """注册入口同样给出明确失败提示（而不是把任务静默注册后不执行）。"""
    monkeypatch.setattr(settings, "SCHEDULER_ALLOW_CODE_EXEC", False)
    node = SimpleNamespace(
        id=7,
        name="演示节点",
        func="def handler(*args, **kwargs):\n    return 'x'\n",
        jobstore="memory",
        executor="threadpool",
        args=None,
        kwargs=None,
        coalesce=False,
        max_instances=1,
    )
    with pytest.raises(CustomException) as excinfo:
        _add_job_with_trigger(node, DateTrigger(run_date=datetime.now()))
    assert "SCHEDULER_ALLOW_CODE_EXEC" in str(excinfo.value)


# ── 3. 生产 CORS 不再回落通配 ────────────────────────────────────────────────


def _cors_probe_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CustomCORSMiddleware)

    @app.get("/probe")
    async def _probe() -> dict[str, bool]:
        return {"ok": True}

    return app


def test_prod_cors_is_empty_when_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """生产未配置 PROD_CORS_ORIGINS → 空列表（安全默认），不再是 ["*"]。"""
    monkeypatch.setattr(settings, "ENVIRONMENT", EnvironmentEnum.PROD)
    monkeypatch.setattr(settings, "PROD_CORS_ORIGINS", "")
    assert settings.ALLOW_ORIGINS == []


def test_prod_cors_drops_wildcard(monkeypatch: pytest.MonkeyPatch) -> None:
    """显式配置通配符也要被剔除（与 ALLOW_CREDENTIALS=True 组合不可接受）。"""
    monkeypatch.setattr(settings, "ENVIRONMENT", EnvironmentEnum.PROD)
    monkeypatch.setattr(settings, "PROD_CORS_ORIGINS", "*")
    assert settings.ALLOW_ORIGINS == []
    monkeypatch.setattr(settings, "PROD_CORS_ORIGINS", "https://ok.example.com, *")
    assert settings.ALLOW_ORIGINS == ["https://ok.example.com"]


def test_prod_cors_keeps_explicit_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    """显式配置的域名清单被保留（去掉空白项）。"""
    monkeypatch.setattr(settings, "ENVIRONMENT", EnvironmentEnum.PROD)
    monkeypatch.setattr(settings, "PROD_CORS_ORIGINS", " https://a.example.com , https://b.example.com , ")
    assert settings.ALLOW_ORIGINS == ["https://a.example.com", "https://b.example.com"]


def test_dev_cors_keeps_wildcard(monkeypatch: pytest.MonkeyPatch) -> None:
    """非生产环境保留通配（本地联调便利），安全默认只收紧生产。"""
    monkeypatch.setattr(settings, "ENVIRONMENT", EnvironmentEnum.DEV)
    assert settings.ALLOW_ORIGINS == ["*"]


def test_prod_cors_headers_absent_for_unknown_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    """端到端：生产未配置域名时，任意来源都拿不到跨域许可头。"""
    monkeypatch.setattr(settings, "ENVIRONMENT", EnvironmentEnum.PROD)
    monkeypatch.setattr(settings, "PROD_CORS_ORIGINS", "")
    client = TestClient(_cors_probe_app())
    response = client.get("/probe", headers={"Origin": "https://evil.tld"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in {key.lower() for key in response.headers}


def test_prod_cors_allows_only_configured_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    """端到端：只有显式配置的来源拿到许可头，其它来源仍被拒绝。"""
    monkeypatch.setattr(settings, "ENVIRONMENT", EnvironmentEnum.PROD)
    monkeypatch.setattr(settings, "PROD_CORS_ORIGINS", "https://ok.example.com")
    client = TestClient(_cors_probe_app())

    allowed = client.get("/probe", headers={"Origin": "https://ok.example.com"})
    assert allowed.headers.get("access-control-allow-origin") == "https://ok.example.com"

    denied = client.get("/probe", headers={"Origin": "https://evil.tld"})
    assert "access-control-allow-origin" not in {key.lower() for key in denied.headers}


# ── 4. 内部故障（包装底层异常）必须为 500，客户端错误保持 4xx ─────────────────
#
# 背景：t10 把 CustomException 的默认状态码从 500 改为 400 后，「包装底层异常」的路径
# （数据库/驱动/Redis/SDK 故障）也被一并降级成 400，监控会把服务端故障误判为客户端错误。
# 这里固化两类语义：包装底层异常 → 500；参数/权限/不存在 → 4xx。

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


class _FailingSession:
    """所有 SQL 操作都抛异常的假会话：模拟数据库/驱动故障。"""

    @staticmethod
    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("模拟底层驱动故障: connection lost")

    def add(self, *_args: object, **_kwargs: object) -> None:
        self._boom()

    async def execute(self, *_args: object, **_kwargs: object) -> None:
        self._boom()

    async def flush(self, *_args: object, **_kwargs: object) -> None:
        self._boom()

    async def refresh(self, *_args: object, **_kwargs: object) -> None:
        self._boom()

    async def delete(self, *_args: object, **_kwargs: object) -> None:
        self._boom()


class _EmptyResult:
    """空结果集：让 get_or_404 走到"查不到"分支。"""

    def scalars(self) -> "_EmptyResult":
        return self

    def first(self) -> None:
        return None

    def all(self) -> list:
        return []

    def scalar(self) -> int:
        return 0

    def fetchall(self) -> list:
        return []


class _EmptySession:
    """execute 恒返回空结果的假会话。"""

    async def execute(self, *_args: object, **_kwargs: object) -> _EmptyResult:
        return _EmptyResult()


def _crud(db: object, model: type | None = None):
    """构造 CRUD 实例（默认挂在一个真实模型上，避免测试私自注册新模型污染 metadata）。"""
    from app.core.base_crud import CRUDBase
    from app.core.base_schema import AuthSchema
    from app.modules.system.role.model import RoleModel

    return CRUDBase(model=model or RoleModel, auth=AuthSchema(), db=db)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("case", "call"),
    [
        ("get", lambda c: c.get(id=1)),
        ("count", lambda c: c.count()),
        ("exists", lambda c: c.exists(id=1)),
        ("get_list", lambda c: c.get_list()),
        ("page", lambda c: c.page(offset=0, limit=10, order_by=[{"id": "asc"}])),
        ("create", lambda c: c.create(data={"name": "x"})),
        ("update", lambda c: c.update(id=1, data={"name": "x"})),
        ("delete", lambda c: c.delete(ids=[1])),
        ("clear", lambda c: c.clear()),
        ("set", lambda c: c.set(ids=[1], status=0)),
    ],
)
async def test_base_crud_wrapped_internal_failure_returns_500(case: str, call) -> None:
    """CRUD 公共出口包装底层异常时必须 500（此前被 t10 降级成 400）。"""
    with pytest.raises(CustomException) as excinfo:
        await call(_crud(_FailingSession()))
    assert excinfo.value.status_code == 500, f"{case} 未按 500 返回（实际 {excinfo.value.status_code}）"
    assert excinfo.value.success is False
    assert "失败" in excinfo.value.msg


async def test_get_or_404_returns_404_for_missing_row() -> None:
    """资源不存在 → 404（客户端可修正类错误，仍是 4xx）。"""
    with pytest.raises(CustomException) as excinfo:
        await _crud(_EmptySession()).get_or_404(id=1, msg="该数据不存在")
    assert excinfo.value.status_code == 404
    assert excinfo.value.msg == "该数据不存在"


def test_client_side_errors_keep_4xx() -> None:
    """客户端类错误保持 4xx：验证码过期/参数类 400、无权限 403、资源不存在 404。"""
    assert CustomException(msg="验证码已过期，请刷新").status_code == 400
    assert CustomException(msg="请求参数错误").status_code == 400
    assert CustomException(msg="无权限操作", code=RET.NO_PERMISSION.code).status_code == 403
    assert CustomException(msg="该数据不存在", status_code=404).status_code == 404
    assert resolve_http_status(RET.NOT_FOUND.code) == 404
    assert resolve_http_status(RET.NO_PERMISSION.code) == 403
    assert resolve_http_status(RET.BAD_REQUEST.code) == 400
    assert resolve_http_status(RET.SERVERERR.code) == 500


def test_internal_failure_body_keeps_business_code_and_message() -> None:
    """内部故障 500 时响应体仍带原始 msg 与业务 code（前端依赖 code=-1 展示真实原因）。"""
    app = FastAPI()
    handle_exception(app)

    @app.get("/internal")
    async def _internal() -> None:
        raise CustomException(msg="统计失败: 模拟底层驱动故障", status_code=500)

    response = TestClient(app, raise_server_exceptions=False).get("/internal")
    assert response.status_code == 500
    body = response.json()
    assert body["msg"] == "统计失败: 模拟底层驱动故障"
    assert body["code"] == RET.EXCEPTION.code


# 与实现同源的分类规则（见 app/core/exceptions.py 的说明与 t11 的清理范围）
_EXC_INTERP = re.compile(r"\{(?:e|exc|err|error|ex|exception)(?:!s|!r|:[a-z]+)?\}|\{errors\[|_error_desc\(")
_EXC_CALL = re.compile(r"CustomException\(")
_CLIENT_MARKERS = (
    "targets 参数格式错误",
    "创建成功但任务注册失败",
    "更新成功但任务注册失败",
    "启用任务失败",
    'msg=f"执行失败: {e!s}"',
    "本地目录不存在",
    "不支持的存储协议",
    "存储源不存在",
    "存储源已停用",
    "不允许上传此类型的文件",
    "流程保存失败",
    "执行失败，连线",
    "创建失败，该字典类型下的",
    "更新失败，该字典类型下的",
    "删除失败，ID为",
    "角色不存在",
    "菜单不存在",
    "部门不存在",
    "用户不存在",
    "岗位不存在",
    "导入文件缺少必要的列",
    "不允许从",
    "工单[",
)


def _iter_custom_exception_calls(path: pathlib.Path):
    """遍历文件里每个 CustomException(...) 调用（含多行调用）。"""
    text = path.read_text(encoding="utf-8")
    for match in _EXC_CALL.finditer(text):
        depth, index = 0, match.end() - 1
        while index < len(text):
            if text[index] == "(":
                depth += 1
            elif text[index] == ")":
                depth -= 1
                if depth == 0:
                    break
            index += 1
        yield text[: match.start()].count("\n") + 1, text[match.start() : index + 1]


def test_all_wrapped_internal_failures_are_explicitly_500() -> None:
    """守卫：inScope 内凡是「包装底层异常」的 CustomException 都必须显式 500。

    否则底层故障会被默认值（400）静默降级成客户端错误，监控失去信号。
    """
    offenders: list[str] = []
    checked = 0
    targets = [_REPO_ROOT / "app" / "core" / "base_crud.py"] + sorted((_REPO_ROOT / "app" / "modules").rglob("*.py"))
    for path in targets:
        for line, call in _iter_custom_exception_calls(path):
            if not _EXC_INTERP.search(call):
                continue
            if any(marker in call for marker in _CLIENT_MARKERS):
                continue
            checked += 1
            if "status_code=500" not in call:
                offenders.append(f"{path.relative_to(_REPO_ROOT)}:{line}")
    assert checked > 90, f"分类用例数异常（只匹配到 {checked} 处），分类规则可能失效"
    assert offenders == [], f"以下代码生成路径仍可能把内部故障降级为 4xx：{offenders}"


def test_base_crud_internal_wrappers_are_500() -> None:
    """core 层专门固化：base_crud.py 全部 9 处包装路径显式 500。"""
    calls = [
        (line, call)
        for line, call in _iter_custom_exception_calls(_REPO_ROOT / "app" / "core" / "base_crud.py")
        if _EXC_INTERP.search(call)
    ]
    assert len(calls) == 9, f"base_crud.py 包装路径数量变化（{len(calls)}）：{[(line, call[:30]) for line, call in calls]}"
    missing = [line for line, call in calls if "status_code=500" not in call]
    assert missing == [], f"base_crud.py 以下行未显式 500：{missing}"


# ── 5. 升级可见性：CORS 严格启动、主机放行开关、健康检查字段 ──────────────────
#
# 背景：t13 把三处「静默行为变更」做成可配置 + 可观测：
# - CORS_STRICT_STARTUP：生产未配置 CORS 白名单时从「只告警」变为「启动失败」；
# - ALLOW_LOCALHOST_HOSTS：localhost 放行从无条件写死变为可开关；
# - 健康检查暴露 code_exec_enabled / cors_origins_configured，避免升级后「任务不动了」无迹可循。


def test_cors_strict_startup_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    """严格模式下：生产未配置白名单 → 直接抛错（启动失败），而不是静默告警。"""
    strict = Settings(
        _env_file=None,
        ENVIRONMENT=EnvironmentEnum.PROD,
        PROD_CORS_ORIGINS="",
        CORS_STRICT_STARTUP=True,
    )
    with pytest.raises(RuntimeError) as excinfo:
        _ = strict.ALLOW_ORIGINS
    assert "PROD_CORS_ORIGINS" in str(excinfo.value)

    # 默认（非严格）仍是安全默认 + 告警，不阻断启动
    lax = Settings(_env_file=None, ENVIRONMENT=EnvironmentEnum.PROD, PROD_CORS_ORIGINS="", CORS_STRICT_STARTUP=False)
    assert lax.ALLOW_ORIGINS == []


def test_localhost_hosts_are_configurable() -> None:
    """localhost/回环放行可开关：默认兼容容器健康检查，生产可收敛 Host 校验范围。"""
    default = Settings(_env_file=None, ALLOW_LOCALHOST_HOSTS=True)
    for host in ("localhost", "127.0.0.1", "[::1]"):
        assert host in default.ALLOWED_HOSTS

    restricted = Settings(_env_file=None, ALLOW_LOCALHOST_HOSTS=False)
    assert "localhost" not in restricted.ALLOWED_HOSTS
    assert "127.0.0.1" not in restricted.ALLOWED_HOSTS
    assert restricted.ALLOWED_HOSTS == ["service.fastapiadmin.com", "*.fastapiadmin.com"]


def test_oauth_allowed_hosts_default_is_not_wildcard() -> None:
    """OAuth 回调域名白名单默认不再是 "*"（Host 注入不再自动放行）。"""
    defaults = Settings(_env_file=None)
    assert "*" not in defaults.OAUTH_ALLOWED_HOSTS
    assert "service.fastapiadmin.com" in defaults.OAUTH_ALLOWED_HOSTS


def test_health_exposes_scheduler_and_cors_state() -> None:
    """健康检查暴露「代码执行开关 / CORS 是否已配置」，让升级后的行为变更可观测。"""
    from app.modules.monitor.health.schema import ServiceInfoOut

    fields = ServiceInfoOut.model_fields
    assert "code_exec_enabled" in fields
    assert "cors_origins_configured" in fields


async def test_health_collect_reports_code_exec_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """collect() 实际填充该字段（与 settings 联动）。"""
    from app.modules.monitor.health.service import HealthService

    monkeypatch.setattr(settings, "SCHEDULER_ALLOW_CODE_EXEC", False)
    info = await HealthService.collect(None)
    assert info.code_exec_enabled is False
    assert set(info.model_dump()) >= {"name", "version", "environment", "db_status", "redis_status", "code_exec_enabled", "cors_origins_configured"}


# ── 6. 内置函数型任务：开关只关闭 exec，不关闭整个调度特性 ─────────────────────
#
# 背景：SCHEDULER_ALLOW_CODE_EXEC 默认 False 后，若没有"非 exec 的合法任务路径"，
# 升级等于停掉全部节点型定时任务。内置处理器白名单（func = "builtin:<模块名>[.<函数名>]"）
# 提供不经 exec 的执行路径，因此该开关只收敛 RCE 面。


def test_builtin_handler_runs_without_code_exec(monkeypatch: pytest.MonkeyPatch) -> None:
    """代码执行关闭时，内置函数型任务仍可正常调度（不经 exec）。"""
    monkeypatch.setattr(settings, "SCHEDULER_ALLOW_CODE_EXEC", False)
    result = SchedulerUtil._task_wrapper("job-builtin", "builtin:demo_handler")
    assert isinstance(result, dict) and result.get("message")


def test_builtin_handler_can_be_registered_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    """注册表可显式注册处理器（供业务侧接入自有白名单函数）。"""
    monkeypatch.setattr(settings, "SCHEDULER_ALLOW_CODE_EXEC", False)
    SchedulerUtil.register_builtin_handler("unit_test_probe", lambda *a, **k: "unit-ok")
    assert SchedulerUtil.resolve_builtin_handler("builtin:unit_test_probe") is not None
    assert SchedulerUtil._task_wrapper("job-custom", "builtin:unit_test_probe") == "unit-ok"


def test_builtin_reference_never_falls_back_to_exec(monkeypatch: pytest.MonkeyPatch) -> None:
    """非法/未知 builtin 引用必须报错，绝不能回退成 exec 执行。"""
    monkeypatch.setattr(settings, "SCHEDULER_ALLOW_CODE_EXEC", True)  # 即使开关打开也不允许回退
    for bad in ("builtin:../../etc/passwd", "builtin:nope.nope", "builtin:", "builtin:os.system"):
        with pytest.raises(ValueError):
            SchedulerUtil._task_wrapper("job-bad", bad)


def test_non_builtin_reference_is_not_treated_as_builtin() -> None:
    """普通代码块不会被误判成内置引用。"""
    assert SchedulerUtil.resolve_builtin_handler("def handler(): return 1") is None
    assert SchedulerUtil.resolve_builtin_handler(None) is None
