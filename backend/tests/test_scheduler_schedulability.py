"""定时任务可调度性回归测试（t15）。

覆盖四类情形：
1) ``SCHEDULER_ALLOW_CODE_EXEC=false`` 时，``builtin:`` 引用型任务**可以**创建/注册（不经 exec）；
2) 同一开关下，原始代码块型任务仍被拒绝，且提示里给出 ``builtin:`` 替代写法；
3) 节点/调度器任务列表返回 ``schedulable`` 状态字段，能区分「已启用但不可调度」与「正常可调度」；
4) 运行期把「已启用但不可调度」暴露为 WARN 日志（带节点/任务标识），不再静默失效。
"""

from types import SimpleNamespace
from typing import Any

import pytest
from apscheduler.triggers.date import DateTrigger
from loguru import logger

from app.common.enums import RET  # noqa: F401  (保持与其它测试一致的导入面)
from app.config.setting import settings
from app.core.ap_scheduler import SchedulerUtil
from app.core.base_schema import AuthSchema
from app.core.exceptions import CustomException
from app.modules.task.cronjob.job.schema import SchedulerJobSchema, SchedulerStatusSchema
from app.modules.task.cronjob.job.service import JobService
from app.modules.task.cronjob.node import service as node_service
from app.modules.task.cronjob.node.schema import NodeOutSchema
from app.modules.task.cronjob.node.service import _add_job_with_trigger

# ── 工具 ──────────────────────────────────────────────────────────────────────


class _EmptyScalars:
    """空结果集（节点列举时的执行日志查询用）。"""

    def scalars(self) -> "_EmptyScalars":
        return self

    def first(self) -> None:
        return None

    def all(self) -> list:
        return []


class _EmptySession:
    """execute 恒返回空结果的假会话。"""

    async def execute(self, *_args: object, **_kwargs: object) -> _EmptyScalars:
        return _EmptyScalars()


class _CapturedLogs:
    """临时 loguru sink：收集 WARN 及以上日志文本。"""

    def __init__(self) -> None:
        self.records: list[str] = []

    def __call__(self, message: Any) -> None:
        self.records.append(message.record["message"] if hasattr(message, "record") else str(message))

    def text(self) -> str:
        return "\n".join(self.records)


def _node(**overrides: Any) -> SimpleNamespace:
    """构造一个可用于注册的节点（不落库）。"""
    data: dict[str, Any] = {
        "id": 101,
        "name": "单元测试节点",
        "func": "builtin:demo_handler",
        "jobstore": "memory",
        "executor": "threadpool",
        "args": None,
        "kwargs": None,
        "coalesce": False,
        "max_instances": 1,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _cleanup_jobs(*job_ids: str) -> None:
    """清理注册到调度器里的测试任务（幂等）。"""
    for job_id in job_ids:
        try:
            SchedulerUtil.remove_job(job_id=job_id)
        except Exception:
            pass


# ── 1) builtin 引用：开关关闭时仍可创建/注册 ──────────────────────────────────


def test_builtin_reference_registers_while_code_exec_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """开关关闭时，builtin: 引用型任务能成功注册（且执行路径不经 exec）。"""
    monkeypatch.setattr(settings, "SCHEDULER_ALLOW_CODE_EXEC", False)
    _cleanup_jobs("unit-builtin-reg")
    try:
        job = _add_job_with_trigger(_node(id="unit-builtin-reg"), DateTrigger(run_date=None))
        assert str(job.id) == "unit-builtin-reg"
        # 执行入口同样放行，且返回内置处理器的结果（证明没走 exec）
        result = SchedulerUtil._task_wrapper("unit-builtin-reg", job.args[1])
        assert isinstance(result, dict) and result.get("message")
    finally:
        _cleanup_jobs("unit-builtin-reg")


def test_builtin_reference_is_reported_as_schedulable(monkeypatch: pytest.MonkeyPatch) -> None:
    """可调度性判定：builtin: 引用为可调度，未知内置则不可调度并给出原因。"""
    monkeypatch.setattr(settings, "SCHEDULER_ALLOW_CODE_EXEC", False)
    assert SchedulerUtil.describe_schedulability("builtin:demo_handler") == (True, None)
    schedulable, reason = SchedulerUtil.describe_schedulability("builtin:not_exist.handler")
    assert schedulable is False
    assert reason and "内置处理器不可用" in reason


# ── 2) 原始代码块：开关关闭时仍被拒绝，并提示 builtin 替代 ─────────────────────


def test_raw_code_block_is_rejected_with_builtin_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    """原始代码块被拒绝，提示必须点명 SCHEDULER_ALLOW_CODE_EXEC 与 builtin: 替代写法。"""
    monkeypatch.setattr(settings, "SCHEDULER_ALLOW_CODE_EXEC", False)
    node = _node(func="def handler(*args, **kwargs):\n    return 1\n")
    with pytest.raises(CustomException) as excinfo:
        _add_job_with_trigger(node, DateTrigger(run_date=None))
    message = str(excinfo.value)
    assert "SCHEDULER_ALLOW_CODE_EXEC" in message
    assert "builtin:" in message
    assert excinfo.value.status_code == 400  # 客户端/策略类拒绝，不是 500


def test_raw_code_block_still_allowed_when_explicitly_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """开关显式打开时，原始代码块仍可注册（本次改动没有收紧既有能力）。"""
    monkeypatch.setattr(settings, "SCHEDULER_ALLOW_CODE_EXEC", True)
    _cleanup_jobs("unit-raw-reg")
    try:
        job = _add_job_with_trigger(_node(id="unit-raw-reg", func="def handler(*a, **k):\n    return 'ok'\n"), DateTrigger(run_date=None))
        assert str(job.id) == "unit-raw-reg"
        assert SchedulerUtil.describe_schedulability(SchedulerUtil.job_code_block(job)) == (True, None)
    finally:
        _cleanup_jobs("unit-raw-reg")


def test_empty_func_is_rejected_before_schedulability_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """空 func 仍是"不能为空"（保持既有报错语义），不被可调度性信息覆盖。"""
    monkeypatch.setattr(settings, "SCHEDULER_ALLOW_CODE_EXEC", False)
    with pytest.raises(ValueError, match="不能为空"):
        _add_job_with_trigger(_node(func="   "), DateTrigger(run_date=None))


# ── 3) 列表状态字段：区分「已启用但不可调度」与「正常可调度」 ─────────────────────


async def test_node_list_exposes_schedulable_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """节点列表：原始代码块 + 开关关闭 → schedulable=false 且带原因；builtin → true。"""
    monkeypatch.setattr(settings, "SCHEDULER_ALLOW_CODE_EXEC", False)
    node_service._WARNED_UNSCHEDULABLE.clear()
    monkeypatch.setattr(SchedulerUtil, "get_jobs", classmethod(lambda cls, jobstore=None: []))

    service = node_service.NodeService(AuthSchema(), _EmptySession())  # type: ignore[arg-type]
    raw_item = NodeOutSchema(id=201, name="原始代码块节点", status=0, func="def handler(): pass")
    builtin_item = NodeOutSchema(id=202, name="内置函数节点", status=0, func="builtin:demo_handler")
    await service._enrich_runtime([raw_item, builtin_item])

    assert raw_item.schedulable is False
    assert raw_item.unschedulable_reason and "builtin:" in raw_item.unschedulable_reason
    assert builtin_item.schedulable is True
    assert builtin_item.unschedulable_reason is None


async def test_node_list_marks_disabled_node_schedulable_but_via_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """停用节点（status=1）不触发告警，但仍如实返回 schedulable 字段。"""
    monkeypatch.setattr(settings, "SCHEDULER_ALLOW_CODE_EXEC", False)
    node_service._WARNED_UNSCHEDULABLE.clear()
    monkeypatch.setattr(SchedulerUtil, "get_jobs", classmethod(lambda cls, jobstore=None: []))
    logs = _CapturedLogs()
    sink_id = logger.add(logs, level="WARNING")

    service = node_service.NodeService(AuthSchema(), _EmptySession())  # type: ignore[arg-type]
    disabled_item = NodeOutSchema(id=203, name="停用节点", status=1, func="def handler(): pass")
    try:
        await service._enrich_runtime([disabled_item])
    finally:
        logger.remove(sink_id)

    assert disabled_item.schedulable is False
    assert "id=203" not in logs.text()  # 未启用不告警，避免噪音


def test_scheduler_job_list_and_status_expose_schedulability(monkeypatch: pytest.MonkeyPatch) -> None:
    """调度器任务列表 / 状态：带 schedulable 与 unschedulable_count（已注册但不可执行）。"""
    monkeypatch.setattr(settings, "SCHEDULER_ALLOW_CODE_EXEC", True)
    _cleanup_jobs("unit-sched-raw")
    try:
        _add_job_with_trigger(
            _node(id="unit-sched-raw", func="def handler(*a, **k):\n    return 'ok'\n"),
            DateTrigger(run_date=None),
        )
        # 打开时：可调度
        items = {item.id: item for item in JobService.get_scheduler_jobs()}
        assert items["unit-sched-raw"].schedulable is True
        assert JobService.get_scheduler_status().unschedulable_count == 0

        # 关闭后：同一任务变成不可执行，且状态里计数可见
        monkeypatch.setattr(settings, "SCHEDULER_ALLOW_CODE_EXEC", False)
        items = {item.id: item for item in JobService.get_scheduler_jobs()}
        assert items["unit-sched-raw"].schedulable is False
        assert items["unit-sched-raw"].unschedulable_reason
        status = JobService.get_scheduler_status()
        assert status.code_exec_enabled is False
        assert status.unschedulable_count >= 1
    finally:
        _cleanup_jobs("unit-sched-raw")


def test_scheduler_schemas_have_expected_fields() -> None:
    """契约字段存在性（前端/运维依赖）。"""
    assert {"status", "is_running", "job_count", "code_exec_enabled", "unschedulable_count"} <= set(SchedulerStatusSchema.model_fields)
    assert {"id", "name", "trigger", "next_run_time", "status", "schedulable", "unschedulable_reason"} <= set(SchedulerJobSchema.model_fields)
    assert {"schedulable", "unschedulable_reason"} <= set(NodeOutSchema.model_fields)


# ── 4) 运行期可见性：WARN 日志带具体标识，不静默失效 ─────────────────────────


async def test_unschedulable_enabled_node_logs_warning_with_identifier(monkeypatch: pytest.MonkeyPatch) -> None:
    """已启用但不可调度的节点：WARN 日志必须带节点 id 与原因，且同一原因只打一次。"""
    monkeypatch.setattr(settings, "SCHEDULER_ALLOW_CODE_EXEC", False)
    node_service._WARNED_UNSCHEDULABLE.clear()
    monkeypatch.setattr(SchedulerUtil, "get_jobs", classmethod(lambda cls, jobstore=None: []))
    logs = _CapturedLogs()
    sink_id = logger.add(logs, level="WARNING")

    service = node_service.NodeService(AuthSchema(), _EmptySession())  # type: ignore[arg-type]
    item = NodeOutSchema(id=301, name="不可调度节点", status=0, func="def handler(): pass")
    try:
        await service._enrich_runtime([item])
        await service._enrich_runtime([item])  # 第二次不应重复告警
    finally:
        logger.remove(sink_id)

    text = logs.text()
    assert "id=301" in text
    assert "不可调度" in text
    assert "SCHEDULER_ALLOW_CODE_EXEC" in text
    assert text.count("id=301") == 1, f"同一节点同一原因重复告警：{text}"


def test_scheduler_status_logs_warning_for_registered_but_dead_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    """调度器状态查询：已注册但不可执行的任务要打 WARN（带 job id）。"""
    monkeypatch.setattr(settings, "SCHEDULER_ALLOW_CODE_EXEC", True)
    _cleanup_jobs("unit-sched-log")
    try:
        _add_job_with_trigger(
            _node(id="unit-sched-log", func="def handler(*a, **k):\n    return 'ok'\n"),
            DateTrigger(run_date=None),
        )
        monkeypatch.setattr(settings, "SCHEDULER_ALLOW_CODE_EXEC", False)
        logs = _CapturedLogs()
        sink_id = logger.add(logs, level="WARNING")
        try:
            status = JobService.get_scheduler_status()
        finally:
            logger.remove(sink_id)
        assert status.unschedulable_count >= 1
        assert "unit-sched-log" in logs.text()
    finally:
        _cleanup_jobs("unit-sched-log")


# ── 5) 创建/更新/手动执行入口（create/update → register_node_job）──────────────


def test_register_node_job_accepts_builtin_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """创建/更新路径（register_node_job）在开关关闭时能注册 builtin: 引用型任务。"""
    monkeypatch.setattr(settings, "SCHEDULER_ALLOW_CODE_EXEC", False)
    node = _node(
        id="unit-reg-builtin",
        trigger="date",
        trigger_args="2099-01-01 00:00:00",
        start_date=None,
        end_date=None,
        status=0,
    )
    try:
        job = node_service.register_node_job(node)
        assert job is not None and str(job.id) == "unit-reg-builtin"
    finally:
        node_service.unregister_node_job("unit-reg-builtin")


def test_register_node_job_rejects_raw_code_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """创建/更新路径在开关关闭时拒绝原始代码块，并给出 builtin 替代写法（不再静默不注册）。"""
    monkeypatch.setattr(settings, "SCHEDULER_ALLOW_CODE_EXEC", False)
    node = _node(
        id="unit-reg-raw",
        trigger="date",
        trigger_args="2099-01-01 00:00:00",
        start_date=None,
        end_date=None,
        status=0,
        func="def handler(*args, **kwargs):\n    return 1\n",
    )
    with pytest.raises(CustomException) as excinfo:
        node_service.register_node_job(node)
    message = str(excinfo.value)
    assert "SCHEDULER_ALLOW_CODE_EXEC" in message and "builtin:" in message
    assert SchedulerUtil.get_job(job_id="unit-reg-raw") is None  # 未注册成功


def test_run_node_once_allows_builtin_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """手动执行入口：开关关闭时 builtin 引用仍可排程执行。"""
    monkeypatch.setattr(settings, "SCHEDULER_ALLOW_CODE_EXEC", False)
    node = _node(id="unit-once-builtin", trigger=None, trigger_args=None, start_date=None, end_date=None, status=0)
    temp_job_id = node_service.run_node_once(node)
    try:
        assert temp_job_id.startswith("unit-once-builtin")
        assert SchedulerUtil.get_job(job_id=temp_job_id) is not None
    finally:
        node_service.unregister_node_job(temp_job_id)


def test_run_node_once_rejects_raw_code_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """手动执行入口：开关关闭时原始代码块被拒绝并提示 builtin 写法。"""
    monkeypatch.setattr(settings, "SCHEDULER_ALLOW_CODE_EXEC", False)
    node = _node(id="unit-once-raw", trigger=None, func="def handler(): return 1", status=0)
    with pytest.raises(CustomException) as excinfo:
        node_service.run_node_once(node)
    assert "builtin:" in str(excinfo.value)
