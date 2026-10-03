# 需求覆盖审计报告：REQUIREMENTS.md vs 实现代码

- 审计对象：`/Users/tao/workspace/FastapiAdmin`（FastAPI 后端 + Vue3 Web 端 + uniapp 移动端）
- 基线文档：`REQUIREMENTS.md`（3135 行，标题「SaaS 多租户平台需求文档 v3.6.0」，最后更新 2026-06-03）
- 审计日期：本轮只读摸底，未改动任何仓库文件（仅新增本报告）
- 审计方式：模块/路由/表结构/权限点的**代码基线盘点 + 文档映射**，非逐行通读

---

## 0. 一句话结论

**`REQUIREMENTS.md` 描述的是一个 SaaS 多租户平台，仓库里实际存在的是一套单租户 RBAC 后台框架（FastapiAdmin 上游形态）。多租户能力（tenant_id 行级隔离、平台/租户/用户三层权限、Tenant/Package/Plugin/Order/Email/Invoice/AuditLog/Dashboard）在三个端的代码里"零实现"，不是"部分实现"。**

可验证的硬事实：

```
$ grep -ril "tenant" backend/app | wc -l          → 0
$ grep -ril "tenant" frontend/web/src frontend/app/src | wc -l → 0
$ find backend/app -iname "*tenant*"              → （无结果）
```

`REQUIREMENTS.md` 的引入方式也印证了这一点：

```
$ git show --stat --no-renames 45a00334
 CHANGELOG.md    | 3136 ---------
 REQUIREMENTS.md | 3136 +++++++++
$ git log --oneline -S "SaaS 多租户平台需求文档" -- REQUIREMENTS.md
45a00334 docs: add SaaS multi-tenant platform requirements
```

需求文档是一次**纯文档提交**（内容即原 `CHANGELOG.md`，`R100` 重命名），没有任何配套的实现提交。1192 个提交中不存在租户功能实现。

---

## 1. 审计范围声明（重要，避免过度解读）

### 1.1 已实际核对（逐行阅读）

| 范围 | 文档行号 | 深度 |
|------|---------|------|
| Part 1 全部（概述/角色定义/架构/数据隔离模型/Mixin 体系） | 1–205 | 逐行读 |
| §11 Notice / §12 Params / §13 LoginLog / §14 OperationLog | 616–785 | 逐行读 |
| §15 Tenant 数据模型/创建删除流程/状态机 | 785–905 | 逐行读 |
| §17 Ticket / §18 Plugin / §19 到期处理 | 1071–1258 | 逐行读 |
| §20 API 接口汇总（20.1–20.25 全部表格） | 1262–1573 | 逐行读 |
| §21 数据库表结构 / §22 安全性要求 | 1575–1682 | 逐行读 |
| §28 未来扩展 / NFR / §29 术语表 / §30 变更记录 | 2105–2195 | 逐行读 |
| §5.3 User 业务规则、§4 Auth 全章 | 208–364 | 逐行读 |

### 1.2 只做结构性核对（未逐行读正文）

| 范围 | 处理方式 |
|------|---------|
| §23 Email（1684–1770）、§24 Order（1770–1917）、§25 SelfService（1917–1980）、§26 APIUsage（1980–2033）、§27 UserInvite（2033–2109） | 读了 §20.18–§20.22 的接口表 + 标题/表名清单；正文表格未逐行读。**结论依据是"代码里完全没有对应实现文件/表/路由"这一可穷举事实**，不依赖正文细节 |
| §31–§37（Part 4 Plugin 子模块，2197–2944） | 读了全部标题 + §32.3 业务规则 + §32.4/§33.4/§35.4 端点表；其余小节只做标题与实现映射 |
| §38 Invoice（2948–3028）、§39 AuditLog（3028–3107）、§40 Dashboard（3107–3135） | 读标题 + §20.23–§20.25 接口表；正文数据模型未逐行读 |

### 1.3 未核对

- 前端（`frontend/web/src/**`、`frontend/app/src/**`）**逐页面**行为核对：本报告只做了目录级/接口调用级覆盖统计，未逐页读 Vue 组件。
- 移动端（uniapp）业务流程、`subPages` 内的交互细节。
- 运行时行为（未启动服务、未跑测试、未连数据库）。所有"表存在"结论来自 `__tablename__` 声明与 `sql/*.json` 种子，**不代表迁移脚本或线上库状态**。
- `backend/app/alembic/versions/` 为空目录（仅 `__init__.py`），因此"声明了表"是否等于"数据库里有表"存疑（见 §8 存疑清单）。

**本报告不声称已逐条核对 3135 行，也不声称任何模块 100% 覆盖。**

---

## 2. 基线事实：文档清单 vs 代码清单

### 2.1 文档声明的模块（§1.4，行 33–58）

`Auth, User, Role, Dept, Position, Menu, Dict, Notice, Params, LoginLog, OperationLog, Tenant, Package, Ticket, Plugin, Cronjob, Workflow, AI Chat, CodeGen, Invoice, AuditLog, Dashboard`（22 个）

> §1.4 表本身**遗漏**了文档 §23–§27 已定义的 Email / Order / TenantSelfService / APIUsage / UserInvite 五个模块，以及 §36 Monitor / §37 Common（见 §8.1）。

### 2.2 代码实际存在的模块

```
backend/app/modules/
├── system/   auth user role menu dept position dict params notice ticket versions log
├── monitor/  cache health online server
├── task/     cronjob/{job,node}  storage/{browse,node,transfer,workflow}
├── ai/       chat
├── generator/ gencode
└── common/   file
backend/app/plugin/
└── module_example/demo
```

模块数：`app/modules` 下 26 个业务模块目录 + 1 个插件模块；路由域 6 个（`/system /monitor /task /ai /generator /common`，见 `backend/app/api/v1/routers.py:32-64`）。

### 2.3 数量对照

| 指标 | 文档 | 代码 | 差异 |
|------|------|------|------|
| 章节数 | 40 章 / 5 个 Part | — | 任务简报称"3 个 Part"，实际是 5 个（Part 4 = §31–37，Part 5 = §38–40） |
| API 端点行 | 430 行 / 260 个唯一路径 | 209 个已注册处理函数（`app/modules` 200 + `app/plugin` 9） | 见 §5 |
| 数据表 | 约 40 张（§21 全部小节） | 29 张（`__tablename__` 去重） | 见 §6 |
| 权限标识 | 种子菜单 123 个 | 代码 121 个 | 4 个"菜单有代码无" + 2 个"代码有菜单无"（§7.1） |
| 租户相关实现 | 贯穿全文 | **0** | — |

---

## 3. 覆盖矩阵：Part 2 核心业务模块

状态定义：**已实现** = 文档要求的主要端点/模型均存在；**部分实现** = 主链路可用但与文档契约有实质差异或缺项；**缺失** = 无对应代码；**存疑** = 证据不足。

| 模块 | 需求章节（行号） | 状态 | 证据（文件:行 / 路由） | 缺口要点 |
|------|-----------------|------|------------------------|---------|
| **Auth** | §4（208–286） | 部分实现 | `app/modules/system/auth/controller.py:37-172`；`/auth/login` `/auth/token/refresh` `/auth/captcha/get` `/auth/captcha/slider/complete` `/auth/logout` `/auth/oauth/{provider}/login` `/auth/oauth/{provider}/callback` `/auth/wx-login` `/auth/wx-phone-login` `/auth/wx-qrcode/generate` | 缺 `/auth/register`（自动建租户）、`/auth/select-tenant/{id}`、`/auth/tenants`、`/auth/forgot-password`、`/auth/auto-login*`；缺"多租户临时/正式 token"机制；JWT 载荷与文档不符（§7.4） |
| **User** | §5（288–364） | 部分实现 | `app/modules/system/user/controller.py:32-193`；模型 `app/modules/system/user/model.py:62-108` | 无 `tenant_id`；无 `platform_user_tenant` 关联表；`/user/current/info/update` vs 文档 `/user/current/update`；`/user/password/reset/{id}` vs 文档 `/user/password/reset`；导入密码策略完全不符（§7.5）；§5.4"菜单与租户可用菜单取交集"无实现 |
| **Role** | §6（366–415） | 部分实现 | `app/modules/system/role/controller.py`；`RoleModel.data_scope` `app/modules/system/role/model.py:72` | 缺 `PUT /role/menus`（只有 `/role/permission`）；无 `tenant_id`；`data_scope` 语义与文档冲突且实现只认 1/2/3（§7.3，**安全相关**） |
| **Dept** | §7（415–459） | 部分实现 | `app/modules/system/dept/controller.py:18-70` | 文档 `GET /dept/list` → 代码只有 `GET /dept/tree`；无 `tenant_id` |
| **Position** | §8（459–487） | 已实现（接口层） | `app/modules/system/position/controller.py:19-95`，含文档未列的 `/position/options` `/position/export` | 无 `tenant_id`；无配额（max_users 之类）联动 |
| **Menu** | §9（487–550） | 部分实现 | `MenuModel` `app/modules/system/menu/model.py:14`（表名 `sys_menu`）；`/menu/tree` | 表名 `sys_menu` vs 文档 `platform_menu`；文档 `GET /menu/list` → 代码 `/menu/tree`；菜单模型字段远多于文档（`scope/link/is_iframe/...`）但文档未定义 |
| **Dict** | §10（550–616） | 部分实现 | `app/modules/system/dict/model.py:10,23`（`sys_dict_type`/`sys_dict_data`） | `__platform_data_shared__` 机制**完全不存在**（§3.2 文档核心机制）；无 `tenant_id`；无 `UNIQUE(tenant_id, dict_type)` |
| **Notice** | §11（616–666） | 部分实现 | `app/modules/system/notice/model.py:10`（仅 `sys_notice`） | **`sys_notice_read` 表不存在**；缺 `/notice/read/{id}` `/notice/read-all` `/notice/unread-count`；多设备已读同步无实现 |
| **Params** | §12（666–702） | 部分实现 | `app/modules/system/params/controller.py:19-31` | 只有 `PUT /param/update/{id}` 和 `GET /param/info`；缺 list/detail/create/delete/status-batch；`/param/info` 走公开路径（§7.6） |
| **LoginLog** | §13（702–733） | 部分实现 | `app/modules/system/log/model.py`（表名 `sys_login_log`）；`/log/login/*` | 表名 `sys_login_log` vs 文档 `platform_login_log`；路径 `/system/log/login/*` vs 文档 `/platform/loginlog/*`；权限 `module_system:login_log:*` vs 文档 `module_platform:loginlog:*` |
| **OperationLog** | §14（733–785） | 部分实现 | `sys_operation_log` 表；`OperationLogRoute`；`/log/operation/*` | 路径 `/system/log/operation/*` vs 文档 `/system/operationlog/*`；权限 `module_system:log:*` vs 文档 `module_system:operationlog:*`；**§14.5 日志保留/清理策略零实现**（无 retention 配置、无 cleanup 定时任务） |
| **Tenant** | §15（785–987） | **缺失** | 无 `platform_tenant`、无 `/tenant/*`、无 `TenantMixin` | 生命周期状态机、配额、配置、用户关联、租户菜单授权全部缺失。**这是全平台最关键的缺口** |
| **Package** | §16（987–1071） | **缺失** | 无 `platform_package`、无 `/platform/package/*` | 套餐-菜单合并逻辑、配额继承、变更预览全部缺失 |
| **Ticket** | §17（1071–1126） | 部分实现 | `app/modules/system/ticket/model.py:17`（`sys_ticket`）；状态机 `app/modules/system/ticket/service.py:48-76` | 表名 `sys_ticket` vs 文档 `platform_ticket`；**无 `tenant_id`**（文档明确要求 TenantMixin）；`PUT /ticket/batch` vs 文档 `/ticket/batch/status`；缺 `close_reason/closed_time/closed_by`（v3.3.0 变更记录声称已加，代码无）；代码多出 `/ticket/stats` `/ticket/export` `/ticket/{id}/comments` 与 `sys_ticket_comment` 表（文档未定义） |
| **Plugin** | §18（1126–1194） | **缺失** | `app/plugin/module_example/plugin.toml` 仅是静态元数据；`app/core/discover.py` 只做路由自动注册 | 无 `platform_plugin` 注册表、无 `platform_tenant_plugin`、无 `/plugin/*` 端点、无安装/卸载、无 `enabled` 状态、无依赖解析。文档 §18.2 的 12 个字段无一存在 |
| **到期处理** | §19（1196–1258） | **缺失** | `grep check_tenant_expiry / expire_after_days / archive_after_days / grace_period` → 0 命中 | 无 `check_tenant_expiry` 定时任务、无宽限期/暂停/过期/归档状态流转、无 30/7/1 天提醒 |

---

## 4. 覆盖矩阵：Part 4 / Part 5（插件与商业运营）

| 模块 | 需求章节（行号） | 状态 | 证据 | 缺口要点 |
|------|-----------------|------|------|---------|
| **AI Chat** | §31（2201–2253） | 已实现（超出文档） | `app/modules/ai/chat/{controller,crud,service,schema}.py`；`/ai/chat/*` | 代码多出 AI 模型配置管理（`/chat/model*`，5 个端点）文档未定义；无 `tenant_id` |
| **Cronjob** | §32（2253–2329） | 部分实现（含**安全项**） | `app/modules/task/cronjob/{job,node}/`；`task_corn_job` / `task_cornjob_node` | 表名 `task_corn_job`/`task_cornjob_node`（`corn` 拼写）vs 文档 `task_job`/`task_node`；权限 `module_task:cronjob:job:xxx` / `module_task:cronjob:node:xxx` vs 文档 `module_task:cronjob:*`；**§32.3 处理器白名单 + `platform_handler_registry` 零实现，`func` 字段就是任意代码块**（§7.2） |
| **Workflow** | §33（2329–2397） | 部分实现（契约不同） | `app/modules/task/storage/workflow/`；表 `task_storage_workflow` / `_node` / `_edge` | 表名与文档 `task_workflow`/`task_workflow_node_type` 完全不同；端点 `/task/storage/workflow/*` vs 文档 `/workflow/flow/*`、`/workflow/nodes/*`、`/workflow/node-type/*`（文档 3 组路径均不存在） |
| **CodeGen** | §34（2397–2479） | 部分实现 | `app/modules/generator/gencode/`；`/generator/gencode/*` | 端点路径与文档 `/gencode/*` 不一致（缺 `/generator` 前缀时无法匹配）；文档端点名 `create/current/select/gen/{id}/zip/{id}/status/batch` 均不存在，代码用 `output/{table}` `preview/{id}` `batch/output` 等 |
| **Demo** | §35（2479–2539） | 部分实现 | `app/plugin/module_example/demo/`；`/example/demo/*`（9 个端点，前缀映射正确） | 只有 `DemoModel`（`example_demo`），**文档 §35.2 的 `Demo01Model`（`example_demo01`）不存在**，对应 `/example/demo01/*` 6 个端点全部缺失 |
| **Monitor** | §36（2539–2802） | 部分实现 | online `app/modules/monitor/online/`、cache、server，`/monitor/*` | **§36.4 资源管理（resource）整体缺失**：`/monitor/resource/*` 9 个端点无实现，代码用 `task/storage/browse/*` 代替（语义与路径都不同）；health 路径不符（§7.7）；无 `/metrics`；代码多出 `/online/current` `/online/stats` 文档未定义 |
| **Common** | §37（2802–2944） | 部分实现 | `app/modules/common/file/controller.py:18,37`；`/monitor/health/*` | 文档 `/file/upload` → 代码 `/common/file/upload`；§37.4 Prometheus `/metrics` **不存在**（只在 `app/config/setting.py:200` 白名单里出现） |
| **Invoice** | §38（2948–3028） | **缺失** | `grep -ril invoice backend/app` → 0 | 无 `platform_invoice` 表、无 `/tenant/invoice/*`、无 `/platform/invoice/*` |
| **AuditLog** | §39（3028–3107） | **缺失** | `grep -ril audit_log backend/app` → 0 | 无 `platform_audit_log`、无 `/platform/audit/*`、无 13 类审计事件、无 3 年保留策略 |
| **Dashboard** | §40（3107–3135） | **缺失** | 仅有 `GET /monitor/online/stats`（`app/modules/monitor/online/controller.py:62`，权限 `module_monitor:dashboard:query`） | 无 `/platform/dashboard/{overview,revenue,tenants,api-usage}`；"权限点叫 dashboard，实现的却是在线用户统计" |
| **Email** | §23（1684–1770） | **缺失** | `grep -ril smtp backend/app` → 0；`grep EmailConfig` → 0 | 无 `platform_email_config/template/log` 三表、无 `/platform/email/*` 6 个端点、无发送服务、无降级策略；牵连注册/重置/邀请/到期提醒全部无法按文档交付 |
| **Order / 支付 / 退款** | §24（1770–1917） | **缺失** | `grep -ril refund` → 0；`grep order` 命中均为 `order_by`/`order` 排序字段 | 无 `platform_order`/`platform_payment_record`/`platform_refund`、无 `/platform/order/*`、`/platform/payment/*`、`/platform/refund/*`。`app/common/enums.py:110` 有 `OrderTypeEnum` 但无任何使用方（悬空枚举） |
| **TenantSelfService** | §25（1917–1980） | **缺失** | 无 `/tenant/package/*`、`/tenant/order/*` | — |
| **APIUsage** | §26（1980–2033） | **缺失** | `grep -ril api_usage` → 0 | 无 `platform_api_usage_daily`、无 4 个统计端点、无异常检测、无限流联动 |
| **UserInvite** | §27（2033–2109） | **缺失** | `grep -ril invite` 仅命中微信小程序 `scene="invite=xxx"` 字符串 | 无 `platform_invite_record`、无 `/tenant/invite/*`、无 `/invite/validate` 与 `/invite/accept` |

---

## 5. 覆盖矩阵：Part 1 架构与基础设施

| 需求条目 | 章节（行号） | 状态 | 证据 | 缺口要点 |
|---------|-------------|------|------|---------|
| 分层架构 Controller→Service→CRUD→Model | §2.1（64–82） | 已实现 | `app/modules/*/` 下的 `controller.py`、`service.py`、`crud.py`、`model.py`、`schema.py` | 结构一致，但 `monitor/*`、`common/file`、`system/auth` 无 `crud.py`/`model.py`（合理，无独立表） |
| 请求链路含"租户中间件(解析 token，设置 ContextVar)" | §2.2（84–90） | **缺失** | `app/core/middlewares.py` 只有 CORS/日志/GZip/IP 黑白名单；无租户中间件、无 ContextVar | 链路中"ORM 自动注入 tenant_id → ContextVar 清理"两步不存在 |
| 模块目录规范 `module_xxx/` | §2.3（92–104） | 部分实现 | 实际为 `app/modules/<域>/<模块>/`；`app/core/discover.py:10` 只对 `app/plugin/module_*` 生效 | 系统模块不在 `app/plugin` 下，文档目录规范与实际不符 |
| 平台资源（无 tenant_id）：platform_menu/package/plugin/tenant | §3.1（110–133） | **缺失** | 4 张表全部不存在；菜单实为 `sys_menu` | — |
| 租户资源（含 tenant_id，ORM 自动过滤）：sys_user/role/dept/position/notice/param/log、platform_ticket | §3.1（119–128） | **缺失** | `sys_user`/`sys_role`/`sys_dept`/`sys_position`/`sys_notice`/`sys_param`/`sys_operation_log` 均**无 `tenant_id` 列**；`sys_ticket` 无 `tenant_id` | 9 张表缺 tenant_id |
| 平台共享资源（`__platform_data_shared__`，tenant_id=1 对所有租户可读） | §3.1（130–133）、§3.2（152）、§3.3（196–200） | **缺失** | `grep __platform_data_shared__` → 0 | `sys_dict_type`/`sys_dict_data` 无 tenant_id、无该标记、无 CRUD 层 `__tenant_condition` |
| ORM 事件层 `tenant_filter.py`（`do_orm_execute` 注入 WHERE tenant_id） | §3.2（137–152） | **缺失** | 文件不存在；`grep do_orm_execute` → 0 | — |
| CRUD 层 `__build_conditions` / `__tenant_condition` 二次确认 | §3.2（140） | **缺失** | `app/core/base_crud.py:33` `CRUDBase` 无租户条件方法 | — |
| 权限策略层 `permission.py` 5 种策略枚举 | §3.2（154–162） | 部分实现 | `app/core/permission.py:12-124` | 只有 `data_scope` 一种策略（1/2/3）；文档的 `ROLE_BASED/DEPT_BASED/USER_ROLE/SELF_ONLY/DATA_SCOPE` 五枚举不存在 |
| `data_scope` 5 档语义 | §3.2（164–172） | **冲突** | `app/core/permission.py:16-18`（1=SELF, 2=DEPT_AND_CHILD, 3=ALL）；`app/core/validator.py:314-322`（1–5）；`app/modules/system/role/model.py:72` | 见 §7.3 |
| Mixin 体系 `ModelMixin` / `TenantMixin` / `UserMixin` | §3.3（174–181） | 部分实现 | `app/core/base_model.py:42`（ModelMixin）、`:124`（UserMixin）；**无 `TenantMixin`** | 缺 `TenantMixin`，连带 `platform_tenant` FK 不存在 |
| 角色定义：超管 / 租户管理员(owner/admin) / 租户用户 | §1.3（25–31） | 部分实现 | `UserModel.is_superuser` `app/modules/system/user/model.py:73`；种子角色 `SUPER_ADMIN/ADMIN/USER` `backend/sql/sys_role.json` | 只有"超管/普通"二元；**无 owner/admin 租户角色概念**；文档"租户范围"列无对应字段 |
| 权限分层：平台层→租户层→用户层 | §1.2（21） | **缺失** | `app/core/dependencies.py:192-234` `AuthPermission` 只做用户层 RBAC（角色→菜单 permission 集合） | 无平台层（菜单/套餐/插件）、无租户层（可见菜单/配额/配置）；`is_superuser` 是唯一"平台层"体现 |
| §22 安全性 13 条 | §22（1663–1681） | 部分实现 | 逐条见 §7.8 | 4 条与文档不符/未实现 |

---

## 6. 覆盖矩阵：数据表（§21）

代码实际表名（`__tablename__` 去重，共 29 张）：

```
sys_user sys_role sys_menu sys_dept sys_position sys_dict_type sys_dict_data
sys_notice sys_param sys_login_log sys_operation_log sys_ticket sys_ticket_comment
sys_version sys_user_roles sys_user_positions sys_role_menus sys_role_depts
task_corn_job task_cornjob_node
task_storage_node task_storage_transfer task_storage_transfer_step
task_storage_workflow task_storage_workflow_node task_storage_workflow_edge
gen_table gen_table_column example_demo  (+ apscheduler_jobs)
```

| 文档表名（§21） | 行号 | 实现中的对应 | 状态 |
|----------------|------|-------------|------|
| `platform_tenant` | 1581 | — | 缺失 |
| `platform_package` / `platform_package_menu` | 1582-1583 | — | 缺失 |
| `platform_menu` | 1584 | `sys_menu` | **命名不符** |
| `platform_plugin` | 1585 | — | 缺失 |
| `platform_email_config/template/log` | 1586-1588 | — | 缺失 |
| `platform_order` / `platform_payment_record` | 1589-1590 | — | 缺失 |
| `platform_tenant_menu` / `platform_tenant_plugin` | 1596-1597 | — | 缺失 |
| `platform_user_tenant` | 1598 | — | 缺失 |
| `platform_invite_record` | 1604 | — | 缺失 |
| `platform_api_usage_daily` | 1605 | — | 缺失 |
| `sys_user`（UNIQUE(tenant_id,username)） | 1611 | `sys_user`（`username` 全局 UNIQUE） | 部分：唯一键缺 tenant 维度 |
| `sys_role`（UNIQUE(tenant_id,code)） | 1612 | `sys_role`（`code` 全局 UNIQUE） | 同上 |
| `sys_dept`（UNIQUE(tenant_id,code)） | 1613 | `sys_dept` | 同上 |
| `sys_position` / `sys_notice` / `sys_param` / `sys_operation_log` | 1614-1617 | 同名存在 | 缺 tenant_id |
| `platform_login_log` | 1618 | `sys_login_log` | **命名不符** |
| `platform_ticket` | 1619 | `sys_ticket` | **命名不符** |
| `sys_dict_type` / `sys_dict_data`（`__platform_data_shared__`） | 1625-1626 | 同名存在 | 缺 tenant_id 与共享机制 |
| `sys_user_roles` / `sys_user_positions` / `sys_role_menus` / `sys_role_depts` | 1632-1635 | 同名存在 | 一致 |
| `sys_notice_read` | 1636 | — | 缺失 |
| `task_workflow` / `task_workflow_node_type` | 1642-1643 | `task_storage_workflow` / `_node` / `_edge` | **命名与结构不符** |
| `task_node` / `task_job` | 1644-1645 | `task_cornjob_node` / `task_corn_job` | **命名不符（且 `corn` 拼写可疑）** |
| `gen_table` / `gen_table_column` | 1646-1647 | 同名存在 | 一致 |
| `example_demo` | 1648 | 同名存在 | 一致 |
| `example_demo01` | 1649 | — | 缺失 |
| `platform_invoice` / `platform_refund` / `platform_audit_log` | 1657-1659 | — | 缺失 |
| **代码存在但文档未定义** | — | `sys_version`、`sys_ticket_comment`、`task_storage_node/transfer/transfer_step` | 4 张表无需求依据 |

---

## 7. 需求与代码契约不一致清单

> 本节只列"同一件事，文档说 A，代码做 B"的地方。整块缺失的模块见 §3/§4。

### 7.1 权限标识与种子菜单（可自动比对，实测结果）

比对方法：提取全部 `AuthPermission([...])` 权限串（含装饰器参数与 `dependencies=[Security(...)]` 两种写法）与 `backend/sql/sys_menu.json` 的 `permission` 字段。

```
代码权限点：121    种子菜单权限点：123
```

**A. 菜单里有、代码里没有（4 个 → 授权后是"死权限"）**

| 权限标识 | 种子菜单用途 | 代码实况 |
|---------|-------------|---------|
| `module_monitor:cache:detail` | 缓存监控详情按钮 | `app/modules/monitor/cache/controller.py` 无任何 `:detail` 端点 |
| `module_swagger:docs:query` | 接口管理→Swagger文档 菜单 | 后端无 `/swagger` 域路由（`app/api/v1/routers.py:32-64` 无该域） |
| `module_system:log:detail` | 操作日志详情按钮 | 日志详情用的是 `module_system:log:query`（`app/modules/system/log/controller.py:62`） |
| `module_system:param:query` | 参数管理查询按钮 | `/param/info` 无权限校验；`/param/update/{id}` 用 `:update` |

**B. 代码里有、种子菜单没有（2 个 → 无法通过 UI 授权，只有超管能用）**

| 权限标识 | 位置 | 影响 |
|---------|------|------|
| `module_common:file:upload` | `app/modules/common/file/controller.py:18` | 非超管用户无法被授予文件上传权限 → **上传功能对普通用户不可用**（业务阻断） |
| `module_common:file:download` | `app/modules/common/file/controller.py:37` | 同上，下载不可用 |

### 7.2 定时任务：任意代码执行 vs 处理器白名单（**安全**）

| 项 | 文档 §32.3（行 2300-2301） | 代码 |
|----|---------------------------|------|
| func 语义 | "须为已注册的处理器标识符"，禁止任意代码 | `func: Mapped[str] = mapped_column(Text, comment="代码块")` — `app/modules/task/cronjob/node/model.py:24` |
| 白名单 | `platform_handler_registry` 注册新处理器，仅超管可加 | 该表/机制**不存在**（`grep handler_registry` → 0） |
| 执行 | — | `app/core/ap_scheduler.py:544-575`：`exec(code_block, module.__dict__)` |
| 开关 | — | `app/config/setting.py:127` `SCHEDULER_ALLOW_CODE_EXEC: bool = True`（**默认开启**） |

代码自身注释（`ap_scheduler.py:547-549`）已承认："exec 等同给所有能创建任务的人服务器代码执行权限"。文档要求的方向（白名单）与实现方向（默认放行任意代码）相反。

### 7.3 `data_scope` 三处语义冲突（**安全**）

| 位置 | 定义 |
|------|------|
| 文档 §3.2（行 166-172） | 1=仅本人 2=本部门 3=本部门及以下 **4=全部** **5=自定义(sys_role_depts)** |
| `app/core/validator.py:314-322` | 接受 1–5，文案与文档一致 |
| `app/core/permission.py:16-18` | 只有常量 `DATA_SCOPE_SELF=1, DATA_SCOPE_DEPT_AND_CHILD=2, DATA_SCOPE_ALL=3` |
| `app/modules/system/role/model.py:72` | 注释"1:仅本人 **2:本部门及以下** 3:全部" |

后果：管理员按文档把角色设为 `data_scope=4`（期望"全部数据"）→ `Permission._filter_by_data_scope()` 走到末尾兜底分支（`permission.py:77-80`）→ `WHERE created_id = 当前用户`，即**退化为"仅本人"**。这是"配置了更宽权限、实际拿到更窄权限"，方向上是安全侧，但业务上会造成"管理员看不到数据"的严重误判；反过来，`data_scope=3` 在文档语义里是"本部门及以下"、在代码里是"全部"，若运维按文档理解去配置，会**意外获得全量数据视野**。

另：`app/core/permission.py:33-34` 超管直接 `return None`（不过滤）；`sys_role.json` 种子中 `SUPER_ADMIN` 与 `ADMIN` 的 `data_scope` 都是 3。

### 7.4 JWT 载荷（**安全**）

| 项 | 文档 §4.3（行 239）/§22.1（行 1665） | 代码 |
|----|--------------------------------------|------|
| 载荷内容 | `session_id, user_id, tenant_id, is_super_admin, 登录信息` | `app/core/base_schema.py:99-110`：只有 `sub`(session_id)、`is_refresh`、`exp` |
| 租户上下文 | 从 Token 提取 `tenant_id` + `is_super_admin`，经 ContextVar 传递 | 无 |

代码把用户身份放在 Redis session（`app/core/dependencies.py:114-190`），这是合理设计，但与文档契约不符；文档要求的临时 token/正式 token 双轨机制、`/auth/select-tenant` 均不存在。

### 7.5 用户导入密码策略（**安全**）

| 项 | 文档 §5.3（行 331） | 代码 |
|----|--------------------|------|
| 密码列为空 | 系统生成 12 位随机密码 + 邮件发送 | 全部行统一 `settings.PASSWORD_IMPORT_DEFAULT` = `"123456"`（`app/config/setting.py:134`，使用点 `app/modules/system/user/service.py:425`） |
| 密码列有值 | Bcrypt 加密后存储 | 模板表头无"密码"列（`service.py:331-339`），逻辑不存在 |
| 首次登录强制修改 | 要求 | 无该标记字段与流程 |

即：**所有导入用户的初始密码都是 `123456`，无邮件、无强制改密**。

### 7.6 登录限流与密码强度（**安全**）

| 项 | 文档（行 1675、1677） | 代码 |
|----|----------------------|------|
| 限流粒度 | 同一 **IP / 账号** | 仅按 IP（`app/modules/system/auth/service.py:155-174`，key=`login_rate_limit:{ip}`） |
| 阈值 | 连续失败 **5 次** | **10 次**（`app/config/setting.py:74` `LOGIN_RATE_LIMIT_MAX_ATTEMPTS=10`） |
| 窗口 | **15 分钟** | **60 秒**（`app/config/setting.py:73`） |
| 计数对象 | 连续**失败** | 递增发生在认证**之前**，成功登录也计数（`service.py:168`），且成功后不重置 |
| 豁免 | 无 | `127.0.0.1` / `localhost` / 空 IP 直接跳过（`service.py:164-165`） |
| 密码最短长度 | **8 位**（含字母+数字） | **6 位**（`app/config/setting.py:132` `PASSWORD_MIN_LENGTH=6`），复杂度为"字母/数字/符号任两类"（`app/utils/password_util.py:74-87`） |
| 初始管理员密码 | 12 位随机 + 邮件一次性重置链接 | 种子用户 `super`/`admin` 使用**同一套固定 PBKDF2 哈希**（`backend/sql/sys_user.json`），无邮件通道 |

补充：`PwdUtil.generate_strong_password(12)` 存在（`app/utils/password_util.py:90`）且要求 ≥8 位，但未与限流/初始化流程连通。

### 7.7 健康检查与指标端点

| 文档（行 1486-1490、2912-2943） | 代码 |
|-------------------------------|------|
| `GET /monitor/health` | `GET /monitor/health/check`（`app/modules/monitor/health/controller.py:20`） |
| `GET /monitor/health/live` | 不存在 |
| `GET /monitor/health/ready` | 不存在 |
| `GET /monitor/health/stream` | 存在（`:30`） |
| `GET /metrics`（Prometheus） | **不存在**；仅在 `app/config/setting.py:200` 的演示模式白名单里被提及 |

### 7.8 §22 安全性 13 条逐条核对

| # | 要求 | 状态 | 证据 |
|---|------|------|------|
| 1 | JWT 携带 tenant_id + is_super_admin，ContextVar 传递 | 缺失 | §7.4 |
| 2 | 白名单路径（登录/验证码/健康检查不设租户上下文） | 部分 | 无租户上下文；`WHITE_API_LIST_PATH`（`setting.py:190-200`）实为**演示模式**白名单，认证是逐路由依赖注入 |
| 3 | 系统租户 id=1 不可删/不可禁用/编码不可改 | 缺失 | 无租户概念 |
| 4 | 删除租户前检查关联数据 | 缺失 | — |
| 5 | 每租户至少保留一个 owner | 缺失 | — |
| 6 | 菜单越权防护（非超管只能在租户可用菜单内分配） | **缺失** | `app/modules/system/role/service.py:177-184` 只校验 menu_id 存在性，无租户菜单范围校验 |
| 7 | ContextVar 请求结束清理 | 缺失 | 无 ContextVar |
| 8 | Bcrypt 存储；普通用户 ≥8 位；初始管理员 12 位随机 | 部分 | 哈希用 PBKDF2-SHA256（`sql/sys_user.json`），符合"不存明文"；长度/随机性不符（§7.6） |
| 9 | 通知内容 `sanitize_html` 清洗 | 已实现 | `app/utils/xss_util.py:99-115`（bleach）；调用点见通知服务 |
| 10 | 登录限流 5 次/15 分钟 | 部分 | §7.6 |
| 11 | 所有 FK 有 ON DELETE/ON UPDATE 级联 | 已实现（抽样） | `app/core/base_model.py:124-160`、各 model 的 `ForeignKey(..., ondelete=..., onupdate=...)` |
| 12 | 文件资源管理禁止路径遍历（`..`） | 已实现 | `app/utils/upload_util.py:127-136, 343-357, 454`（`resolve().is_relative_to(...)` 兜底） |
| 13 | CORS 白名单 | 已实现 | `app/core/middlewares.py:22-32`；`app/config/setting.py:245-247` |

**额外发现（文档未覆盖）**：`/api/v1/system/param/info` 在演示模式白名单中且**无认证依赖**（`app/modules/system/params/controller.py:31`），任何人可读取全部 `sys_param`（17 条，含 `demo_enable` / `ip_white_list` / `ip_black_list`）。文档 §22.2 的白名单只列了"登录、验证码、健康检查"，未包含参数配置，属契约外行为。当前种子值敏感度低（品牌/备案/开关类），故定级中低。

### 7.9 API 路径前缀体系

代码统一挂载在 `/api/v1/<域>/...`（`ROOT_PATH=/api/v1`，`app/config/setting.py:47`；域见 `app/api/v1/routers.py:32-64`）。文档 §20 的路径**混用两套风格**：

| 文档风格 | 例 | 代码实况 | 数量 |
|---------|-----|---------|------|
| 无域前缀（User/Role/Dept/Position/Menu/Dict/Notice/Params/Ticket） | `/user/create` | `/api/v1/system/user/create` | 约 80 个路径 |
| 带域前缀且与代码一致 | `/monitor/cache/info` | `/api/v1/monitor/cache/info` ✔ | 约 14 个 |
| 带域前缀但与代码不符 | `/platform/loginlog/list`、`/system/operationlog/list`、`/file/upload`、`/chat/list`、`/gencode/*`、`/cronjob/*`、`/workflow/flow/*` | `/system/log/login/list`、`/system/log/operation/list`、`/common/file/upload`、`/ai/chat/*`、`/generator/gencode/*`、`/task/cronjob/*`、`/task/storage/workflow/*` | 约 100 个路径 |

自动化比对结果（路径参数名归一化后）：**文档 260 个唯一路径中，248 个与代码注册路径无法直接对应；代码 200 个端点中 184 个在文档中查不到**（该数字包含"整块模块缺失"与"仅前缀不同"两类，需结合 §3/§4 阅读）。

> 说明：比对集合为 `app/modules` 下的 200 个端点。`app/plugin/module_example/demo` 的 9 个端点（`/api/v1/example/demo/*`）与文档 §35.4 一致，未计入差异。

### 7.10 操作日志接口的路径+权限双重不一致

| 项 | 文档 §20.11（行 1396-1398） | 代码 |
|----|---------------------------|------|
| 路径 | `/system/operationlog/{detail,list,delete}` | `/system/log/operation/{detail,list,delete}` |
| 权限 | `module_system:operationlog:{query,delete}` | `module_system:log:{query,delete,export}`（`app/modules/system/log/controller.py:62,77,90,100`） |

登录日志同理：文档 `/platform/loginlog/*` + `module_platform:loginlog:*`，代码 `/system/log/login/*` + `module_system:login_log:*`。

### 7.11 接口返回结构

文档未定义统一返回包络；代码统一为 `ResponseSchema[T]` + `SuccessResponse/ErrorResponse`（`app/common/response.py`），列表统一 `PageResultSchema[T]`（`app/core/base_schema.py`）。**这是一处"文档缺验收标准"的问题**（见 §8.3），不宜判定为代码违规。

例外：`/user/export`、`/role/export`、`/position/export`、`/ticket/export`、`/log/operation/export` 返回 `StreamingResponse`（Excel 流）；`/notice/stream`、`/monitor/health/stream`、`/storage/transfer/stream` 返回 SSE。文档 §20 对这些端点只写"导出/实时流"，未定义格式。

### 7.12 其他命名/契约差异（汇总）

| 主题 | 文档 | 代码 |
|------|------|------|
| 参数模块路径 | §20.9 `/param/*`；§12.4 `/params/*`（文档内自相矛盾） | `/param/*` |
| 工单批量状态 | §17.4 `PUT /ticket/batch/status`；§20.12 `PATCH /ticket/status/batch` | `PUT /ticket/batch` |
| 角色菜单 | §20.3 `PUT /role/menus` | 不存在（只有 `PUT /role/permission`） |
| 用户改密/重置 | §20.2 `/user/password/change`、`/user/password/reset/{id}`；§5.5 `/user/current/password/change`、`/user/password/reset`（文档内自相矛盾） | `/user/password/change`、`/user/password/reset/{id}` |
| 忘记密码 | §20.1 `POST /auth/forgot-password` | `POST /user/password/forget` |
| 注册 | §20.1/§4.5 `POST /auth/register`（自动建租户+owner 角色+全量菜单） | `POST /user/register`（`app/modules/system/user/service.py:308-327`，只建用户，无租户/角色/菜单） |
| 数据库迁移 | §28.4 要求 Alembic 管理所有 schema 变更 | `backend/alembic.ini` 存在，但 `backend/app/alembic/versions/` **为空** |
| 缓存键规范 | §28.4 `{namespace}:{sub_namespace}:{identifier}` | 部分符合（`login_rate_limit:{ip}`、`{USER_SESSION}:{session_id}`），但 `login_rate_limit:*` 为两段式 |

---

## 8. 需求文档本身的问题

### 8.1 章节编号错误（可机械验证）

| 问题 | 行号 | 说明 |
|------|------|------|
| **§21.4 重复两次** | 1607、1621 | 1607「租户隔离业务表」与 1621「平台共享业务表」都编 21.4；后续 21.5/21.6/21.7 也未顺延 |
| **§24.6 缺失** | 1849→1851 | §24.5 业务规则 后直接跳 §24.7 退款流程，24.6 不存在 |
| §19 与 §15 状态机图不一致 | 865-875 vs 1211-1214 | §15 画的是 `active→grace→suspended→expired` + 独立 frozen 支线；§19 画 `active→grace→suspended→expired→archived`，未含 frozen 支线。两处对"frozen 与 expired 谁先"的描述可读性差 |
| Part 结构 | 2197、2944 | Part 4「Plugin 子模块需求」、Part 5「商业运营模块」被排在 Part 3「附录」正文之后，层级语义混乱（附录不应夹在两个需求 Part 之间） |

### 8.2 §1.4 模块总览严重过期

§1.4（行 33-58）列 22 个模块，但**遗漏了文档自身已定义的**：Email（§23）、Order（§24）、TenantSelfService（§25）、APIUsage（§26）、UserInvite（§27）、Monitor（§36）、Common（§37）、Demo（§35）。

同时 §1.4 把 `Cronjob / Workflow / AI Chat / CodeGen` 标为"插件"，但文档 Part 4 又把它们放在 §31-§37，且 Plugin 注册表（§18）本身缺失——"插件"既指目录约定又指注册表模块，术语未区分。

### 8.3 缺验收标准

- §20 API 汇总给出路径但**不给请求/响应示例**，无法验收返回结构（如分页字段名、时间格式、软删除是否可见）。
- NFR（§28.4）列出 P95 ≤ 500ms、500+ 并发、99.5% 可用性、RTO/RPO，但**无验证方法、无压测脚本、无环境基线**，不可验收。
- §22 安全性 13 条无一条给出验证用例（例如"登录失败 5 次锁定"如何观测）。
- §15.3/§19.2 涉及定时任务（到期扫描、归档），但**未定义任务名以外的任何可观测产物**（日志格式、指标、失败重试）。
- §28.3 API 路径规范把"日志层级问题"标为"建议保持现状"，而 §20.11/§20.10 又写成 `/system/operationlog/`、`/platform/loginlog/`——**"规范"章节与附录接口表互相打架**。

### 8.4 与代码现实背离的表述（文档自称"与代码一致"，实测不一致）

§30 变更记录明确声称已修复命名，但实测仍不符：

| 变更记录声明 | 实际代码 | 结论 |
|-------------|---------|------|
| v3.2.1（行 2186）"统一表名为 `platform_*` 前缀（与代码一致）" | 代码是 `sys_user/sys_role/sys_dept/sys_notice/sys_param/sys_ticket/sys_menu/sys_login_log` | **反了**：文档改成了 `platform_*`，代码一直是 `sys_*` |
| v3.2.2（行 2187）"修复 `sys_ticket`→`platform_ticket`、`sys_login_log`→`platform_login_log` 两处表名错误" | 代码仍为 `sys_ticket`、`sys_login_log` | 该"修复"使文档进一步偏离代码 |
| v3.3.0（行 2188）"P0-4 初始管理员密码交付改为邮件一次性重置链接" | 无邮件模块；种子管理员为固定哈希 | 未落地 |
| v3.3.0 "P1-1 通知已读机制改为后端 `sys_notice_read` 表" | 无该表 | 未落地 |
| v3.3.0 "P1-2 工单增加 `close_reason/closed_time/closed_by`" | `sys_ticket` 无这三个字段 | 未落地 |
| v3.3.0 "P0-2 定时任务/工作流代码执行安全性（任意代码→预定义处理器白名单）" | `SCHEDULER_ALLOW_CODE_EXEC=True` 默认放行 `exec` | 未落地且方向相反 |
| v3.3.0 "P1-4 用户导入密码处理策略" | 硬编码 `123456` | 未落地 |
| v3.6.0（行 2191）"PRD 100% 完整度达标" | — | 该结论只针对文档自身完整性，与实现无关，易被误读为"已交付" |

### 8.5 版本/时间线异常

- 文档版本 `v3.6.0`、最后更新 `2026-06-03`，而 `backend/pyproject.toml` 版本 `3.2.0`，`CHANGELOG.md`（新版）最新条目为 `2026-09-06`。文档版本号与代码版本号无对应关系。
- §30 变更记录全部集中在 `2026-06-01 ~ 2026-06-03` 三天内完成 v3.1.0→v3.6.0 五个版本的"审查修复"，而仓库实际开发时间线为 2026-06 至 2026-09。**该文档像是独立生成的规划稿，未与代码仓库的迭代同步。**

### 8.6 需求内部矛盾清单

| # | 冲突点 | 位置 |
|---|--------|------|
| 1 | 工单批量状态：`PUT /ticket/batch/status` vs `PATCH /ticket/status/batch` | 1122 vs 1409 |
| 2 | 参数路径：`/params/*` vs `/param/*` | 694-698 vs 1377-1382 |
| 3 | 用户改密/重置路径两套 | 1294-1295 vs 352-353 |
| 4 | 权限标识风格：`user:query`、`role:query`（§20.2-20.9）vs `module_system:user:query`、`module_system:login_log:query`（§20.10-20.11，也是代码实际风格） | 1284-1382 vs 1386-1398 |
| 5 | 租户生命周期图两处不一致（frozen 支线） | 865-875 vs 1211-1214 |
| 6 | 状态编码：§15.2 说 `status` default=0 且 0=active…5=archived；§19.1 再列一遍阶段但顺序含 archived | 810 vs 1202-1207 |
| 7 | `expire_after_days`/`archive_after_days` 标为"全局配置"（§19.4），但 §15.2 的 `platform_tenant` 表只有 `grace_period_days`；全局配置的存储位置未定义 | 1241-1243 |
| 8 | 文档 §1.4 把 LoginLog 标为"平台级无隔离"、OperationLog 标为"TenantMixin"，但 §21.4 又把 `platform_login_log` 列在"租户隔离业务表"下的同一张表清单里（表名前缀矛盾） | 46-47 vs 1617-1618 |
| 9 | `is_default` 套餐字段：§16.2 定义（行 1002），§4.5 依赖（行 258/269），§21 平台资源表小节无 `platform_package` 字段清单（行 1582） | 1002 / 258 / 1582 |
| 10 | 文档称"已内置插件 module_ai/chat、module_example/demo、module_generator/gencode、module_task/cronjob、module_task/workflow"，但实际 `app/plugin/` 下**只有 module_example/demo**，其余在 `app/modules/` | 1175-1180 vs 目录实况 |

---

## 9. 缺口影响判断与建议优先级

### P0（阻断级 / 安全级）—— 决定"这套代码能不能称为 SaaS 多租户平台"

| # | 缺口 | 业务风险 | 证据 |
|---|------|---------|------|
| P0-1 | **多租户数据隔离整体缺失**（tenant_id / TenantMixin / ORM 事件层 / CRUD 层 / 租户中间件 / ContextVar / `__platform_data_shared__`） | 平台无法上线多租户：所有租户数据同库同表无隔离，多客户共用一个 `sys_user` 表，`username` 全局唯一，A 租户能看到 B 租户全部用户/角色/部门/公告/参数/工单/日志。这是**数据泄露级**风险，且不是"补一个字段"能修——需要贯穿 Model→CRUD→Service→Auth 的改造 | §5 Part1 全节；`grep tenant backend/app` → 0 |
| P0-2 | **平台层/租户层权限模型缺失** | 只有"超管 / 普通用户"二元模型（`is_superuser`）；无法表达"租户管理员可管本租户、不可跨租户" | §1.2/§1.3；`app/core/dependencies.py:192-234` |
| P0-3 | **Tenant 模块 + Package 模块完全缺失** | 无法开通租户、无法售卖套餐、无法配额管控。`/tenant/*`(14 端点)、`/platform/package/*`(7 端点) 全无 → 商业闭环为零 | §3 矩阵；`find backend/app -iname "*tenant*"` → 空 |
| P0-4 | **定时任务默认允许任意代码执行** | 任何能创建 cronjob 节点的用户可在服务器执行任意 Python（`exec`），等同 RCE。文档 v3.3.0 已把该问题列为 P0 并要求改为处理器白名单，代码未改且默认开启 | §7.2 |
| P0-5 | **`data_scope` 语义双标 + 校验放宽到 5** | 校验层接受 4/5，权限层只认 1/2/3 且 2/3 含义与文档不同 → 按文档配置会得到与预期相反的可见范围（管理员"看不到数据"或意外获得全量视野） | §7.3 |

### P1（核心业务能力缺失）—— 决定"能不能跑通一个租户的完整生命周期"

| # | 缺口 | 业务风险 | 优先级理由 |
|---|------|---------|-----------|
| P1-1 | **Email 邮件服务缺失**（§23） | 密码重置、用户邀请、到期提醒、初始管理员交付**四条业务链路全部断掉**；文档 §19.5/§4.5/§27 都依赖它 | 被 4 个模块依赖，属"公共基础设施缺失" |
| P1-2 | **Order / Payment / Refund 缺失**（§24，13 端点 + 3 表） | 无法收款、无法续费、无法升级降级。`OrderTypeEnum` 已存在但无使用方（悬空） | 商业闭环 |
| P1-3 | **到期处理与租户生命周期状态机缺失**（§19，`check_tenant_expiry`） | 无到期扫描 → 租户永不到期；无宽限期/暂停/过期/归档 → 无续费压力也无资源回收 | 依赖 P0-3 |
| P1-4 | **Plugin 注册表缺失**（§18，`platform_plugin` + `platform_tenant_plugin` + 安装/卸载） | 插件只有目录约定（`app/core/discover.py`）和静态 `plugin.toml`，无法按租户启用/禁用/计费 | 文档 §18 全部字段与端点均无 |
| P1-5 | **文件上传/下载权限点不在种子菜单**（§7.1-B） | **非超管用户完全无法上传/下载文件**——这是当下立即可复现的功能阻断，与多租户无关，独立可修 | 修复成本极低、影响直接 |
| P1-6 | **UserInvite / APIUsage / AuditLog / Dashboard / Invoice 缺失** | §26 用量统计是计费依据；§39 审计日志是合规刚需（文档要求 3 年保留、不可篡改）；§40 大盘是运营入口 | 依赖 P0-3/P1-2 |
| P1-7 | **注册链路无租户/角色/菜单初始化**（§4.5） | `POST /user/register` 公开可用但只建用户、无租户、无 owner 角色、无菜单、无邮箱验证 → 任何人在库里造孤立用户 | `app/modules/system/user/service.py:308-327` |
| P1-8 | **用户导入密码固定 `123456`**（§7.5） | 批量导入后所有账号共享同一弱口令，且无强制改密 → 撞库即批量失陷 | `setting.py:134` |
| P1-9 | **登录限流 10 次/60 秒 + 仅 IP + 成功也计数**（§7.6） | 10 次/60 秒 ≈ 14400 次/天/IP，对账号爆破几乎无防护；且成功登录也计数会导致正常用户被误锁 | `auth/service.py:155-174` |

### P2（契约对齐与工程质量）

| # | 缺口 | 影响 |
|---|------|------|
| P2-1 | 4 个"死权限点"（`cache:detail`、`swagger:docs`、`log:detail`、`param:query`） | 种子菜单授予了不存在的权限，前端按钮显隐与后端校验脱节 |
| P2-2 | 登录/操作日志的路径 + 权限标识与文档全不一致（§7.10） | 前端、网关、权限配置、文档四方对不上 |
| P2-3 | 表名前缀体系混乱（文档 `platform_*` vs 代码 `sys_*`，且 `task_corn_*` 拼写可疑） | 运维/DB 审计/文档读者三方误解 |
| P2-4 | 表名缺 `tenant_id` 唯一键维度（`username`/`code` 全局唯一） | 即使补了 tenant_id，也无法支持"不同租户同名账号" |
| P2-5 | §14.5 操作日志保留/清理策略零实现；`sys_login_log` 无清理 | 生产环境日志表无限增长 |
| P2-6 | `/metrics` 不存在；health 端点路径不符（§7.7） | K8s liveness/readiness 探针与 Prometheus 抓取需按代码而非文档配置 |
| P2-7 | NFR 的 i18n key 未落地 | `grep "errors\." backend/app` 命中均为 `errors.append(...)` 变量，非 i18n key；后端错误消息为硬编码中文（前端已有 `locales/{en,zh}.json`） |
| P2-8 | `app/alembic/versions/` 为空 | §28.4 要求"所有 schema 变更通过 migration 执行"，实际靠 `app/scripts/initialize.py` 建表（`initialize.py:70,167`） |
| P2-9 | 未文档化的已实现模块：`versions`（版本管理，6 端点，含种子菜单）、`task/storage/*`（存储浏览/传输/工作流，25 端点，4 张表）、`chat/model`（AI 模型配置，5 端点） | 需求文档无法覆盖现有功能，反向缺口 |
| P2-10 | `/api/v1/system/param/info` 契约外公开（§7.8 额外发现） | 当前敏感度低，但配置内容一旦扩展（如密钥类参数）即成泄露点 |

### 建议的处理顺序（若后续要"向文档对齐"）

```
阶段 0（当天可做，独立价值）
  → P1-5 补种子菜单 2 个文件权限点
  → P2-1 清理 4 个死权限点（或补齐对应端点）
  → P0-4 把 SCHEDULER_ALLOW_CODE_EXEC 默认改为 False（最低成本消除 RCE）
  → P1-9 / P1-8 对齐限流参数与导入密码策略

阶段 1（决定架构走向，需先做决策而非编码）
  → 决策：文档 v3.6.0 是"目标规格"还是"已交付规格"？
    · 若是目标规格 → 应把 REQUIREMENTS.md 移到 docs/ 并标注"未实现"，本报告即差距清单
    · 若是已交付规格 → 与实现差距过大（5 个整模块 + 跨层改造），需重写文档
  → P0-5 data_scope 语义统一（改文档或改代码，二者取一）
  → P0-1/P0-2/P0-3 多租户改造方案设计（不是编码任务）

阶段 2（多租户改造落地后）
  → P1-1 Email → P1-3 到期处理 → P1-2 订单支付 → P1-4 Plugin → P1-6 其余
```

---

## 10. 存疑清单与核实方法

| # | 存疑点 | 为什么存疑 | 核实方法 |
|---|--------|-----------|---------|
| 1 | 数据表是否真实存在于任何运行库 | `app/alembic/versions/` 为空；建表走 `app/scripts/initialize.py`（`initialize.py:70,167`），未启动服务验证 | 启动后连库执行 `SHOW TABLES` / `\dt`，与 `grep __tablename__` 结果比对 |
| 2 | **审计范围未覆盖前端逐页面行为** | 只做了目录级统计（web `views` 101 个 `.vue`、app `pages+subPages` 14 个 `.vue`），未逐页读 | 指定页面逐个走查；或按 `frontend/web/src/api/**` 的实际请求路径反查后端路由是否存在 |
| 3 | §23–§27 与 §38–§40 正文的字段级细节 | 只按"代码零实现"下结论，未逐行读正文表格 | 若这些模块要进入排期，需重读 §23.2/§24.3/§26.2/§27.2/§38.3/§39.3 的字段清单 |
| 4 | §31–§37 的规则级符合度 | 只核对了路由前缀/表名/权限点，未逐条核对业务规则（如 §33.3 工作流规则） | 逐条读 §32.3/§33.3/§34.3/§36.3/§37.3 后与 service 层比对 |
| 5 | `demo_enable` / IP 黑白名单的实际拦截行为 | 只读了中间件分支（`app/core/middlewares.py:50-68`），未运行验证 | 造请求实测 |
| 6 | 前端权限点使用是否与后端一致 | 未逐条比对前端 `hasPerm`/指令与后端 `AuthPermission` | 提取 `frontend/web/src/directives/**` 与 `common_util` 中的权限串做集合比对 |
| 7 | `sys_role_depts`（文档 `data_scope=5` 自定义数据权限）是否被实际使用 | 表存在（`app/modules/system/role/model.py:41`），但 `permission.py` 未读取该表 | 全仓搜 `RoleDeptsModel` 使用点确认 |
| 8 | 移动端（uniapp）与文档的对应关系 | 文档几乎只写后端；`frontend/app/src/pages` 只有 index/login/mine/work | 若移动端需纳管，需另建移动端需求基线 |

---

## 11. 证据索引（关键文件行号速查）

```
多租户缺失
  backend/app/core/base_model.py:22,42,124        MappedBase / ModelMixin / UserMixin（无 TenantMixin）
  backend/app/core/permission.py:12-124           唯一的数据权限实现（data_scope 1/2/3）
  backend/app/core/validator.py:314-322           data_scope 校验接受 1-5
  backend/app/core/base_crud.py:33                CRUDBase（无租户条件）
  backend/app/api/v1/routers.py:32-64             6 个路由域，无 /tenant /platform /plugin
  backend/app/core/discover.py:1-106              仅 app/plugin/module_* 动态注册

安全相关
  backend/app/core/ap_scheduler.py:544-575        exec(code_block)
  backend/app/config/setting.py:127               SCHEDULER_ALLOW_CODE_EXEC = True
  backend/app/config/setting.py:73,74             限流 60s / 10 次
  backend/app/config/setting.py:132               PASSWORD_MIN_LENGTH = 6
  backend/app/config/setting.py:134               PASSWORD_IMPORT_DEFAULT = "123456"
  backend/app/modules/system/auth/service.py:155-174   限流实现（仅 IP）
  backend/app/modules/system/user/service.py:425       导入密码使用点
  backend/app/core/base_schema.py:99-110          JWTPayloadSchema（无 tenant_id/is_super_admin）
  backend/app/utils/xss_util.py:99-115            sanitize_html ✔
  backend/app/utils/upload_util.py:127,343,454    路径遍历防护 ✔
  backend/app/core/middlewares.py:22-32           CORS ✔
  backend/app/config/setting.py:190-200           白名单（含 /api/v1/system/param/info）

契约不一致
  backend/sql/sys_menu.json                       123 个权限点（4 个 backend 无实现）
  backend/app/modules/common/file/controller.py:18,37  2 个权限点不在种子菜单
  backend/app/modules/system/ticket/model.py:17   sys_ticket（文档 platform_ticket）
  backend/app/modules/system/log/model.py         sys_login_log（文档 platform_login_log）
  backend/app/modules/task/cronjob/node/model.py:11,24   task_cornjob_node / func="代码块"
  backend/app/modules/task/cronjob/job/model.py:11       task_corn_job
  backend/app/modules/system/role/model.py:72     data_scope 注释
  backend/app/modules/system/role/service.py:177-184     角色菜单分配无租户范围校验

种子数据
  backend/sql/*.json                              11 个种子文件；无 tenant/package/plugin 种子
  backend/sql/sys_role.json                       SUPER_ADMIN/ADMIN data_scope=3
  backend/sql/sys_user.json                       super/admin 同一固定 PBKDF2 哈希

前端覆盖
  frontend/web/src/views/                         11 个目录，无 tenant/package/plugin/order/dashboard(platform)
  frontend/web/src/api/                           7 个模块目录
  frontend/app/src/pages/ + subPages/             14 个页面，无租户/套餐
  frontend/web/src/locales/langs/{en,zh}.json     前端 i18n 已有骨架

文档基线
  REQUIREMENTS.md:1-5                             标题与版本 v3.6.0 / 2026-06-03
  REQUIREMENTS.md:33-58                           §1.4 模块总览（遗漏 8 个模块）
  REQUIREMENTS.md:166-172                         data_scope 五档（与代码冲突）
  REQUIREMENTS.md:785-987                         §15 Tenant（整章无实现）
  REQUIREMENTS.md:1262-1573                       §20 API 汇总（260 唯一路径）
  REQUIREMENTS.md:1577-1659                       §21 表结构（21.4 重复）
  REQUIREMENTS.md:1663-1681                       §22 安全性 13 条
  REQUIREMENTS.md:1849-1851                       §24.6 缺号
  REQUIREMENTS.md:2180-2191                       §30 变更记录（多处声明与代码不符）

Git 证据
  45a00334 docs: add SaaS multi-tenant platform requirements   （纯文档提交，R100 重命名自 CHANGELOG.md）
```

---

## 附：机械化核对命令（可复现）

```bash
cd /Users/tao/workspace/FastapiAdmin

# 1. 多租户实现是否存在
grep -ril "tenant" backend/app frontend/web/src frontend/app/src | wc -l        # → 0

# 2. 需求文档的引入方式
git show --stat --no-renames 45a00334
git log --oneline -S "SaaS 多租户平台需求文档" -- REQUIREMENTS.md

# 3. 权限点 vs 种子菜单
grep -rn "AuthPermission(\[" backend/app --include=*.py | grep -v __pycache__   # 121 个
python3 -c "import json;d=json.load(open('backend/sql/sys_menu.json'));p=set()
def w(n):
    for x in n:
        p.add(x['permission']) if x.get('permission') else None; w(x.get('children') or [])
w(d); print(len(p))"                                                            # 123 个

# 4. 表名清单
grep -rn "__tablename__" backend/app --include=*.py | grep -v __pycache__

# 5. 到期处理是否实现
grep -rn "check_tenant_expiry\|expire_after_days\|archive_after_days\|grace_period" backend/app  # → 无

# 6. 商业运营模块是否实现
for k in smtp EmailConfig refund invoice audit_log api_usage; do
  echo "$k: $(grep -ril "$k" backend/app | wc -l)"; done
```

---

*报告结束。本报告所有结论均可由 §11 索引中的文件行号与附录命令复现；标注"存疑"的条目请按 §10 的方法核实后再进入排期。*
