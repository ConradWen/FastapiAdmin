# FastapiAdmin 安全审计报告：认证 / 授权 / 敏感信息

- 审计任务：`t4` — 安全审计（认证 / 授权 / 敏感信息）
- 审计对象：后端（`backend/app`、`backend/main.py`、`backend/env/*`、`backend/sql/*`、`backend/logs/*`）及必要的关联面（`docker/nginx/nginx.conf`、`frontend/web/src/utils/auth/index.ts`、`frontend/web/.env`、git 历史）
- 工作区：`/Users/tao/workspace/FastapiAdmin`（分支工作树，含未提交改动）
- 审计时间点：审计时刻工作区实际内容
- 约束遵守：**只读审计**。未安装依赖、未启动服务、未提交 git、未做任何破坏性或对外发包的利用尝试；仅新增本报告文件。
- 证据规则：`文件:行号` 为审计时刻实际内容；命令输出为在本地对工作区/仓库的只读操作结果。所有"可利用性"结论都标注了前置条件，未验证的部分进入第 6 节「待验证」。
- 交叉引用：部署链路的安全问题已有独立报告 [`docker/audit-deploy.md`](../docker/audit-deploy.md)（任务 t6）。本报告只引用其结论，不重复展开。

---

## 1. 结论速览

### 1.1 上线前必须修（blocker / high）

| ID | 级别 | 问题 | 关键证据（文件:行号） | 修复建议 |
|----|------|------|----------------------|---------|
| **S1** | **blocker** | JWT 签名密钥使用源码内公开默认值，且 `env/.env.dev`、`env/.env.prod`、docker 编排均未注入 `SECRET_KEY` → 任何人可用公开密钥伪造任意用户的访问令牌；同一密钥经 HKDF 派生数据加密主密钥，落库/落缓存的 AI `api_key`、存储源口令可被解密 | `backend/app/config/setting.py:66`（默认值）、`backend/env/.env.prod`（无 `SECRET_KEY` 键）、`grep -n "SECRET_KEY" docker/docker-compose.yaml deploy.sh` 无命中（编排亦未注入）、`backend/app/core/security.py:112-116,139`、`backend/app/utils/crypto_util.py:35-55`；与 `docker/audit-deploy.md` B1 同一根因 | 1) 删除 `SECRET_KEY` 的默认值，改为必填（缺省即启动失败）；2) 部署侧注入 ≥32 字节随机值（`openssl rand -hex 32`）并轮换现值；3) 同时显式配置 `DATA_ENCRYPTION_KEY` 并轮换已加密数据 |
| **S2** | **blocker** | 种子账号 `super` / `admin` / `user` 三者的口令哈希完全相同，实测对应口令 `123456`；该种子在任何环境的**空库启动时自动写入**，`super`/`admin` 还是 `is_superuser=true`；README 直接公开该口令 | `backend/sql/sys_user.json:3-4,23-24,43-44`（同一 pbkdf2 哈希）、`backend/app/scripts/initialize.py:50-58,163-200`（无环境判断）、`README.md:66-67,86`；口令校验命令见 §7.1 | 1) 首次启动随机生成超管口令并一次性输出/落盘（或强制首次登录改密）；2) 删除 `sql/sys_user.json` 中的固定哈希，改为按环境注入；3) README 改为"首次初始化口令见控制台" |
| **S3** | **high** | 停用/删除用户、重置口令、撤销角色后**既有会话不被撤销**：认证只看 Redis 会话里的 `user_status`，每请求查库只校验"用户存在且未删除"，不校验 DB 的 `status`；会话滑动续期最长 7 天 | `backend/app/core/dependencies.py:162-182`（用会话里的 `user_status`，DB 查询未含 `status` 条件）、`backend/app/modules/system/user/service.py:145-168`（删除用户不清理会话）、`288-295`（重置口令不清理会话）、`backend/app/modules/system/auth/service.py:531-533`（仅登出自身会话）；权限取自会话快照 `dependencies.py:185-189` | 1) `_authenticate` 增加 `user_obj.status != 0 → 401` 并即时清理会话；2) 停用/删除/改密/角色变更后按 `user_id` 扫描并删除 `user_session:{sid}`；3) 会话内权限改为每请求/短 TTL 重算 |
| **S4** | **high** | 第三方 OAuth 的 `redirect_uri` 完全由请求方指定、无任何域名白名单校验；登录成功后按该地址 302 重定向并把 `access_token`/`refresh_token` 拼进 **URL query** → 钓鱼链接可让受害者把自己的令牌交到攻击者域 | `backend/app/modules/system/auth/oauth_service.py:410-439`（原样保存 `redirect_uri`）、`474-479` + `51-60`（成功重定向携带令牌）、`backend/app/modules/system/auth/controller.py:93-107`；`OAUTH_ALLOWED_HOSTS` 只校验回调域不校验前端回跳域（`setting.py:150`、`oauth_service.py:35-43`） | 1) `redirect_uri` 必须命中配置白名单，否则拒绝（缺失时才回落 `OAUTH_FRONTEND_FALLBACK`）；2) 令牌改为短时一次性 code，由前端换 token，禁止出现在 URL；3) 该端点对 `redirect_uri` 做同源/相对路径限制 |
| **S5** | **high** | `/api/v1/system/user/register` 无鉴权、无验证码、无开关，任何人可无限注册账号；同时登录验证码是"假滑块"（服务端只查 key 状态，无任何人机证据），`/captcha/get` + `/captcha/slider/complete` 可脚本化 → 账号爆破与刷号成本极低 | `backend/app/modules/system/user/controller.py:84-92`（无依赖）、`backend/app/core/dependencies.py:192-234`（授权类与注册无关）、`backend/app/modules/system/auth/service.py:540-549`（作者自述"只能提高滥用成本"）、`196-204`、`155-173`（限流仅按 IP，10 次/分钟） | 1) 注册接口加开关（默认关）+ 验证码 + 邮箱/短信校验；2) 换服务端出题的图形/行为验证码；3) 登录限流改为 账号+IP 双维度并收紧窗口 |
| **S6** | **high** | DEBUG 级别下数据库驱动把**含实参值的完整 SQL** 写入日志，口令哈希明文落盘；`backend/logs/fastapiadmin.log` 中已有 24 行包含种子口令哈希 | `backend/app/core/logger.py:57,71-94`（`aiosqlite` 未列入降噪名单）、实测 `backend/logs/fastapiadmin.log:8407`（见 §7.2）；`backend/.gitignore` 未忽略日志本身，但 `backend/logs` 已在根 `.gitignore` 中 | 1) 将 `aiosqlite`/`aioboto3` 等驱动 logger 一并置为 WARNING；2) DEBUG 级别禁止写文件 sink，或对 SQL 值做脱敏；3) 清理现存日志并按需轮换密钥（哈希已在本地明文出现） |

### 1.2 可排期修复（medium）

| ID | 级别 | 问题 | 关键证据 | 修复建议 |
|----|------|------|---------|---------|
| **S7** | medium | 生产环境**无条件暴露** API 文档与 OpenAPI 规范（`register_docs` 无环境判断），且 `/api/v1/openapi.json` 经 nginx `/api/v1` 代理可直接访问 → 完整接口/参数/字段结构外泄 | `backend/app/__init__.py:95-123`、`backend/app/config/setting.py:302-321`（只关 `docs_url`，`openapi_url` 仍默认）、`docker/nginx/nginx.conf:116-135` | 生产环境不注册 `/docs`、`/redoc`，并设置 `openapi_url=None` 或用管理员鉴权包裹 |
| **S8** | medium | 未鉴权接口暴露系统配置与业务数据：`/api/v1/system/param/info`（全部系统参数，含 IP 黑白名单、演示开关）、`/dict/data/info/{type}`、`/versions/published`、`/monitor/health/check`（版本+环境+DB/Redis 状态）、`/monitor/health/stream` | `backend/app/modules/system/params/controller.py:31-36`、`backend/app/modules/system/params/service.py:101-118`、`backend/app/modules/system/dict/controller.py:180-186`、`backend/app/modules/system/versions/controller.py:36-44`、`backend/app/modules/monitor/health/controller.py:20-45` | 除健康探针外全部补 `get_current_user`；健康接口只返回 `ok/not ok`，版本与环境写入内部监控 |
| **S9** | medium | CORS 默认"任意来源"且 `allow_credentials=True`（`PROD_CORS_ORIGINS` 为空即回落 `["*"]`），生产亦是 | `backend/app/config/setting.py:57,60,243-248`、`backend/app/core/middlewares.py:22-33`；实测 starlette 0.52.1 行为：简单请求回 `Access-Control-Allow-Origin: *`（`.venv/.../starlette/middleware/cors.py:40-46`） | 生产强制配置显式域名清单并在启动期校验非空（空即启动失败）；不使用时关掉 `ALLOW_CREDENTIALS` |
| **S10** | medium | 代码生成器可执行任意 SQL（`POST /generator/gencode/create` 的 `body.sql` 直送 `execute_sql`）；定时任务默认允许执行用户提交代码块（`exec`，等价 RCE） | `backend/app/modules/generator/gencode/controller.py:76-83`、`backend/app/modules/generator/gencode/crud.py:333-342`、`backend/app/config/setting.py:127`、`backend/app/core/ap_scheduler.py:548-563`、`backend/app/modules/task/cronjob/node/service.py:284,371` | 生产 `SCHEDULER_ALLOW_CODE_EXEC=False`（并写入 `.env.example`/部署模板）；代码生成器移除"执行任意 SQL"入口，或降级为仅白名单 DDL 模板 |
| **S11** | medium | 存储源支持 `local` 协议且 `host` 即根目录，配合浏览/下载/删除/重命名接口 → 具备存储权限者可读写服务器任意目录；FTP/SFTP/S3 等协议可作为 SSRF 探测内网 | `backend/app/modules/task/storage/core/local_adapter.py:15-26,43-59`、`backend/app/modules/task/storage/node/controller.py:81-89`（仅看 permission）、`backend/app/modules/task/storage/browse/controller.py:43-75` | local 协议根目录限定在 `static/upload` 且做 `resolve()+is_relative_to` 校验；远端协议加内网网段黑名单与出站策略；该类权限收敛到超管 |
| **S12** | medium | 缓存监控接口能按 `{cache_name}:{cache_key}` 组合读取**任意 Redis 键**（含 `user_session:*` 会话 JSON：手机号/邮箱/权限）；`/cache/clear` 清空整个 DB（会话、调度器 jobstore 一并丢失） | `backend/app/modules/monitor/cache/service.py:34-40,43-57`、`backend/app/modules/monitor/cache/controller.py:37-59`（仅 `module_monitor:cache:*`） | 仅允许白名单前缀（如 `system_config:*`）；键名做严格格式校验；`clear` 改为按前缀清理并二次确认 |
| **S13** | medium | 口令策略被"合法绕过"：批量导入用户与导入更新会把口令重置为固定 `123456`（`PASSWORD_IMPORT_DEFAULT`），且无首次登录强制改密；导入仅校验用户名唯一、不校验手机号唯一 | `backend/app/config/setting.py:132-134`、`backend/app/modules/system/user/service.py:370-445`（`425` 固定口令、`434` 更新既有用户）、`backend/app/modules/system/user/model.py:68-71`（`mobile` 非唯一）、`backend/app/modules/system/auth/wx_mini_service.py:302-318`（按手机号登录取 `.first()`） | 导入时随机口令并要求首登改密；`mobile` 加唯一约束（含软删除场景）；手机号登录命中多条时报错 |
| **S14** | medium | 文件上传允许 `.svg`，上传目录 `static/upload` 以 `/static` 同源直出 → 具备上传权限者可构造同源存储型 XSS，窃取 localStorage 中的令牌；声明 MIME 与文件真实内容不一致时只记 warning 不拦截 | `backend/app/config/setting.py:213-222`、`backend/app/__init__.py:89-92`、`backend/app/utils/upload_util.py:215-234`（`return True` 恒定）、前端令牌在 localStorage：`frontend/web/src/utils/auth/index.ts:24-50`。缓解现状：nginx 已全局下发 `X-Content-Type-Options: nosniff` + `Referrer-Policy`（`docker/nginx/nginx.conf:59-63`），可挡住"改扩展名伪装 HTML"的嗅探变体，但**不阻止** `image/svg+xml` 内嵌脚本被执行，且无 CSP；直连后端 8001（绕过 nginx）时全部安全头缺失 | 移除 `.svg`（或强制 `Content-Disposition: attachment` + 独立域）；补充 CSP；在应用层也下发 nosniff（覆盖直连场景）；MIME 不匹配即拒绝 |
| **S15** | medium | 工单富文本在**服务端未做任何 HTML 清洗**，仅 Web 端渲染时用 DOMPurify 兜底；公告内容有服务端清洗但工单没有 → 其它客户端（移动端/导出/富文本回显）存在存储型 XSS | `backend/app/modules/system/notice/schema.py:10,30-33`（公告有）、`backend/app/modules/system/ticket/*.py`（grep `sanitize` 无命中）、`frontend/web/src/views/module_system/ticket/index.vue:187,198,240,403,865` | 与公告一致，在 ticket `schema.py` 用 `sanitize_html` 入库清洗；导出/其它渲染端同样清洗 |

### 1.3 加固项（low）

| ID | 级别 | 问题 | 关键证据 | 修复建议 |
|----|------|------|---------|---------|
| **S16** | low | `AuthPermission()` 传空权限列表时等于"仅需登录"，`/task/storage/transfer/stream` 即用此写法（当前只推送本人任务，影响有限） | `backend/app/core/dependencies.py:219-220`、`backend/app/modules/task/storage/transfer/controller.py:107` | 空权限列表直接 `raise`，避免"忘记填权限 = 放行" |
| **S17** | low | `WHITE_API_LIST_PATH` 的注释与命名（"无需认证即可访问"）与实际用途（仅演示模式写保护放行）不一致；`/user/current/info` 等被列入却仍需认证 → 误导后续维护者 | `backend/app/config/setting.py:188-201`、验证只用在一处：`backend/app/core/middlewares.py:55` | 改名为 `DEMO_WRITE_ALLOWLIST` 并修正注释 |
| **S18** | low | 无全局鉴权中间件，鉴权完全依赖每个 endpoint 自觉声明依赖 → **默认 fail-open**，本轮即发现 6 个接口漏加（S5/S8） | `backend/app/__init__.py:69-74`（`MIDDLEWARE_LIST` 无鉴权件）、`backend/app/api/v1/routers.py:66-71` | 增加"默认拒绝"的全局依赖/启动期自检：扫描所有路由必须在白名单内或包含 `get_current_user` |
| **S19** | low | 数据权限（data_scope）实现依赖模型有 `created_id`，无该字段的模型完全不参与过滤（登录/操作日志、字典、参数、定时任务等） | `backend/app/core/permission.py:29-40`、`backend/app/core/base_crud.py:321-325`、`backend/app/modules/system/log/model.py:23,40`、`backend/app/modules/task/cronjob/job/model.py:7` | 明确这些表的可见范围并写进权限矩阵；日志类接口保持管理员专属 |
| **S20** | low | 前端"锁屏加密密钥"`VITE_LOCK_ENCRYPT_KEY = s3cur3k3y4adpro` 硬编码，且该文件（`frontend/web/.env`）**当前仍被 git 跟踪**（`.gitignore` 后来才加入该路径，已跟踪文件不会被自动忽略） | `frontend/web/.env:25`（`git ls-files --error-unmatch frontend/web/.env` 命中）、`frontend/web/src/layouts/fa-screen-lock/index.vue:168` | 客户端固定密钥无法真正保密，锁屏只作"防窥"用途，不得复用为任何数据加密密钥；如需保留该文件，请 `git rm --cached frontend/web/.env` 并改用 `.example` |
| **S21** | low | `.env.prod` 中的 `DEMO_ENABLE=True` 是**无效配置**（`Settings` 无该字段且 `extra="ignore"`），演示模式实际由 Redis 系统参数控制 → 运维误以为"演示写保护已开启" | `backend/env/.env.prod:13`、`backend/app/config/setting.py:16-21`（model_config）、`backend/app/core/middlewares.py:48-58`；已被 `docker/audit-deploy.md` 记为 medium | 删除该变量或实现为真实开关，并在文档中说明演示模式配置位置 |
| **S22** | low | 本地 `env/.env.dev`、`env/.env.prod` 含真实凭据（生产 DB/Redis 口令、可用 LLM API Key），且**历史上曾被提交进 git**（后续 `xxxx` 脱敏并删除文件，但旧提交仍在历史中） | `backend/env/.env.prod`（工作区文件）、`git log -S "FastApi123abc"` 命中 `2ba5b321`、`16054f6c`、`3b45ca2b` 等（见 §7.3） | 视为已泄露：轮换全部相关口令与 API Key；历史清理（`git filter-repo`）或直接废弃该仓库副本 |
| **S23** | low | 令牌过期语义失效：滑动续期开启时 JWT 的 `exp` **完全不校验**，访问令牌在会话存活期内（最长 7 天）永远有效；且 `_authenticate` 不比对 Redis 中存的活动令牌，无法撤销单个令牌（只能整体删会话） | `backend/app/config/setting.py:71`、`backend/app/core/dependencies.py:105-106`、`backend/app/core/security.py:119-139`、`backend/app/modules/system/auth/service.py:531-533` | 滑动续期改为"服务端 TTL 决定、但 JWT exp 仍校验一个较短上限"；`_authenticate` 比对 `access_token:{sid}` 的值，实现单令牌吊销 |

---

## 2. 详细结论（可利用性判断）

### S1 [blocker] JWT 签名密钥为公开默认值（可伪造令牌 + 可解密落库密文）

**事实**

- `SECRET_KEY` 的声明带默认值，且注释声称"必须通过环境变量设置，无默认值"，但代码并未强制：
  `backend/app/config/setting.py:66`
  ```python
  SECRET_KEY: str = "fastapiadmin-dev-secret-key-do-not-use-in-production"
  ```
- `backend/env/.env.dev`、`backend/env/.env.prod` **都不包含 `SECRET_KEY`**（见 §7.4 的 `grep` 结果），docker 编排同样未注入（`docker/audit-deploy.md` B1）。配置源为 `.env.{ENVIRONMENT}`（`setting.py:16-21,324-329`），因此所有环境实际使用上述公开字符串。
- 令牌签发/校验都使用该密钥与 `HS256`：`backend/app/core/security.py:112-116`、`139`。`algorithms` 固定为配置算法（无 `alg=none` 风险）。
- 该密钥同时是 `CryptoUtil` 数据加密主密钥的派生源（`DATA_ENCRYPTION_KEY` 默认 `None`）：`backend/app/utils/crypto_util.py:35-55`。

**可利用性（分两条链，均有前置条件，已按现实性排序）**

1. **链 A（有明确前置，可完整冒充超管）**：`/api/v1/monitor/online/list` 返回全部在线会话的完整 JSON，**包含 `session_id`**（`backend/app/modules/monitor/online/service.py:20-52`；`OnlineOutSchema` 继承 `SessionInfoSchema.session_id`：`backend/app/modules/monitor/online/schema.py:7-8`、`backend/app/core/base_schema.py:78`）。任一持有 `module_monitor:online:query` 的账号即可拿到超管的 `session_id`，随后用公开密钥离线签发
   `{"sub": "<超管 session_id>", "is_refresh": false, "exp": <任意未来时间>}`
   即可通过 `_authenticate`（它只要求 Redis 中存在 `user_session:{sub}`，并信任会话内的 `permissions`/`is_superuser`），无需口令即获得超管权限。
2. **链 B（无额外权限，危害较小）**：任意已认证用户（含 S5 自助注册的零权限账号）都能签发自己 `session_id` 的令牌并随意设置 `exp`，绕过令牌过期（因 S23 的滑动模式跳过 `exp` 校验）。

**为什么不能只依赖 Redis 会话**：`_authenticate`（`backend/app/core/dependencies.py:110-189`）只用 `sub` 去 Redis 取会话，**从不比较请求令牌与 `access_token:{sid}` 中存的值**，因此"签名正确 + 会话存在"即放行；密钥公开就等于"任意会话可被重新签发"。

**修复**：见 §1.1 S1；另建议把权限/超管标记从会话快照改为每请求查库，并让 `_authenticate` 比对 Redis 中存的活动令牌（实现真正可撤销）。

### S2 [blocker] 种子账号固定弱口令 `123456`（超管可被直接登录）

**事实**

- 三个种子用户口令哈希完全相同：`backend/sql/sys_user.json:4,24,44` 均为
  `$pbkdf2-sha256$600000$XX20aO1v73xS0JnoewXNtw==$PEaVHV1N5L7PfYQw2lCAQOc4hAEyCiwsGR48/jgVBjU=`
  其中 `super`、`admin` 为 `is_superuser: true`。
- 该哈希在本地按实现（PBKDF2-HMAC-SHA256、60 万次迭代、salt 为 `base64.b64decode(salt_b64)`，见 `backend/app/utils/password_util.py:42-59`）复算，命中口令 `123456`（命令与输出见 §7.1）。
- 种子数据在**任何环境的空库启动时**写入，无环境判断：`backend/app/scripts/initialize.py:50-58`（`init_db` → `__init_data`）、`163-200`（表为空即灌入）；`lifespan` 在应用启动时调用（`backend/app/__init__.py:30`）。
- README 公开该口令：`README.md:66-67,86`（`admin` / `123456`）。

**可利用性**：对任何"用本项目默认方式部署、未改口令"的实例，攻击者只需 `POST /api/v1/system/auth/login`（默认 `CAPTCHA_ENABLE=True`，但见 S5：滑块可脚本化）即可获得超管权限。**无需任何前置知识**，是该仓库最高可利用性的问题。

**修复**：见 §1.1 S2。注意口令策略（最少 2 类字符，`password_util.py:73-87`）对种子数据无效——`123456` 是纯数字。

### S3 [high] 停用/删除/改密/撤权后会话不失效（最长 7 天）

**事实**

- 认证读取的"用户状态"来自**登录时写入 Redis 的会话快照**，而不是数据库当前值：
  `backend/app/core/dependencies.py:162-166`
  ```python
  user_status = user_info.get("user_status", 0)
  ...
  if user_status == 1:
      raise CustomException(msg="用户已被停用", ...)
  ```
- 每请求的数据库校验只判断"存在且未软删"，**没有 `status` 条件**：`dependencies.py:171-182`。
- `set_available`（停用/启用）只写库不清理会话：`backend/app/modules/system/user/service.py:269-273`；删除用户（`145-168`）、重置口令（`288-295`）、角色授权变更（`backend/app/modules/system/role/service.py` 的授权接口）同样不清理会话。
- 会话存活上限：`SESSION_MAX_LIFETIME_SECONDS = 7 天`，且滑动续期在每次请求时刷新 TTL（`setting.py:71-72`、`dependencies.py:124-156`）。

**可利用性**：管理员发现异常账号后"停用/改密/撤角色"，被处置账号在会话到期前（活跃时被不断续期，最长 7 天）仍可调用全部原权限接口；权限列表也是会话快照（`dependencies.py:185-189`），撤权不生效。属于"处置无效"类风险，需与 S1（会话可被重新签发）一起看。

**修复**：见 §1.1 S3。

### S4 [high] OAuth `redirect_uri` 无白名单 → 令牌经 302 外泄（未启用第三方登录时为纯开放重定向）

**事实**

- `/api/v1/system/auth/oauth/{provider}/login?redirect_uri=...`：`redirect_uri` 由请求方任意指定，直接写入 state 缓存，无任何校验：
  `backend/app/modules/system/auth/oauth_service.py:410-439`
- 回调成功后按该地址重定向，并把令牌拼进 query：
  `oauth_service.py:474-479` + `51-60`
  ```python
  def _frontend_success_redirect(frontend_base, access_token, refresh_token, token_type):
      q = urlencode({"access_token": ..., "refresh_token": ..., "token_type": ...})
      return f"{frontend_base}{sep}{q}"
  ```
- `OAUTH_ALLOWED_HOSTS`（默认 `["*"]`，`setting.py:150`）只用于**回调域**校验（`oauth_service.py:35-43`），不约束前端回跳域。
- 异常分支同样会重定向到调用方给的地址：`oauth_service.py:439`（`_frontend_error_redirect(redirect_uri or fallback, e.msg)`）。

**可利用性**

- 前置：目标站点启用了 OAuth（`OAUTH_*_CLIENT_ID/SECRET` 非空，默认全空）。攻击者构造
  `https://victim/api/v1/system/auth/oauth/github/login?redirect_uri=https://evil.tld/cb`，诱导受害者点击并完成第三方登录 → 受害者浏览器被重定向到 `https://evil.tld/cb?access_token=...&refresh_token=...`，攻击者拿到可用令牌（凭证交换与用户绑定流程本身是正确的：state 一次性消费、provider 比对，见 `oauth_service.py:331-345`）。
- 前置不满足时（默认未配置渠道密钥）：仍是**开放重定向**（302 到任意域并带 `oauth_error`），可用于钓鱼跳板。
- 附带问题：令牌出现在 URL query，会进入浏览器历史、Referer 与网关访问日志。

**修复**：见 §1.1 S4。

### S5 [high] 开放注册 + 验证码无实质人机校验

**事实**

- `POST /api/v1/system/user/register` 无鉴权依赖、无验证码、无配置开关：`backend/app/modules/system/user/controller.py:84-92`。注册会创建 `status=0`、无角色用户（`backend/app/modules/system/user/service.py:308-327`），因此不构成直接的权限提升，但可用于刷号、占用用户名（含 `201-...` 类业务标识）、以及拿到一个"合法登录态"配合 S1/S16。
- 验证码：`CaptchaService` 自述"滑块是纯前端交互，服务端拿不到任何可信的人机证据（拖动轨迹可以伪造）"，实现只需 `captcha_key` + 指纹（IP+UA）+ ≥0.2s 间隔即可通过：`backend/app/modules/system/auth/service.py:540-549,610-648`。
- 登录限流按 IP 固定窗口 10 次/分钟，且对 `127.0.0.1`/`unknown` 直接放行：`auth/service.py:155-173`、`setting.py:73-74`。IP 来源依赖 `X-Real-IP`/`X-Forwarded-For` 且只在"直连对端是可信代理"时信任（`backend/app/utils/ip_local_util.py:24-60`）——但部署侧存在 `FORWARDED_ALLOW_IPS=*` + 8001 直连（`docker/audit-deploy.md` H2），一旦成立即可伪造 IP 绕过限流（见 §6 待验证）。
- `POST /api/v1/system/user/password/forget` 也未鉴权，但实现是**安全的**：不返回账号是否存在、不改密（`controller.py:74-81`、`service.py:297-306`），此项不作为问题。

**可利用性**：对已知用户名做口令爆破，自动化成本被限流（10 次/分钟/IP）压低但不为 0（约 14400 次/天/IP，配合代理池或伪造头可放大）；配合 S2 的弱口令几乎无意义——弱口令本身已被直接命中。

**修复**：见 §1.1 S5。

### S6 [high] 敏感数据（含口令哈希）写入日志文件

**事实**

- `setup_logger` 把根 logger 与所有既有 logger 接到 `InterceptHandler`，并把 `LOGGER_LEVEL`（dev 默认 `DEBUG`）作为级别；降噪白名单**不含 `aiosqlite`**：`backend/app/core/logger.py:49-94`（`aiomysql` 在列，`aiosqlite` 不在）。
- 实测日志中 24 行包含种子口令哈希明文，例如 `backend/logs/fastapiadmin.log:8407`：
  ```
  2026-10-04 03:57:52.396 | DEBUG | aiosqlite.core:_connection_worker_thread:62 - executing functools.partial(..., 'INSERT INTO sys_user (username, password, name, ...' ... pbkdf2-sha256$600000$XX20aO1v73xS0JnoewXNtw==$PEaVHV1N5L7PfYQw2lCAQOc4h
  ```
  （完整命令与输出见 §7.2）
- 生产 `LOGGER_LEVEL=INFO`（`backend/env/.env.prod`）时不触发；但 DEBUG 在 dev/调试环境是默认值，日志文件按天轮转保留 30 天（`logger.py:65-66`）。

**可利用性**：任何能读到 `backend/logs/*.log`（开发机共享、容器挂载、日志采集平台、备份）的人，直接获得口令哈希（PBKDF2 600k，离线爆破成本较高，但 S2 的种子哈希等于明文口令）以及 SQL 中的其它业务数据。

**修复**：见 §1.1 S6。

### S7 [medium] 生产无条件暴露 `/docs`、`/redoc`、`/openapi.json`

- `FASTAPI_CONFIG` 只把 `docs_url`/`redoc_url` 设为 `None`（`setting.py:308-310`），但 `register_docs` 又**无条件**注册 `/docs`、`/redoc`（`app/__init__.py:95-123`），无 `ENVIRONMENT` 判断；`openapi_url` 保持默认（`/openapi.json`）。
- `ROOT_PATH="/api/v1"` 经 Starlette 的 `get_route_path` 生效（`.venv/.../starlette/_utils.py:90-102`、`fastapi/applications.py:1160-1163`），故实际外部路径为 `/api/v1/docs`、`/api/v1/redoc`、`/api/v1/openapi.json`，全部落在 nginx 的 `location /api/v1` 代理范围内（`docker/nginx/nginx.conf:116-135`）。
- 可利用性：无需认证即可下载完整 API 结构（接口清单、请求/响应 schema、字段名），显著降低后续攻击成本。修复见速览表 S7。

### S8 [medium] 未鉴权接口暴露系统配置与业务数据

已确认"无任何鉴权依赖"的路由（解析全部 `controller.py` 的 decorator→签名块，见 §7.5）：

| 路由 | 说明 | 证据 |
|------|------|------|
| `GET /api/v1/system/param/info` | 返回 Redis 中全部系统参数（`sys_name`、`demo_enable`、`ip_white_list`、`ip_black_list`、`ip_location_enable` …） | `params/controller.py:31-36`、`params/service.py:101-118`、种子 `backend/sql/sys_param.json` |
| `GET /api/v1/system/dict/data/info/{dict_type}` | 任意字典类型的数据 | `dict/controller.py:180-186` |
| `GET /api/v1/system/versions/published` | 已发布版本列表（`auth = AuthSchema()` 空上下文） | `versions/controller.py:36-44` |
| `GET /api/v1/monitor/health/check`、`/health/stream` | 应用名/版本/环境 + DB/Redis 连通状态 | `monitor/health/controller.py:20-45`、`health/service.py:42-54` |
| `POST /api/v1/system/user/register`、`/password/forget` | 见 S5（`forget` 实现安全，仅列举） | `user/controller.py:74-92` |

说明：`setting.py:188-201` 把其中若干路径列进 `WHITE_API_LIST_PATH` 并注释为"无需认证即可访问"，但该列表**仅**用于演示模式写保护判断（`middlewares.py:55`，全仓唯一引用）。因此这些接口的公开性是"漏加依赖"而非"有意白名单"，详见 S17/S18。

### S9 [medium] CORS 任意来源 + 允许携带凭证

- `ALLOW_ORIGINS` 在非 PROD 或 `PROD_CORS_ORIGINS` 为空时返回 `["*"]`（`setting.py:243-248`），`ALLOW_CREDENTIALS=True`（`setting.py:60`）。
- 实测安装版本 starlette 0.52.1 的行为：`allow_all_origins=True` 时简单响应返回 `Access-Control-Allow-Origin: *` 且同时带 `Access-Control-Allow-Credentials: true`（`.venv/lib/python3.12/site-packages/starlette/middleware/cors.py:38-47`）；预检因 `allow_credentials` 会回显 Origin。
- 可利用性评估（不夸大）：本项目认证走 `Authorization` 头而非 Cookie（全仓 `grep set_cookie` 无命中），浏览器不会自动附带凭证，因此**当前不构成"任意站点读取已登录用户数据"**；但任意站点可读取所有未鉴权接口（S8）的响应，且一旦将来引入 Cookie 会话即变为严重问题。修复见速览表 S9。

### S10 [medium] 任意 SQL 执行与用户代码执行（默认开启）

- `POST /api/v1/generator/gencode/create` 把请求体 `sql` 直接送 `execute_sql(text(sql))`：`generator/gencode/controller.py:76-83`、`generator/gencode/crud.py:333-342`。权限 `module_generator:gencode:create`。
- 定时任务节点保存 `code_block` 并在调度器中 `exec(code_block, module.__dict__)`，仅由 `SCHEDULER_ALLOW_CODE_EXEC` 控制，**默认 True**（`setting.py:127`），env/部署模板均未覆盖（`backend/env/.env.prod` 无该键）；相关校验见 `ap_scheduler.py:548-563`、`task/cronjob/node/service.py:284,371`。权限 `module_task:cronjob:job:task`。
- 可利用性：拥有上述权限的账号可执行任意系统命令/任意 SQL（MySQL 下还可 `INTO OUTFILE` 写文件），属"设计内的高危能力"。若把这些权限授给非超管角色，实际后果等同服务器失陷。修复见速览表 S10。

### S11 [medium] 存储源 `local` 协议可读写服务器任意目录 / 远端协议 SSRF

- `LocalStorageAdapter.__init__` 把 `host` 当根目录，`_abs_path` 仅拒绝 `..`（`local_adapter.py:15-26`），因此 `host="/"` 或 `/etc` 即可浏览、下载、删除、重命名宿主机文件（`_sync_list/_sync_download/_sync_delete/_sync_rename`，`43-120`）；路径以 `/` 开头会被 `lstrip("/")` 归到 root 下，但 root 本身可被配置为任意目录。
- 节点创建/更新只需 `module_task:storage:node:create/update`（`storage/node/controller.py:81-101`）；浏览接口 `storage/browse/controller.py:28-135` 用同一套配置。
- FTP/SFTP/S3/OSS/COS/OBS 适配器接受用户填写的 `host:port`（`storage/node/model.py:14-16`），具备内网探测（SSRF）能力。
- 缓解：存储源口令以 Fernet 加密存储且不回显（`storage/node/schema.py:138-149`），但该密钥派生自 S1 的公开 `SECRET_KEY` → 加密对读代码者无效。
- 修复见速览表 S11。

### S12 [medium] 缓存监控可读任意 Redis 键 / 一键清库

- `get_monitor_cache_value` 拼接 `f"{cache_name}:{cache_key}"` 并直接 `get`（`monitor/cache/service.py:34-40`）；`cache_name` 填 `user_session`、`cache_key` 填某 `session_id` 即可读出该用户会话 JSON（手机号/邮箱/权限/IP）；也可读 `ai_model_config:items:{uid}`（`api_key` 密文，但 S1 使其可解）。
- `clear_monitor_cache_all` 清空整个 DB（`service.py:52-57`），会一并删除全部会话与调度器 jobstore，等于强制全员下线 + 任务状态丢失。
- 权限仅 `module_monitor:cache:query/delete`（`monitor/cache/controller.py:37-61`）。
- 修复见速览表 S12。

### S13 [medium] 固定默认口令的导入路径 + 手机号登录的账号匹配风险

- 批量导入：新用户口令固定为 `PASSWORD_IMPORT_DEFAULT="123456"`（`setting.py:134`、`user/service.py:425`）；`update_support=True` 时对已存在用户执行 `UserUpdateSchema(**user_data)` 更新，**同样把口令重置为 123456**（`user/service.py:428-437`）。权限 `module_system:user:import`。
- 无"首次登录必须改密"机制（全仓无 `must_change_password` 类字段）。
- `mobile` 仅有普通索引、非唯一（`user/model.py:71`），而导入路径不校验手机号唯一（只校验用户名，`user/service.py:428`）→ 可能出现两账号同手机号，微信手机号登录取 `.first()`（`wx_mini_service.py:302-318`），存在账号串号隐患。
- 修复见速览表 S13。

### S14 [medium] 上传 SVG + 同源静态直出 → 存储型 XSS 面

- 允许扩展名含 `.svg`（`setting.py:213-222`）；上传校验只对"危险扩展名"和允许清单做判断，内容类型不符仅 `logger.warning` 后 `return True`（`upload_util.py:215-234`）；文件路径穿越有校验（`upload_util.py:410-411,437-456`），下载有 `is_relative_to` 校验（`common/file/service.py:46-58`）——**这两处实现是好的**。
- 上传目录 `static/upload` 通过 `app.mount(settings.STATIC_URL, StaticFiles(...))` 同源直出（`app/__init__.py:89-92`）。
- 浏览器直接打开 `/static/upload/.../*.svg` 会以 `image/svg+xml` 渲染并执行内嵌脚本。缓解现状：nginx 在 http 级下发 `X-Content-Type-Options: nosniff`、`Referrer-Policy: strict-origin-when-cross-origin`（`docker/nginx/nginx.conf:59-63`），可挡住"改成 `.png` 伪装 HTML 被嗅探"的变体，但 `image/svg+xml` 是声明类型本身，nosniff 不阻止其脚本执行；仓库内 `grep Content-Security-Policy` 无命中，且应用层（直连 8001 或开发环境）没有任何安全响应头（`grep -rn "X-Content-Type-Options" backend/app` 无命中）。前端令牌存 localStorage（`frontend/web/src/utils/auth/index.ts:24-50`），一旦同源 XSS 成立即可窃取令牌（影响 S1 链 B 的令牌豁免）。
- 前置：攻击者需具备 `module_common:file:upload` 权限并诱导受害者打开链接。
- 修复见速览表 S14。

### S15 [medium] 工单富文本服务端未清洗

- 公告在入库前清洗（`notice/schema.py:10,30-33` 调 `sanitize_html`，白名单见 `utils/xss_util.py:99-118`）。
- 工单模块全目录 `grep sanitize` 无命中（`app/modules/system/ticket/`），仅前端渲染时用 DOMPurify（`frontend/web/src/views/module_system/ticket/index.vue:403,865`）。服务端不设防意味着任何非 Web 渲染方（移动端、导出、日志回显、第三方集成）会直接执行内容中的脚本。
- 修复见速览表 S15。

### S16–S23（low）

见 §1.3 速览表；其中 S18（默认 fail-open 的鉴权模型）是 S5/S8 的根因，建议优先以"启动期路由自检"的方式固化，避免后续新增接口再次漏加。

补充说明 S23（令牌过期语义）：认证时按 `decode_access_token(token, verify_exp=not settings.TOKEN_SLIDING_EXPIRE)` 调用（`dependencies.py:105-106`），默认 `TOKEN_SLIDING_EXPIRE=True`（`setting.py:71`）→ PyJWT 跳过 `exp` 校验，访问令牌只要会话仍在 Redis 中就有效；而会话在每次请求时被续期（`dependencies.py:124-156`），仅由 `SESSION_MAX_LIFETIME_SECONDS`（7 天）封顶。因此"12 小时的 access_token 有效期"这一配置（`ACCESS_TOKEN_EXPIRE_SECONDS`）在默认配置下**不产生实际约束**，且无法单独吊销某个已签发令牌（`logout` 直接删除整个会话，`auth/service.py:531-533`）。<br>可利用性：拿到任一份令牌（日志、代理缓存、浏览器历史、S4 的 URL 泄漏）后，其可用窗口从"12 小时"变为"受害者会话剩余寿命"，并可直接用公开密钥重签（S1）延长至任意时长。

---

## 3. 已核查、未发现问题的项（避免误判）

| 项 | 结论 | 证据 |
|----|------|------|
| SQL 注入（业务查询） | 未发现。查询条件全部经 SQLAlchemy 表达式构造；`search` 键来自 Pydantic schema 声明（`json_schema_extra={"q": ...}`），`order_by` 走 `getattr(model, field)` 属性访问 | `backend/app/core/base_crud.py:303-387`、`backend/app/core/base_schema.py:136-162` |
| 代码生成器列表查询的 f-string SQL | **无注入**：`where_sql` 只拼接固定片段，变量一律用绑定参数（`:name_kw` 等） | `backend/app/modules/generator/gencode/crud.py:176-226` |
| JWT 算法混淆（`alg=none`、RS/HS 混淆） | 未发现：`decode` 固定白名单算法为配置值 `HS256` | `backend/app/core/security.py:139` |
| 刷新令牌重放 | 有防护：refresh token 轮换 + 不一致即撤销整个会话 | `backend/app/modules/system/auth/service.py:449-463` |
| 登出 | 会话/双令牌均被删除（`logout` 需先通过认证） | `auth/service.py:522-537`、`auth/controller.py:82-90` |
| 越权混用"用户端/管理端令牌" | 未发现双端令牌体系；权限完全由 RBAC 会话决定，令牌本身不含角色信息 | `backend/app/core/base_schema.py:99-121`、`dependencies.py:185-189` |
| 垂直越权（普通用户访问管理接口） | 除 S8 所列公开接口与 S16 外，所有管理接口均带 `AuthPermission([...])`；`AuthPermission` 对无权限用户返回 403，`is_superuser` 才短路放行 | `backend/app/core/dependencies.py:206-234` |
| `AuthPermission` 通配符 | `*` / `*:*:*` 才短路，未发现空串短路 | `dependencies.py:222-223` |
| 水平越权（数据权限） | 已在 `base_crud._build_conditions` 统一注入 `Permission` 过滤，且 `created_id` 为空集合时降级为 `created_id == self.id` | `base_crud.py:321-325`、`permission.py:29-80` |
| 模板注入（Jinja2 SSTI） | 未发现：Jinja 模板来自仓库内固定文件，渲染上下文是 DB 元数据（值不参与模板语法） | `backend/app/modules/generator/gencode/jinja2_template_util.py:150-264` |
| 反序列化 | 仅 `pickle.loads` 用于读取 APScheduler 自身 jobstore 状态字节，非外部输入解码路径（不排除"能写 Redis 者"这一常规信任边界） | `backend/app/core/ap_scheduler.py:578,591` |
| 上传路径穿越 / 任意文件下载 | 有防护：文件名清洗 + `resolve().is_relative_to(UPLOAD_FILE_PATH)` 双重校验；下载同样校验 | `backend/app/utils/upload_util.py:107-124,410-456`、`backend/app/modules/common/file/service.py:46-58` |
| 操作日志敏感字段 | 有脱敏：请求体/响应体按敏感键名递归打码（含 `access_token`/`refresh_token`/`password`/`api_key` 等），文件对象不入库 | `backend/app/core/router_class.py:15-41,86-116` |
| 异常响应信息泄漏 | 生产环境不外泄 `data`/DB 细节（`ENVIRONMENT == PROD` 判断） | `backend/app/core/exceptions.py:72-74,115-130` |
| 存储源口令回显 | 不回显（`password` 字段 `exclude=True`，只给 `has_password`） | `backend/app/modules/task/storage/node/schema.py:138-149` |
| 用户列表/详情泄漏口令哈希 | 输出模型不含 `password` | `backend/app/modules/system/user/schema.py:218-237` |
| 注册/自助改资料的字段越权（mass assignment） | 未发现：`UserRegisterSchema` / `CurrentUserUpdateSchema` 均不含 `is_superuser`/`role_ids`/`status`，Pydantic 默认忽略多余字段 | `user/schema.py:25-33,159-183`、`user/controller.py:42-49,84-92` |
| 忘记密码接口 | 安全：不区分账号是否存在、不直接改密 | `user/controller.py:74-81`、`user/service.py:297-306` |
| 客户端 IP 伪造 | 实现是收敛的（仅在直连对端为可信代理时采信 `X-Real-IP`/右起取 XFF）；风险在部署侧（见 §6） | `backend/app/utils/ip_local_util.py:24-60` |
| 本地日志中的令牌 | 未发现 `Bearer`/JWT 落日志（`grep -c "Bearer " logs/*.log` = 0）；但存在 S6 的口令哈希问题 | §7.2 |
| 接口文档/静态资源鉴权 | 属于设计取舍（S7）而非"漏鉴权" | `app/__init__.py:95-123` |
| 安全响应头（nginx 层） | 已下发 `X-Frame-Options: SAMEORIGIN`、`X-Content-Type-Options: nosniff`、`X-XSS-Protection`、`Referrer-Policy: strict-origin-when-cross-origin`；缺 HSTS/CSP（与 t6 的 M7 一致），应用层直连时无任何安全头 | `docker/nginx/nginx.conf:59-63`；`grep -rn "X-Content-Type-Options" backend/app` 无命中 |

---

## 4. 最小修复路径（按投入产出排序）

**P0（当天可完成，阻断最高可利用性风险）**

1. `setting.py:66` 去掉 `SECRET_KEY` 默认值 → 改为必填并在启动期校验长度 ≥32；`env/.env.example` 增加 `SECRET_KEY=` 必填说明；现网轮换密钥并重新登录全体用户。
2. 处理种子口令：删除 `sql/sys_user.json` 的固定哈希或改为启动时随机生成 + 一次性输出；README 去除明文口令（S2）。
3. 部署侧落实 `docker/audit-deploy.md` 的 B1/B3（不要在镜像层烤入 `.env.prod`）与 P0 同步执行。
4. 关闭可达的公网调试面：生产不注册 `/docs`/`/redoc`，`openapi_url=None`（S7）；`SCHEDULER_ALLOW_CODE_EXEC=False`（S10）。

**P1（1–2 天，收敛授权与会话语义）**

5. `_authenticate` 增加 DB `status` 校验 + 会话比对（S3），并提供"按 user_id 清理会话"的服务方法，在停用/删除/改密/改角色处调用。
6. S8 的 6 个公开接口按需补 `get_current_user`；`AuthPermission` 空列表直接拒绝（S16）。
7. 新增启动期路由自检：遍历 `app.routes`，凡未含 `get_current_user`/白名单声明的路由打 warning 或直接失败（S18）。
8. OAuth `redirect_uri` 白名单（S4），令牌改为一次性 code 换取（参考 S4 修复项 2）。

**P2（排期，纵深防御）**

9. 口令与会话策略：注册开关默认关 + 真实验证码（S5）；导入随机口令 + 首登改密 + `mobile` 唯一约束（S13）。
10. 敏感面收敛：缓存监控键名白名单（S12）、存储源 local 根目录与远端协议出站限制（S11）、上传去掉 `.svg` 并加 `nosniff`/CSP（S14）、工单入库清洗（S15）。
11. 日志与配置卫生：`aiosqlite` 降噪、DEBUG 不落盘（S6）；强制生产 CORS 显式域名（S9）；清理无效的 `DEMO_ENABLE`、重命名 `WHITE_API_LIST_PATH`（S21/S17）；轮换所有历史泄露凭据（S22）。

---

## 5. 结论一致性说明

- 本报告与 `docker/audit-deploy.md` 的 S1/B1、S10/H2、S21（其 medium 列表中的 `DEMO_ENABLE`）指向同一批根因，视角不同（应用代码 vs 部署链路），修复时需要同时落地，避免"只改代码没改编排"（例如 `SECRET_KEY` 必须由编排注入）。
- 本报告未包含对前端 Web 应用与 uniapp 移动端的完整审计（前端仅核查了令牌存储与锁屏密钥两处与认证/敏感信息直接相关的点，S14/S20）。若需要覆盖 XSS/CSRF/依赖漏洞等前端面，应由前端审计任务单独产出。

---

## 6. 待验证清单（附验证方法）

| 编号 | 待验证问题 | 验证方法（只读、不改代码、不对外发包） |
|------|-----------|----------------------------------------|
| V1 | `X-Forwarded-For` 伪造是否真能绕过登录限流（依赖部署编排 `FORWARDED_ALLOW_IPS=*`、后端 8001 是否对外） | 在测试环境按 `docker/docker-compose.yaml` 启动后，用 `curl -H 'X-Forwarded-For: 1.2.3.4'` 连续请求 `/api/v1/system/auth/login`，观察是否出现"登录尝试过于频繁"；同时确认 8001 未被 nginx 屏蔽（t6 H2 已给静态证据，此条为动态确认） |
| V2 | 默认部署下 `GET /api/v1/param/info`、`/api/v1/openapi.json`、`/api/v1/docs` 是否真能匿名访问 | 启动后 `curl -i http://127.0.0.1:8001/api/v1/openapi.json`（不带 Authorization）；再经 nginx `curl -i https://<host>/api/v1/openapi.json` |
| V3 | OAuth 重定向链在"已配置渠道密钥"时的实际行为（本地默认未配置渠道密钥，无法端到端复现） | 在测试环境填入测试用 GitHub OAuth App（`OAUTH_GITHUB_CLIENT_ID/SECRET`），用 `redirect_uri=https://example.com/cb` 走完授权，检查 302 Location 是否携带 `access_token` |
| V4 | 停用用户后旧会话是否仍可用（S3 的动态确认） | 用 A 账号登录取 token → 管理员停用 A → 用同一 token 请求 `/api/v1/system/user/current/info`，观察是否仍 200 |
| V5 | `mobile` 是否存在重复数据（影响手机号登录串号） | 只读 SQL：`SELECT mobile, COUNT(*) FROM sys_user WHERE mobile IS NOT NULL GROUP BY mobile HAVING COUNT(*)>1;` |
| V6 | `backend/env/.env.dev|.env.prod` 中的真实凭据是否曾被推送到远端（本地 git 历史命中 `FastApi123abc`，但未确认远端是否可达） | `git log --all -S "FastApi123abc" --oneline`（已确认本地历史命中）、`git remote -v` 与远端仓库可见性核查；无论结果如何，按 S22 直接轮换 |
| V7 | 生产环境 `PROD_CORS_ORIGINS` 是否实际配置（代码默认回落到 `["*"]`） | 在目标环境执行 `python -c` 加载 `settings` 打印 `ALLOW_ORIGINS`；或查看部署用的 `.env`（`docker/.env` 未入库，需在服务器上核对） |
| V8 | 定时任务 `exec` 能力在生产是否真的开放 | 在目标环境读取 `SCHEDULER_ALLOW_CODE_EXEC` 生效值（`python -c "from app.config.setting import settings; print(settings.SCHEDULER_ALLOW_CODE_EXEC)"`） |
| V9 | 缓存监控接口能否读到他人会话（需一个具备 `module_monitor:cache:query` 的测试账号） | 测试环境：先 `GET /api/v1/monitor/online/list` 取 `session_id`，再 `GET /api/v1/monitor/cache/get/value/user_session/<sid>`，观察是否返回会话 JSON |

---

## 7. 附录：关键命令与输出

### 7.1 种子口令哈希 → 明文 `123456`（只读本地复算）

```
$ python3 - <<'EOF'
import hashlib, base64, hmac
salt = base64.b64decode("XX20aO1v73xS0JnoewXNtw==")
expected = base64.b64decode("PEaVHV1N5L7PfYQw2lCAQOc4hAEyCiwsGR48/jgVBjU=")
for c in ["123456","admin123","Admin123", ...]:
    if hmac.compare_digest(hashlib.pbkdf2_hmac('sha256', c.encode(), salt, 600000), expected):
        print("MATCH:", c)
EOF
MATCH: 123456
```

迭代次数/编码方式与实现一致：`backend/app/utils/password_util.py:12-14,25-29,42-59`。

### 7.2 日志中的口令哈希（本机只读 grep）

```
$ grep -rc "pbkdf2-sha256" backend/logs/fastapiadmin.log
24
$ sed -n '8407p' backend/logs/fastapiadmin.log | grep -o "pbkdf2-sha256\$[0-9]*\$[^']*"
pbkdf2-sha256$600000$XX20aO1v73xS0JnoewXNtw==$PEaVHV1N5L7PfYQw2lCAQOc4h
$ grep -rc "Bearer " backend/logs/*.log
backend/logs/fastapiadmin.log:0        # 未发现令牌落日志
```

### 7.3 git 历史中的真实凭据（只读）

```
$ git log --all --oneline -S "FastApi123abc"
2ba5b321 fix: 统一数据库和Redis的密码为小写格式
37d4dade feat(nginx): 更新SSL证书路径配置
c178b996 chore: 删除前后端环境配置文件
...
$ git show 2ba5b321 | grep -n "PASSWORD"
-      MYSQL_ROOT_PASSWORD: "FastApi123abc"
-      MYSQL_PASSWORD: "FastApi123abc"
-      DATABASE_PASSWORD: "FastApi123abc"
-      REDIS_PASSWORD: "FastApi123abc"
```

`git ls-files` 显示：`backend/env/.env.dev`、`backend/env/.env.prod` 已从索引移除（当前只保留 `.env.example`），但历史提交仍可检出（S22）；另需注意 `frontend/web/.env` **仍在跟踪中**（S20），即便 `.gitignore` 已列入该路径。

### 7.4 环境配置文件未注入 `SECRET_KEY`

```
$ grep -n "SECRET_KEY" backend/env/.env.dev backend/env/.env.prod backend/env/.env.example
(backend/env/.env.dev、.env.prod 无输出；.env.example 的注释里提到需修改 SECRET_KEY，但无该行)
```
`Settings.model_config.env_file = ENV_DIR / f".env.{ENVIRONMENT}"`（`backend/app/config/setting.py:16-21`）→ 因此实际生效值就是 `setting.py:66` 的默认字符串。

### 7.5 未鉴权路由的提取方式（只读静态解析）

对 `backend/app/**/controller.py` 的每个 `@XRouter.get|post|put|delete|patch` 装饰器块（装饰器 + 函数签名）做文本扫描，凡块内不含 `AuthPermission` 与 `get_current_user` 的即判为"无鉴权依赖"，得到 §1.1 S5 / §3 S8 的清单；同时用 `grep -rn "Security(AuthPermission" ` 交叉核对（189 处命中，覆盖 24 个 controller）。该方法只做静态判断，不含运行时行为（动态确认见 §6 V2）。

---

*报告结束。本报告为只读审计产出，未修改任何业务代码；仓库唯一新增文件即本报告。*
