# FastapiAdmin 全栈审计总报告

> 生成时间：2026-10-04
> 审计范围：后端（FastAPI）、Web 管理后台（Vue3）、移动端（uniapp）、部署编排（Docker/Nginx）、需求覆盖、测试与可验证性、交互与视觉一致性
> 参与：7 名审计成员并行执行 + 队长线上实测复核
> 方法：只读审查 + 真实命令执行（命令与退出码均记录在各分报告）；线上结论均由对生产环境的实测得出

---

## 0. 一句话结论

**这是一个功能可用、但安全与质量债较重的单租户 RBAC 中后台**：认证、权限、代码生成等核心能力具备，但存在多类可被直接利用的问题（公开密钥可伪造令牌、超管弱口令、代码生成即 RCE、部署面暴露），同时需求文档声称的 SaaS 多租户能力在代码中零实现——需求文档与实际产品是两件事。

---

## 1. 覆盖范围与缺口（必须先看）

| 维度 | 已覆盖 | 未覆盖 / 存疑 |
| --- | --- | --- |
| 后端代码 | 216 个 py 文件 / 28519 行静态审查；`ruff check` 全量通过 | 需真实 MySQL/PostgreSQL/Redis 的行为未验证（本机三端口均不可达） |
| 前端 Web | 101 个 `.vue`；`type-check` exit 0；`vitest` 10/10 通过 | 无浏览器实机验证；无真机性能数据 |
| 移动端 uniapp | 14 个页面；`type-check` exit 0 | 未跑 `uni build` 各平台产物；无真机验证；0 测试 |
| 部署编排 | compose 校验、镜像构建、容器运行时、端口、证书、资源实测 | 未做真实压测；未验证灾备恢复演练 |
| 需求覆盖 | 逐行读 REQUIREMENTS.md Part1 + §11–§19 + §20–§22 + §28–§30 | §23–§27、§38–§40 依「代码零实现」这一可穷举事实下结论，未逐行读正文表格 |
| 测试 | pytest 与 vitest 真实执行 | 迁移链路 0 覆盖；无 CI |

**审计成员明确声明的抽样边界与存疑项**，见各分报告末尾章节；本报告不把抽样结论伪装成全量结论。

---

## 2. 必须先止血的问题（可被直接利用）

### 2.1 [blocker] 生产使用源码公开的默认 SECRET_KEY

- 证据：`backend/app/config/setting.py:66` 默认值硬编码；`docker/docker-compose.yaml`、`docker/.env.example`、`backend/env/.env.prod` 三处均无该键（grep 验证 + 线上容器 env 实测）
- 后果：
  - `backend/app/core/security.py:114,139` 用该密钥签发/校验 JWT → 可离线伪造任意用户（含超管）令牌
  - `backend/app/core/crypto_util.py:47-56` 用同一密钥经 HKDF 派生 `DATA_ENCRYPTION_KEY` → 落库的加密字段（API Key、存储源口令）可被解密
  - 与 `/api/v1/monitor/online/list` 返回的 session_id 结合，可在不知道任何口令的情况下完成认证绕过
- 为什么严重：攻击者只需要拿到源码（或知道该默认字符串），不需要任何其他条件

### 2.2 [blocker] 种子超管账号使用公开弱口令

- 证据：安全审计经 PBKDF2 复算确认种子哈希对应 `123456`；`backend/app/scripts/initialize.py` 无环境判断，空库启动即写入；README 中公开该口令
- 受影响账号：`super`、`admin`（均为超管）
- 实测补充：种子账号的登录受滑块验证码保护，但安全审计判定该验证码**无实质人机校验**，不构成有效防线

### 2.3 [blocker] 代码生成模板导致权限即 RCE

- 证据：生成模板 `autoescape=False`，把 `function_name` / `column_comment` / `column_name` 原样写入 `.py`；输出目录为 `app/plugin/**`，而 `app/core/discover.py:52,74` 在启动时 import 该目录
- 后果：任何拥有代码生成权限的账号可通过构造字段注释写入任意 Python 代码，服务重启后执行
- 相关：`backend/app/modules/system/scheduler` 侧 `SCHEDULER_ALLOW_CODE_EXEC=True`（`setting.py:127`）+ `exec` 带完整 builtins（`ap_scheduler.py:562-563`）无需 gencode 权限同样构成 RCE 面

### 2.4 [blocker] 仓库当前**无法构建**

- 证据：`docker/backend/Dockerfile` 仍只 `COPY requirements.txt`，而依赖已拆分为 `backend/requirements/`；该目录**未被 git 跟踪**（`git ls-files backend/requirements` = 0）
- 后果：新克隆的仓库按文档构建必然失败；`deploy-artifacts.sh` 因其自带 Dockerfile 生成逻辑而绕过该问题，但这掩盖了仓库本身的破损
- 状态：本轮已将仓库 Dockerfile 改写为与新依赖结构一致（见 §4）

### 2.5 [high] 部署面暴露与错误默认值

| 项 | 证据 | 状态 |
| --- | --- | --- |
| API 文档公网可访问 | `/api/v1/docs`、`/redoc`、`/openapi.json` 实测 200 | 已修（nginx 仅放行内网） |
| MySQL/Redis/Backend 端口对公网开放 | 外部实测 3306/6379/8001 均可达 | 已修（绑定 127.0.0.1） |
| 生产 CORS 回落为 `["*"]` 且 `ALLOW_CREDENTIALS=True` | `setting.py:243-248` | 待修 |
| `FORWARDED_ALLOW_IPS="*"` | `docker-compose.yaml:119`；叠加后端端口曾暴露 → 可伪造 XFF 绕过限流与登录 IP 记录 | 待修 |
| 登录失败返回 HTTP 500 | 实测：验证码过期走 `custom_exception_handler` → 500（业务异常被当服务器错误） | 待修 |

---

## 3. 逻辑与契约缺陷（影响数据正确性）

1. **通知状态枚举两端冲突**（已复核）：后端权威 `notice/model.py:16` = `0草稿/1已发布/2已归档`，移动端一致；Web 端 `views/module_system/notice/index.vue:116-117,189-190,254,403` 却是 `0启用/1停用` → 已归档公告在 Web 显示为灰色数字「2」，且筛选条件里不存在「已归档」。
2. **移动端刷新令牌格式不符**：app 发 `{refresh_token}` 对象，后端 `auth/controller.py:57` 为 `Body(str)` → 422；移动端 token 过期后必然强制登出。
3. **移动端文件上传路径错误**：app 调 `/file/upload`，真实路径为 `/api/v1/common/file/upload` → 404。
4. **移动端生产 WebSocket 指向 localhost**：`app/.env.production:23` = `ws://localhost:5180/ws` → 线上 AI 对话不可用。
5. **富文本默认上传地址畸形**：`web/src/components/forms/fa-wang-editor/index.vue:83` 拼出 `//file/upload`（协议相对 + 缺 `/common`）→ 公告/工单插图必失败。
6. **Web 生产构建开关恒 false**：`web/vite.config.ts:28` 判断 `mode === "prod"`，而脚本只传 `production/development` → minify、drop_console、gzip/brotli、剔除 vue-devtools 全部不生效。
7. **CRUDBase 权限注入不完整**：`base_crud.py:300-330` 仅读路径注入数据权限，`delete/clear/set`（`:225-251`）不注入；6 处 `set_available` 无完整性校验 → 普通管理员可改任意部门/字典/公告、可停用超管。
8. **部门/菜单成环导致权限查询 500**：`common_util.py:181-196` 的 `get_child_recursion` 无 visited 集合。

---

## 4. 本轮已落地的修复（部署侧，全部有验证证据）

| 修复 | 证据 |
| --- | --- |
| 关闭公网数据面暴露：3306/6379/8001 仅绑 127.0.0.1 | 外部实测三端口均已关闭；四端 200 |
| API 文档对外封堵（仅内网可访问） | 外部 403，服务器本机 200，业务接口不受影响 |
| 容器改为非 root 运行（uid=1000 app） | 容器内 `id` = app；日志/上传/迁移目录均可写 |
| TLS 私钥与 `.env` 权限收紧到 600 | `stat` 实测；nginx 仍可读取 |
| 隐藏文件不再对外服务 | `.DS_Store` 由 200 变 403，并加 nginx deny 兜底 |
| 静态资源长缓存 | 哈希资源 `max-age=31536000, immutable`，图片 30 天，HTML 不缓存 |
| nginx 升级 1.25.5 → 1.27.5 | 配置校验通过；TLS1.2/1.3 正常；保留 `nginx:rollback-1.25` |
| 后端健康检查修复 | 由长期 unhealthy 变为 healthy（`ALLOWED_HOSTS` 放行 localhost） |
| 后端依赖拆分（核心 / 数据库驱动 / 存储） | MySQL 变体镜像 565MB → 521MB；PG 变体自检 asyncpg+psycopg 通过 |
| 部署脚本具备备份、回滚、轮转、变体构建 | `deploy-artifacts.sh` 各子命令均实测通过（含回滚哨兵测试） |
| SSH 加固 | 密码登录禁用、root 仅密钥、密码已轮换 |

---

## 5. 修复路线（按风险×成本排序）

| 优先级 | 动作 | 影响面 | 预估 |
| --- | --- | --- | --- |
| P0 | 注入强随机 `SECRET_KEY` + `DATA_ENCRYPTION_KEY`；轮换 super/admin 口令；若启用演示模式则关闭 | 会话作废需重新登录；落库密文保持可解 | 30 分钟 |
| P0 | 修仓库 Dockerfile 与依赖跟踪，使「克隆即可构建」 | 无运行时影响 | 20 分钟 |
| P1 | 前端 5 条 P0（生产开关、刷新令牌、上传路径、WS 地址、富文本上传） | 需重建并部署前端 | 1–2 小时 |
| P1 | 后端：日志级别、`SCHEDULER_ALLOW_CODE_EXEC=False`、模板 `autoescape=True`、CRUDBase 补权限注入、`get_child_recursion` 防环 | 需完整回归 | 1 天 |
| P1 | 生产 CORS 显式白名单；`FORWARDED_ALLOW_IPS` 收敛；业务异常返回 4xx | 需回归 | 半天 |
| P2 | 建立 CI（后端 pytest + ruff、web type-check + vitest）；修复测试夹具（fakeredis、assert_route、隔离） | 无运行时影响 | 1–2 天 |
| P2 | Web i18n 补齐（85/101 页面未接入）与通知枚举修正 | 需产品确认后端是否提供菜单 i18n 字段 | 2–3 天 |
| P2 | 证书自动续期（当前 2027-03-06 到期，无续期与告警；ACME 路径被 301） | 无运行时影响 | 半天 |
| P3 | 清理死代码、`any` 治理、键盘可达性（76 处 `@click` 无 tabindex/role） | 渐进 | 持续 |

---

## 6. 需要决策的事项

1. **线上数据库口令与 OPENAI_API_KEY**：两者均出现在 git 历史（旧库口令命中 10 个提交，已推送到 `master/dev`），且镜像内 `.env.prod` 曾包含真实值 → 建议按已泄露处理并重新签发。是否重写 git 历史取决于仓库可见性。
2. **多租户规格错位**：`REQUIREMENTS.md` v3.6.0 描述 SaaS 多租户（`grep -ril tenant` 在三端 0 命中），实为单租户后台；该文档是 CHANGELOG.md 重命名产生的纯文档提交。是「改文档」还是「立项实现」，只能由产品决定。
3. **`/user/register` 接口**：无鉴权/无验证码/无开关（当前被 `DEMO_ENABLE` 挡住返回 400）。是否保留该接口、以及演示模式在生产是否应关闭。
4. **后端是否提供菜单名 i18n 字段**：Web 侧边栏菜单名来自数据库，补齐前端 i18n 后菜单仍为中文。
5. **移动端范围**：无批量操作、无导入导出是否已在需求中登记为范围外。

---

## 7. 本次审计对既有结论的修正（避免误判）

| 原表述 | 修正 |
| --- | --- |
| 任务背景称「Web 端使用 uno.config.ts」 | 不成立：Web 端为 Tailwind v4（`@tailwindcss/vite` + `tailwindcss@^4.3.0`），UnoCSS 仅存在于 app 端；两端令牌体系独立 |
| 安全报告称 `/user/register` 无鉴权可注册 | 接口确实无鉴权，但当前被演示模式拦截（实测 400）；风险取决于 `DEMO_ENABLE` |
| 队长初判 nginx `ssl_protocols` 缺 TLS1.3 | 误判：`nginx -T` 显示 `ssl_protocols TLSv1.2 TLSv1.3;`，实测 TLS1.3 可用 |
| 队长初判 `.DS_Store` 清理后仍可访问 | 实为清理成功，后续 200 来自 SPA 回退（`try_files` → index.html），已用 deny 规则彻底封堵 |

---

## 8. 分报告索引

| 报告 | 覆盖 |
| --- | --- |
| `backend/audit-backend.md` | 后端架构与代码质量（22 条） |
| `frontend/audit-frontend.md` | 前端与移动端工程（32 条） |
| `backend/audit-testing.md` | 测试与可验证性 |
| `backend/audit-security.md` | 认证/授权/敏感信息（23 条） |
| `backend/audit-requirements.md` | 需求覆盖对照 |
| `frontend/audit-uxui.md` | 交互与视觉一致性（590 行） |
| `docker/audit-deploy.md` | 容器化与部署链路（799 行） |

每份报告均包含：问题清单（级别 + 文件:行号 + 现象 + 影响 + 建议）、按优先级的修复清单、未验证/存疑项。
