# FastapiAdmin backend 只读审计报告

- 审计对象：`backend/`（v3.2.0，FastAPI 0.138 + SQLAlchemy 2.0 async + Redis + MySQL/PostgreSQL/SQLite + Alembic）
- 审计日期：本轮审计内（工作区 `/Users/tao/workspace/FastapiAdmin`）
- 审计方式：**只读**。除本报告外未修改/删除任何仓库文件，未启动数据库/Redis，未安装依赖，未提交 git。
- 规模：`app/` 下 216 个 `.py`，约 28,500 行（`modules/` 16 个业务模块约 20,000 行，`core+config+utils+common` 约 7,500 行）。

---

## 0. 可复现命令与结果（务必与「未验证项」区分）

| # | 命令 | 退出码 | 关键输出 |
|---|------|--------|----------|
| 1 | `cd backend && uv run pytest -q` | **2（工具失败）** | `error: Failed to initialize cache at /Users/tao/.cache/uv ... Operation not permitted (os error 1)`。uv 缓存目录在工作区之外，被本会话的文件沙箱拒绝；未申请提权（本会话提权被自动拒绝）。 |
| 1b | `cd backend && UV_CACHE_DIR=/tmp/uvcache-test uv run --no-sync pytest -q` | **0** | `2 passed in 2.44s` |
| 1c | `cd backend && .venv/bin/python -m pytest -q`（等价路径） | 0 | `2 passed` |
| 2 | `cd backend && uv run ruff check` | **2（同上，缓存失败）** | 同上 |
| 2b | `cd backend && UV_CACHE_DIR=/tmp/uvcache-test uv run --no-sync ruff check` | **0** | `All checks passed!` |

工具版本：uv 0.12.10、Python 3.12.12、pytest 9.0.2、ruff 0.14.13（均为仓库自带 `.venv` 中已安装版本）。

**结论**：静态检查（ruff）干净；测试套件只有 **2 个测试用例**（`tests/test_main.py::test_check_health`、`tests/test_migrations.py::test_bootstrap_matches_metadata`）对约 2.85 万行代码，功能覆盖率实质为零（见 M8）。

### 未验证项（明确标注，未编造）
- 本机 **3306 / 5432 / 6379 端口均不可达**（`nc -z` 探测），因此**所有需要真实 MySQL/PostgreSQL/Redis 的行为均未运行验证**：登录限流、Redis 会话续期、APScheduler 分布式锁与 jobstore、Alembic 对真实库的迁移、代码生成器对物理库的 Inspector 反射，均以**静态阅读 + 代码路径推演**为依据。
- `uv run`（不带 `--no-sync`）在本沙箱不可用，仅能用 `UV_CACHE_DIR` 指向可写目录 + `--no-sync` 复现；这一点本身属于「环境限制」，不是仓库缺陷。
- 测试使用的 sqlite + mock Redis 路径能通过，**不代表** MySQL/Redis 生产路径可用。

---

## 1. 安全问题（blocker / high）

### B1 [blocker] 代码生成器把未转义的用户输入渲染进「会被 import 的 Python 文件」→ 认证用户 RCE / 任意代码注入

**位置**
- 模板渲染无转义：`backend/app/modules/generator/gencode/jinja2_template_util.py:34`（`autoescape=False`）
- 渲染值直接嵌入 Python 字符串与标识符：
  - `backend/templates/python/model.py.jinja2:16`（`"""{{ function_name }}表"""` docstring）、`:19`、`:32`、`:34`、`:47`、`:54`、`:57`、`:59`（`comment='{{ column.column_comment }}'`）、`:61`（`'{{ table_name }}'`）
  - `backend/templates/python/schema.py.jinja2:17,22,24,26,28,30,32,34,36,44,49,51,53,55,57,65,71,76,77,79`（同理，且 `{{ column.column_name }}` 直接当字段名/标识符用）
  - `backend/templates/python/controller.py.jinja2:19,20,24,26,...`（`summary="获取{{ function_name }}详情"`、`tags=["{{ function_name }}模块"]`）
- 落盘位置就是应用自身的插件导入目录：`backend/app/modules/generator/gencode/service.py:663-693`（`_write_templates` → `BASE_DIR.parent.joinpath("backend/app/plugin/{package_name}/{module_name}/controller.py")`，另含 `model.py`/`schema.py`/`service.py`/`crud.py`/`__init__.py`）
- 启动时无条件 import：`backend/app/core/discover.py:52`（`glob("module_*/**/controller.py")`）+ `:74`（`importlib.import_module(module_path)`），且导入失败会**中止启动**（`:96-99`）
- 未受校验的输入来源：
  - `backend/app/modules/generator/gencode/schema.py:27-60`：`GenTableColumnSchema.column_name` / `column_comment` / `function_name` **没有任何 pattern/长度/字符集校验**（对比 `package_name`/`module_name`/`business_name` 都做了 slug 规范化）
  - `backend/app/modules/generator/gencode/service.py:487-502`：`update_gen_table` 把请求体里「库里没有的列」直接 `GenTableColumnSchema(table_id=..., **gen_table_column.model_dump(...))` 落库
  - `backend/app/modules/generator/gencode/gen_util.py:36-48`：`function_name` 默认取自**物理表的表注释**，而表注释可被「建表 SQL」功能（`service.py:376-457`）写入

**现象**：`generate_code`（`POST /generator/gencode/output/{table_name}`）会把上述字段原样写进 `.py` 源码。一个 `function_name` 形如 `x\n"""\nimport os\nos.system("id")\n"""\n` 或 `column_comment` 形如 `a'); import os; os.system('id'); #` 的值，会让生成的 `model.py` / `schema.py` 语法合法且**在模块顶层执行任意语句**；文件被写入 `app/plugin/**`，应用下次启动（或 dev reload）即被 `discover.py` 导入执行。

**为什么有害**：这是一个听起来只需要「代码生成」权限（`module_generator:gencode:update` / `:code`）的能力，实际等价于**服务器任意代码执行**。而且它是「先写文件、后建菜单」的顺序（`service.py:662-698` 注释明确：文件先写），菜单创建失败也不会回滚已写入的代码。开发环境 `DEBUG=True` → `reload=True`（`main.py:42`），写入即触发重载执行，攻击窗口从「下次重启」缩短到「保存即生效」。

**建议修法**（任一都不够，建议全做）
1. 生成模板改为**数据驱动**：`comment='...'` 用 `repr()`/`json.dumps()` 产出，标识符类字段先做 `^[a-z_][a-z0-9_]*$` 断言；`function_name` 这类自由文本只允许出现在渲染时转义的位置（或干脆不写入源码，改成常量表）。
2. 在 `GenTableColumnSchema` / `GenTableSchema` 上补齐校验：`column_name` 必须匹配 `^[A-Za-z_][A-Za-z0-9_]*$`，`column_comment` / `function_name` 禁止换行与引号（或长度上限 + 字符集白名单）。
3. 落盘后用 `ast.parse()` 校验生成的 `.py`，语法不合法直接拒绝并拒绝写盘（可防未来新增模板的注入面）。
4. 生成产物写入**独立输出目录**（如 `backend/generated/`，不进 `app/plugin`），改为人工审核后移动；至少不要落在 `discover.py` 会自动 import 的路径下。
5. 该能力单独拆分高权限（如仅超管），并在文档/权限名里写明「等价远程代码执行」。

---

### B2 [blocker] 数据权限（RBAC data_scope）在批量写路径上被绕过；多处 `set_available` 可直接改他人数据、甚至停用超管

**位置**
- 根因：`backend/app/core/base_crud.py`
  - 权限条件只在**读路径**注入：`_build_conditions`（`:300-330`，其中 `:316-318` 调 `Permission(...)._permission_condition()`）
  - 写路径直接用主键集合改库、**完全不注入权限条件**：`delete`（`:225-232`）、`clear`（`:234-239`）、`set`（`:241-251`）
- 依赖「调用方自己先查一遍」的守卫，而这些调用方漏了或只做了一半：
  - `backend/app/modules/system/notice/service.py:150-156` `NoticeService.set_available`：**零校验**直接 `set(ids=data.ids, status=...)`
  - `backend/app/modules/system/dict/service.py:221-230`（`DictTypeService`）与 `:510-519`（`DictDataService`）：同样**零校验**
  - `backend/app/modules/system/user/service.py:268-273` `UserService.set_available`：只对「查出来的」用户做 `is_superuser` 拦截，**没有校验 `len(users) == len(data.ids)`**；越权 id 查不出来 → 不触发拦截 → 但 `set(ids=data.ids)` 照改 → 可用任意（含超管）id 启停
  - `backend/app/modules/system/dept/service.py:90-105` `DeptService.set_available`：`get_child_recursion` 会**无条件 `ids.append(id)`**（`backend/app/utils/common_util.py:192-196`），所以请求里的 id 即使不在可见集合中也会进入 `total_ids` → `set()` 越权
  - `backend/app/modules/task/cronjob/node/service.py:149-164` `batch_set_status`：`if not obj: continue` 后仍 `set(ids=ids, ...)`
- 对照（说明这是「漏做」而非「设计」）：`role/service.py:195-209`、`position/service.py:86-92`、`notice/service.py:135-148`（delete）、`user/service.py:145-163`（delete）都显式做了「按可见集合校验每个 id」的前置检查。

**现象**：一个 `data_scope=1`（仅本人）的普通管理员，只要拥有对应按钮权限（`module_system:notice:patch`、`module_system:dict_type:patch`、`module_system:user:patch`、`module_system:dept:patch` 等），就能通过 `ids` 参数修改**任意租户/部门**的公告、字典、部门状态；对 `user:patch` 还能一并**停用超级管理员账号**（`get_list` 因权限过滤看不到超管 → 绕过 `is_superuser` 拦截 → `set(status=1)` 生效）。

**为什么有害**：`Permission` 类的类注释自称「为业务模型提供数据权限过滤功能」，但实现只在 SELECT 上生效，导致「查不到 ≠ 改不了」。这类越权不需要任何注入技巧，普通管理员账号 + 一个正常业务接口即可完成，属可直接利用的授权缺陷；「能停用超管」还是提权/拒绝服务链的一环。

**建议修法**
1. 把权限条件下沉到写路径：`delete` / `set` / `clear` 一律先经 `_build_conditions`（或构造 `WHERE pk IN (...) AND <permission_condition>`），从结构上让「越权 id 命中 0 行」；顺手用 `rowcount != len(set(ids))` 报错。这样「Service 忘记校验」最多是功能异常，不再是越权。
2. 过渡期先把上述 6 处调用点改成统一模板：`objs = await crud.get_list(search={"id": ("in", ids)})` → `if len(objs) != len(set(ids)): raise CustomException(...)` → 再 `set/delete`（参考 `role/service.py:195-209`）。
3. `get_child_recursion` / `get_parent_recursion` 增加 `visited` 集合（同时修 M5/H4），并**先校验入参 id 在可见集合内**再展开。
4. 补一条集成测试：以非超管 + `data_scope=1` 登录，对越权 id 调 `set_available`/`delete`，断言 4xx 且目标行未被修改。

---

### H1 [high] `SECRET_KEY` 有硬编码默认值；`.env.example` 未模板化该键；无启动期校验 → 生产可能用公开密钥签发 JWT

**位置**
- `backend/app/config/setting.py:66`：`SECRET_KEY: str = "fastapiadmin-dev-secret-key-do-not-use-in-production"  # ...（必须通过环境变量 SECRET_KEY 设置，无默认值）`——注释与代码自相矛盾，实际**有**默认值。
- `backend/env/.env.example:2` 的注释明确要求使用者修改 `SECRET_KEY`，但文件正文里**没有 `SECRET_KEY` 这一项**（也没有 `DATA_ENCRYPTION_KEY`）。
- 该密钥还被用来派生数据加密主密钥：`backend/app/utils/crypto_util.py:52-56`（`DATA_ENCRYPTION_KEY or SECRET_KEY` → HKDF）。
- 相关反证：`tests/conftest.py:33` 注释写「SECRET_KEY 必填项，固定注入保证测试确定性」——说明作者本意是「必填」，但 `Settings` 给了默认值，测试才需要手动注入。

**现象**：按仓库自带 `.env.example` 部署（不额外设置 `SECRET_KEY`）时，进程用公开已知的默认串签发/校验 JWT，并用它派生 Fernet 主密钥。

**为什么有害**：任何人可用默认串自行签发 `{"sub": "<任意 session_id>"}` 的 token（`app/core/security.py:99-116`，HS256）；虽然还需要 Redis 里存在对应 session（`app/core/dependencies.py:114-118`），但**数据加密**（存储源密码、AI 密钥，`crypto_util.py`）可被离线解密。此外默认值被写进代码仓库，属于「默认凭据」类配置缺陷。

**建议修法**
1. `SECRET_KEY: str = ""`，在 `Settings` 上加 `model_validator(mode="after")`：仅当 `ENVIRONMENT != dev` 时空值/等于默认串就直接 `raise`（fail-fast），或至少在 prod 打 `logger.critical` 并拒绝启动。
2. `.env.example` 补 `SECRET_KEY = `（并注释生成方式 `openssl rand -hex 32`）与 `DATA_ENCRYPTION_KEY`。
3. 把「默认串」改为不可能出现的哨兵值（如 `__CHANGE_ME__`），避免有人以为它是可用的密钥。
4. 统一 `model_config.env_file` 与 `get_settings()` 的 `ENVIRONMENT` 默认值（`setting.py:17` 用 `os.getenv('ENVIRONMENT')`（无默认）而 `:326` 用默认 `'dev'`），避免 `.env.None` 这种隐式路径。

---

### H2 [high] 定时任务「代码块」默认允许 `exec`，且带完整 builtins

**位置**
- 开关默认开：`backend/app/config/setting.py:127`：`SCHEDULER_ALLOW_CODE_EXEC: bool = True`
- 执行点：`backend/app/core/ap_scheduler.py:544-573`，关键两行 `module.__dict__["__builtins__"] = __builtins__`（`:562`）与 `exec(code_block, module.__dict__)`（`:563`）
- 代码块来源是业务表单字段：`backend/app/modules/task/cronjob/node/service.py:281-285`（`code_block = job_info.func`）、`:311`/`:330`（作为 job args 注册）、`:364-376`（手动执行）

**现象**：任何能创建/编辑「节点任务」的用户提交 `func` 即可在服务器上以应用进程权限执行任意 Python（无沙箱、无 AST 白名单、builtins 完整）。

**为什么有害**：与 B1 同类（认证用户 → RCE），且默认开启、只在注释里写「生产环境强烈建议设为 False」。多租户/多管理员后台里，这是「任务管理」权限被偷偷放大成「服务器控制权」。

**建议修法**
1. 默认值改 `False`；生产启动时若为 `True` 打印 `logger.critical`。
2. 改为白名单「内置处理器注册表」（node service 已有 `handlers/` 目录，如 `demo_handler.py`），`func` 只允许引用注册名；彻底删掉 `exec` 路径，或至少用 AST 校验（禁 `import`/`__`/属性访问）。
3. 若必须保留，放到独立执行器/子进程 + 降权用户 + 资源/网络限制，并单独授予权限标识。

---

### H3 [high] 操作日志的操作用户恒为 `unknown`（审计链断裂）

**位置**：`backend/app/core/router_class.py:119`
```python
"username": str(getattr(getattr(request.state, "ctx", None), "user_username", None) or "unknown"),
```
全仓库检索：`request.state.ctx` **只有这一处读取，没有任何一处写入**（`grep -rn "request\.state" app` 仅命中此文件）。同时日志记录体里也没有 `created_id`（`OperationLogRecord`，`:44-56`），而导出模板却包含 `created_id` 列（`backend/app/modules/system/log/service.py:118-130`）。

**现象**：所有 `task_operation_log`/operation log 记录的 `username` 都是 `unknown`，「谁改了什么」无法追查。

**为什么有害**：对后台管理系统，操作日志是唯一的追责证据来源（也是等保/审计要求的常见项）。当前它只能证明「某个请求发生过」，不能证明「谁发起」。B2 那种越权行为发生后，日志无法定位到账号。

**建议修法**：在 `AuthPermission.__call__` / `get_current_user`（`app/core/dependencies.py:206-234`、`:43-49`）里把认证后的 `auth.user.username`、`user_id` 写入 `request.state`（注意 `AuthSchema.user` 带 `exclude=True`，取 `auth.user.username` 即可）；`OperationLogRecord` 增加 `created_id`/`user_id` 字段并在 `_write_operation_log_async` 中落库；补一条测试断言登录用户的操作日志 `username` 非 `unknown`。

---

### H4 [high] 部门/菜单父子关系可造环 → `get_child_recursion` 无限递归（RecursionError / 500），并可被用来打爆自己的数据权限路径

**位置**
- 递归无 visited 保护：`backend/app/utils/common_util.py:181-196`（`get_child_recursion`）、`:141-155`（`get_parent_recursion` 同型）
- 可造环的写入口（都不校验 parent 是否为自己/后代）：
  - `backend/app/modules/system/dept/service.py:62-72`（`update` 只查重名/编码）
  - `backend/app/modules/system/menu/service.py:98-119`（`_validate_parent_child_type` 只校验父的 type，`X.parent_id = X`（type=1）可通过）
- 被环命中的调用点：`app/core/permission.py:119-124`（`_load_dept_children`，**每个使用 dept 数据权限的请求都会走到**）、`app/modules/system/dept/service.py:100-103`、`app/modules/system/menu/service.py:133-148`（delete/set_available）

**现象**：把部门 A 的 `parent_id` 设成 A（或 A↔B 互指）后，任何 `data_scope=2` 用户的下一次查询、或对该节点执行删除/启停，都会 `RecursionError: maximum recursion depth exceeded`（500）。菜单同理。

**为什么有害**：一个纯配置操作即可让**整个部门数据权限链路**报 500（不是单点功能坏，而是所有带 `created_id` 模型的读路径），属低成本自伤/拒绝服务；且脏数据持久化后即使重启也立刻复发。

**建议修法**：`update` 时校验 `data.parent_id != id` 且 `data.parent_id not in get_child_recursion(id, ...)`；两个递归函数加 `visited` 集合与深度上限（超限抛 `CustomException`）；在 Alembic 迁移或启动自检里检测并告警存量环。

---

### H5 [high] 异常处理器里的 `status.HTTP_403_SERVICE_UNAVAILABLE` 不存在 → 处理器自身抛 `AttributeError`

**位置**：`backend/app/core/exceptions.py:119`
```python
if "connect" in detail or "connection" in detail:
    return ErrorResponse(msg="数据库连接失败", status_code=status.HTTP_403_SERVICE_UNAVAILABLE, data=expose_detail)
```
实测（`.venv/bin/python`）：`starlette.status` 里 `HTTP_403_SERVICE_UNAVAILABLE` **不存在**（只有 `HTTP_403_FORBIDDEN` 与 `HTTP_503_SERVICE_UNAVAILABLE`），`'HTTP_403_SERVICE_UNAVAILABLE' in dir(status) → False`。ruff 不会发现（属性访问）。

**现象**：该分支一旦命中，`AttributeError` 在 ASGI 异常处理中间件里被抛出 → Starlette 兜底返回**纯文本 500**，既没有统一 JSON 信封，也没有可读原因（`logger.error` 在本行之后，也不会执行）。

**为什么有害**：这正是「数据库连不上」这个最需要清晰报错的场景，却退化成最难排查的 500 裸响应；同时说明这段代码从未被执行过（无覆盖）。另外该分支挂在 `isinstance(exc, IntegrityError)` 下（`:115`），而连接失败实际是 `OperationalError`/`InterfaceError`，即使名字修对了也**永远不会命中**，属双重失效。

**建议修法**：改成 `HTTP_503_SERVICE_UNAVAILABLE`，并把连接类错误判断从 `IntegrityError` 分支上移到 `SQLAlchemyError` 顶层（或在 `OperationalError` 分支里处理）；补一个「DB 不可达 → 503 JSON 信封」的测试（可用 `pytest.raise`/mock 引擎）。

---

### H6 [high] 上传：内容校验只记日志不拦截；默认允许 `.svg` 且静态同源提供 → 存储型 XSS；`file.size` 为 None 时无大小上限

**位置**
- `backend/app/utils/upload_util.py:216-234`（`validate_file_content_type`：类型不匹配只 `logger.warning`，**始终 `return True`**）
- 默认白名单含 `.svg`、`.ico`、`.xls/.xlsx`：`backend/app/config/setting.py:213-222`
- 上传目录通过静态路由同源暴露：`app/__init__.py:88-91`（`app.mount("/static", StaticFiles(directory=STATIC_DIR))`），落地目录 `settings.UPLOAD_FILE_PATH = Path("static/upload")`（`setting.py:211`）
- 大小校验依赖 `file.size`：`upload_util.py:249-251`（`if file.size and file.size > MAX_FILE_SIZE`），随后 `:421` `await file.read()` **整文件读入内存**

**现象**：上传一个内容为 `<svg xmlns="…"><script>fetch('/api/v1/system/user/current/info',{headers:{Authorization:'Bearer '+localStorage.token}})</script></svg>` 的 `.svg`（或把 `.html` 改名成 `.png` 绕过扩展名白名单——内容校验不拦），即可从 API 同源地址访问到它。`detect_file_type`（`:170-193`）根本不识别 SVG/HTML，所以 SVG 必然通过。前端 token 存于浏览器（`Authorization` 头），同源脚本可直接读取 → 管理员打开该 URL 即被接管。若经过代理导致分片传输使 `file.size` 为 `None`，则**完全没有大小限制**，且 `await file.read()` 把整个文件读进内存。

**为什么有害**：文件上传是后台系统里最常见的 XSS/RCE 落地通道；同源 + 无 `Content-Disposition`（静态挂载直接内联渲染 SVG）使 XSS 可靠触发，且可窃取会话。

**建议修法**
1. 内容校验改为**强制**：`detect_file_type` 无法识别或与声明扩展名不一致 → 抛 `CustomException`；补齐 SVG/HTML 魔数识别与内联白名单。
2. 从 `ALLOWED_EXTENSIONS` 移除 `.svg`（或对 SVG 做 DOMPurify/白名单化清洗后再存）。
3. 上传目录改为独立子域/独立静态目录，响应加 `Content-Disposition: attachment` + `X-Content-Type-Options: nosniff`。
4. 大小限制不依赖 `file.size`：流式读取时累加字节并在超限时中止；`MAX_FILE_SIZE` 同时用 `Content-Length` 预检。

---

## 2. 中等（medium）

### M1 [medium] `order_by` 完全由客户端控制且无字段白名单
- 位置：`backend/app/core/base_schema.py:141-162`（`order_by: Any`，仅承诺「JSON 数组」），解析处 `backend/app/core/base_crud.py:322-330`（`_parse_order`：`getattr(self.model, field)` → `asc/desc(...)`）
- 现象：`order_by=[{"任意属性名":"asc"}]` 进入 `getattr`；传 `__table__`/`metadata`/关系属性等会抛 `ArgumentError`，被 `page()` 的外层 `except` 包成 `CustomException(msg="分页查询失败: ...")`（默认 HTTP 500，`exceptions.py:41-55`），对客户端表现为「服务器错误」而非 400。
- 为什么有害：① 用户输入错误 → 500 而非 400，污染错误监控；② 可按未建索引列排序（如 `description`）造成慢查询，是低成本的接口级 DoS；③ 无白名单意味着模型新增敏感列后立刻对所有人开放排序侧信道。
- 建议修法：在 `PaginationQueryParam.validate_order_by` 里只接受 `{field: asc|desc}` 且 `field` 匹配 `^[a-z_][a-z0-9_]*$`；在 `_parse_order` 里用 `sa_inspect(model).columns` 白名单校验，非法字段抛 400 而不是 500。

### M2 [medium] 数据权限判定在每个读操作上额外查库，且 `_load_dept_children` 全表加载
- 位置：`backend/app/core/permission.py:44`（`_load_user_data_scopes`，每次 `_build_conditions` 都执行）、`:96-103`（`select(RoleModel.data_scope).join(RoleModel.users)`）、`:119-124`（`select(DeptModel)` **全表** + `get_child_recursion` 内存展开）
- 现象：`get`/`count`/`exists`/`get_list`/`page` 各触发 1 次权限查询；`data_scope=2` 时再全表扫一次部门。`exists()` 走 `count()`（`base_crud.py:88-90`）→ 一次「存在性判断」= 权限查询 + COUNT。
- 为什么有害：每个请求多 1–2 次 DB 往返；部门表大时每次查询都全量加载 + Python 递归，随规模线性恶化；也让 `page()` 这类本应 2 条的 SQL 变成 4 条。
- 建议修法：在 `AuthSchema`/`Redis` 会话里缓存一次「用户可见部门集合」（会话内不变，可直接放到登录时写入的 Redis session 或 `request.state`）；把部门子树改为单条递归 CTE（MySQL 8 / PostgreSQL 均支持）或按 `parent_path` 物化路径过滤。

### M3 [medium] 「建表 SQL」只校验顶层语句类型 → 放行 `CREATE TABLE ... AS SELECT`、`CREATE VIEW`、`CREATE INDEX`
- 位置：`backend/app/modules/generator/gencode/service.py:391-404`（`has_create = any(isinstance(s, Create) ...)`；禁止集合只覆盖 `Delete/Drop/Insert/TruncateTable/Update` 顶层节点）、`:430-444`（只重放 `Create/Comment/Alter`）
- 现象：`CREATE TABLE x AS SELECT * FROM sys_user`（CTAS）在 sqlglot 里是 `Create`，内层 `Select` 不会被禁止集合命中 → 直接执行，生成含敏感数据的副本表；`CREATE VIEW`/`CREATE INDEX` 同样被当作「建表」放行。
- 为什么有害：该接口的本意是「只允许建表」，实际打开了「以数据库权限复制任意表数据」「创建视图指向任意表」的口子；配合 `db/list` 导入还能把该表变成代码生成对象。
- 建议修法：只接受 `isinstance(s, Create)` 且 `s.kind.upper() == "TABLE"` 且 `s.expression` 为空（无 CTAS）；`Comment` 只允许 `TABLE`/`COLUMN`；拒绝一切非 `TABLE` 的 `Create`；执行前对重放后的 SQL 再做一次同规则校验。

### M4 [medium] 代码生成/字典删除存在 N+1 写放大
- 位置：`backend/app/modules/generator/gencode/service.py:349-368`（导入：每列 1 条 INSERT）、`:487-509`（编辑：每列 1 条 UPDATE/DELETE，含 `delete(ids=[db_id])` 逐列）、`:799-830`（每个按钮 1 次 `get` + 1 次 `create`，固定 9 个按钮 → 最多 18 条语句）
- 另见 `backend/app/modules/system/dict/service.py:200-203`（每个 dict_type 一次 `get_list` 判空）
- 现象：60 列表格导入 = 60 次 `flush+refresh`（`base_crud.create` 每次都 `flush()` + `refresh()` + 可能的 `joinedload` 回查，`base_crud.py:186-217`），一次「生成代码」= 十余条 INSERT。
- 为什么有害：整个请求共用一个事务（`dependencies.py:21-28`），语句数线性放大延长锁持有时间；MySQL/PostgreSQL 下大表导入/生成代码会明显变慢并加剧锁竞争。
- 建议修法：批量 `add_all` / `insert().values([...])`，必要时用 `executemany`；`create` 的 `refresh` 改为按需；按钮权限用 `permission in (...)` 一次查出已存在集合再差量创建；字典删除用 `exists()` 子查询或一次 `IN` 查询。

### M5 [medium] 时区口径混用：模型默认 UTC-aware，业务代码用 naive `datetime.now()`
- 位置：UTC 一侧 `backend/app/core/base_model.py:104,111-112`（`created_time/updated_time` 默认 `datetime.now(UTC)`）、`backend/app/core/base_crud.py:64`（软删除 `datetime.now(UTC)`）；本地时间一侧 `backend/app/modules/system/user/crud.py:40`（`last_login = datetime.now()`）、`backend/app/modules/system/log/service.py:146`（`cutoff = datetime.now() - timedelta(days=days)`）、`backend/app/modules/system/auth/service.py:372,479`（JWT exp 基线）
- 现象：`created_time`（UTC 墙钟写入）与 `last_login`（本地墙钟写入）在同一张 `sys_user` 表里混着存；`cleanup_expired_logs` 用本地时间与 UTC 墙钟比较。
- 为什么有害：① 日志清理边界偏移一个时区（以东八区为例多删 8 小时数据，或保留策略形同虚设）；② 「最后登录时间」与「创建时间」相差 8 小时，前端展示与运维排查都会误判；③ 任何跨时区迁移/多活部署都会放大。
- 建议修法：统一为「存 UTC、展示时按配置时区格式化」（`DateTime(timezone=True)` + `datetime.now(UTC)` 全量替换 naive 调用），前端序列化已由 `validator.py:DateTimeStr` 统一；补一条测试断言 `last_login` 与 `created_time` 同源。

### M6 [medium] `RedisCURD.get_keys` 走 `KEYS` 且被用于全库匹配
- 位置：`backend/app/core/redis_crud.py:89-102`（`KEYS pattern`），调用点 `backend/app/modules/monitor/cache/service.py:35,50,57,64`（其中 `:64` 是 `get_keys()` → `KEYS *`）
- 现象：缓存管理页面点「清除所有缓存」会对整个 Redis 实例执行 `KEYS *`。
- 为什么有害：`KEYS` 在单线程 Redis 上 O(N) 阻塞，会拖慢/卡死所有依赖 Redis 的请求（会话、限流、调度 jobstore）；生产数据量大时是明确的可用性事故点。
- 建议修法：改 `SCAN`（类内已有 `scan_keys`，`redis_crud.py:70-87`），或分页 + 分批 `UNLINK`；`KEYS` 路径加显式弃用告警。

### M7 [medium] 在线用户列表 N+1 + `zip(strict=True)` 在 Redis 出错时抛未捕获异常
- 位置：`backend/app/modules/monitor/online/service.py:23-25`（`scan_keys` → `mget` → `zip(keys, tokens, strict=True)`），循环内 `:35` 每个会话一次 `GET`，异常分支 `:59-62` 每个坏会话 3 次 `DELETE`
- 现象：列表中每个会话 1 次 Redis 往返（外加失效会话 3 次删除）；`mget` 内部异常时返回 `[]`（`redis_crud.py:59-68`），`strict=True` 使 `zip` 抛 `ValueError` → 未捕获 → 500。
- 为什么有害：会话多时页面变慢；Redis 抖动时该接口 500 而不是降级。
- 建议修法：`mget` 失败返回 `None` 并显式判空；用 Redis pipeline / `MGET` 一次取齐所有 `USER_SESSION`（`mget` 后逐个 `json.loads`）；失效会话用一次 `DEL` 多键删除。

### M8 [medium] 测试覆盖实质为零，且 `assert_route` 把「异常/500」当成通过
- 位置：`backend/tests/`（3 个文件共 324 行，2 个用例）、`backend/tests/conftest.py:243-277`（`assert_route`：`except Exception: return` 直接放过，`expected_status=None` 时只断言 `!= 404`）
- 现象：2.85 万行代码只有「健康检查」和「迁移零漂移」两个断言的守护；`assert_route` 这个为「模块化接口测试」准备的助手**没有任何测试使用**（`grep -rn assert_route tests` 只命中定义），而它的语义是「只要不是 404 就算过」。
- 为什么有害：本报告里 B1/B2/H1–H6 全部可以在 CI 无感地存在；任何重构（尤其是插件/生成器/权限）都没有安全网。
- 建议修法：① 至少为「认证→权限→CRUD」主链路补 happy path + 越权 4xx 用例（`assert_route` 的 `expected_status` 必填）；② 把 `except Exception: return` 改为失败；③ 加 `pytest --cov --cov-fail-under`（当前无覆盖率门禁）。

### M9 [medium] 用户角色/岗位「替换」语义在空列表时静默跳过
- 位置：`backend/app/modules/system/user/service.py:180-204`（`_set_user_roles` / `_set_user_positions` 开头 `if not role_ids: return`），调用点 `:112-113`、`:140-141`（`data.role_ids or []`）
- 现象：编辑用户时提交 `role_ids: []`（本意「清空所有角色」）不会清空；同一函数被 `delete()`（`:166-167`）复用且那里传 `role_objs=[]` 是有效的——同一语义两种行为。
- 为什么有害：管理员以为已回收权限，实际账号仍持有旧角色（最小权限原则失效），属静默的权限残留；也是审计时「配置与预期不符」的常见来源。
- 建议修法：区分「未提供」（`None` → 保持）与「提供空列表」（`[]` → 清空），签名改为 `role_ids: list[int] | None`；补测试固定这两种语义。

### M10 [medium] 配置/生命周期：引擎在 import 期创建、上传目录相对 CWD、`WORKERS>1` 未经真实多进程验证
- 位置：`backend/app/core/database.py:87-88`（模块级 `engine = create_sync_engine()`、`async_engine, async_db_session = create_async_engine_and_session()`）、`backend/app/config/setting.py:33`（`WORKERS`）、`:211`（`UPLOAD_FILE_PATH: Path = Path("static/upload")` 相对路径）、`backend/app/modules/common/file/service.py:52-56`（用同一相对根做 `is_relative_to` 校验）
- 现象：只要 `import app.core.database`（很多模块间接依赖）就会建立两个引擎；`uvicorn --factory app:create_app` 在 pre-fork（多 worker）场景下，若在 fork 前 import 就会把父进程的连接池句柄带进子进程（经典 fork 连接复用问题）。上传目录以进程 CWD 为基准解析。
- 为什么有害：① 从不同 CWD 启动（systemd `WorkingDirectory=/`、容器 workdir 变更）会让上传文件落到别处、`download` 校验根也随之变化，出现「上传成功但下载 404/非法路径」；② 多 worker 下的连接池/调度器行为未验证，`WORKERS>1` 的注释（`setting.py:33`）只写了「确保 Redis 共享 jobstore」。
- 建议修法：引擎改为 `lifespan` 内惰性创建（或用 `@lru_cache` 函数延迟到首次使用）；`UPLOAD_FILE_PATH` 改为基于 `path_conf.BASE_DIR` 的绝对路径；在文档/启动日志中固化「多 worker 部署须用 `app:create_app` factory 且不要在 fork 前 import DB 模块」。

### M11 [medium] OAuth 回调域名白名单默认关闭；`X-Real-IP` 在私网来源下被无条件信任
- 位置：`backend/app/config/setting.py:150`（`OAUTH_ALLOWED_HOSTS: list[str] = ["*"]`）、`backend/app/modules/system/auth/oauth_service.py:35-43`（`if allowed_hosts and allowed_hosts != ["*"]:` 才校验 Host）、`backend/app/utils/ip_local_util.py:44-50`（`TRUSTED_PROXY_HOPS > 0` 且对端是私网/回环时直接采用 `X-Real-IP`）、`setting.py:34`（`TRUSTED_PROXY_HOPS = 1` 默认）
- 现象：默认配置下 `redirect_uri` 由 `request.base_url`（即 Host 头）拼出，Host 注入不受任何校验；只要直连对端落在私网（docker/k8s 内网、跳板机、同网段主机），客户端就能伪造 `X-Real-IP` 影响登录限流与 IP 黑白名单（`app/core/middlewares.py:43-58`、`auth/service.py:161`）。
- 为什么有害：OAuth 授权码可能被重定向到攻击者域名；伪 IP 可直接绕过登录限流（`app/modules/system/auth/service.py:161-163` 还额外豁免 `127.0.0.1`，见 M12）与黑名单封禁。
- 建议修法：`OAUTH_ALLOWED_HOSTS` 默认改为部署域名（或改为「必须显式配置否则拒绝启动」）；私网来源不能作为信任代理的判据，应改为显式代理 IP/CIDR 白名单（`TRUSTED_PROXIES`）；启动日志打印生效的信任策略。

### M12 [medium] 登录限流可被绕过：豁免 `127.0.0.1`、仅按 IP、成功后不复位
- 位置：`backend/app/modules/system/auth/service.py:161-163`（`if not request_ip or request_ip in ("unknown", "127.0.0.1", "localhost"): return`）、`:164-173`（固定窗口 INCR）、`:209-242`（失败/成功分支）
- 现象：`get_client_ip` 从不返回字面量 `"unknown"`（`ip_local_util.py:35-60`），而配合 M11 的 `X-Real-IP` 信任，攻击者可直接把来源设成 `127.0.0.1` → **完全不进入限流计数**；此外计数只按 IP、永不按账号，成功后也不清零，分布式撞库（多 IP 打同一账号）无任何约束。
- 为什么有害：爆破/撞库防护实际上可被一行请求头绕过；`LOGIN_RATE_LIMIT_MAX_ATTEMPTS=10` 只能挡住最笨的脚本。
- 建议修法：删除 `127.0.0.1/localhost` 豁免（排障可另设开关）；增加「按账号」计数与指数退避；成功登录后清零该账号计数；把「未知来源」当作普通 IP 计数而不是豁免。

### M13 [medium] `execute_sql` 吞掉异常返回 False，DDL 部分成功无法感知
- 位置：`backend/app/modules/generator/gencode/crud.py:331-346`（`except Exception: logger.error(...); return False`），调用点 `backend/app/modules/generator/gencode/service.py:443-444`
- 现象：多条 DDL 逐条执行（`:430-444`），任一条失败只返回 `False` → 外层抛自定义异常，但**前面已成功的语句不会回滚**（MySQL DDL 隐式提交）。
- 为什么有害：用户看到「创建表结构失败」，库里却残留半张表；下次重试因「表已存在」被拒（`service.py:421-422`），需要人工清理；服务层也丢失了真实错误类型（只剩一句 `请检查数据库`）。
- 建议修法：`execute_sql` 抛原始异常（由 `handle_service_exception` 包装），错误信息带语句序号与方言原文；对 MySQL 显式提示「DDL 不可回滚，失败可能残留半成品」，并提供清理/重试入口。

---

## 3. 低（low）

### L1 [low] 错误响应/错误码在同一种语义下不一致
- `backend/app/core/dependencies.py:228` 用 `RET.FORBIDDEN`（403），`:232` 同为 403 却用 `RET.NO_PERMISSION`（10403）；`backend/app/common/response.py:70-78` 的 `ErrorResponse` 默认 `code=RET.ERROR.code=1`，于是 `HTTPException` 分支（`exceptions.py:76-85`）永远返回 `code=1` + 各自 `status_code`；`CustomException` 默认 `code=-1`（`exceptions.py:41-55`）。
- 前端若按 `code` 分支处理会踩坑（同一语义两个码）。建议：错误码与 HTTP 状态一一映射，统一由一个映射表产出；`ErrorResponse` 默认 `code` 由 `status_code` 推导。

### L2 [low] `require_superadmin` 是死代码，且权限不足时返回 500 而非 403
- `backend/app/core/exceptions.py:16-38`：全仓库无调用点（`grep -rn require_superadmin app` 只命中定义），且 `CustomException(msg="仅平台管理员可操作")` 使用默认 `status_code=500`。
- 建议：删除或改为 `status_code=403, code=RET.FORBIDDEN.code`；若保留，补使用点与测试。

### L3 [low] `AuthPermission` 不识别用户侧的 `*:*:*` 通配
- `backend/app/core/dependencies.py:219-232`：通配判断作用在**接口声明的** `self.permissions` 上；用户权限集合里即使含 `*:*:*`（RuoYi 习惯写法），`:230` 的 `any(perm in user_permissions ...)` 仍会拒绝。
- 影响：给非超管角色授 `*:*:*` 菜单后「勾了权限却全 403」（fail-closed，安全但难排查）。建议：显式支持 `user_permissions` 中含 `*` / `*:*:*` 时放行，并在权限说明里标注通配符语义。

### L4 [low] 文档/常量与实际实现不一致（易误判数据权限语义）
- `backend/app/core/base_model.py:47-56` 写「1:仅本人 2:本部门 3:本部门及以下 4:全部 5:自定义」；实际实现是 `app/core/permission.py:16-18` 的 `1/2/3 = 仅本人/本部门及以下/全部`（前端 `frontend/web/src/views/module_system/role/components/FaPermissonDrawer.vue:37-39` 与 `role/schema.py:25-30`、`role/model.py:72` 均为 1..3）。
- `backend/app/core/validator.py:300-330`（`role_permission_request_validator`）仍按 1..5 校验并生成错误文案（因 `RolePermissionSettingSchema` 已 `le=3`，该分支为死代码）。
- `backend/app/modules/system/role/model.py:41` 称 `sys_role_depts`「仅当 data_scope=5 时使用」，与 `role/service.py:163-165`（改数据权限时直接清空 dept 关联）矛盾。
- `backend/app/modules/system/log/service.py:118-130` 导出映射含 `created_id`，但 `OperationLogRecord`/模型无该字段（导出为空列）。
- 建议：统一按 1..3 修正注释与死代码；删除 `sys_role_depts` 相关残留描述（或补齐「自定义数据权限」实现）。

### L5 [low] `_effective_package_name` 从 `menu.route_path` 直接赋给 `package_name`，绕过 pydantic 校验器
- `backend/app/modules/generator/gencode/service.py:88-98`（`return seg if seg.startswith("module_") else f"module_{seg}"`）与 `:649`、`:1245` 直接**赋值**给已校验过的模型字段（pydantic 的 `field_validator` 不会因赋值再跑一次）。
- 现状：由于 `module_` 前缀约束，实测难以构造真正的路径穿越（`route_path` 首段永远是单段），但生成路径的合法性完全依赖调用方，属于脆弱点。
- 建议：抽一个 `_safe_slug()` 在赋值后再规范化一次，并断言结果匹配 `^module_[a-z0-9_]+$`；`generate_code` 落盘前用 `Path.resolve().is_relative_to(允许根)` 复核（可复用 `upload_util.py:454` 的写法）。

### L6 [low] 在线用户「强制下线」无归属校验（管理员作用域内的 IDOR）
- `backend/app/modules/monitor/online/service.py:69-78`（`delete_online(redis, session_id)` 直接删会话），session_id 来自客户端参数；受 `monitor:online:delete` 权限保护。
- 影响：在管理员之间无隔离（A 管理员可踢掉 B 管理员的会话）。建议：普通管理员仅能踢本部门/自己创建的下线范围，或至少记录操作日志（当前操作日志 `username` 恒为 unknown，见 H3，等于无痕）。

---

## 4. 按优先级排序的修复清单

| 优先级 | 编号 | 一句话动作 | 影响面 | 预估成本 |
|--------|------|-----------|--------|---------|
| P0 | B1 | 代码生成模板对 `function_name`/`column_comment`/`column_name` 做转义与字符集校验；生成后 `ast.parse` 校验；产物移出 `app/plugin` 自动导入路径 | 服务器 RCE | 1–2 天 |
| P0 | B2 | 把 `Permission` 条件下沉进 `base_crud` 的 `delete/set/clear`；并修 6 处未校验的 `set_available`（notice/dict×2/user/dept/node） | 越权写、可停用超管 | 1–2 天 |
| P0 | H1 | `SECRET_KEY` 去掉可用默认值 + prod 启动校验；`.env.example` 补模板项 | JWT 伪造 / 数据可解密 | 2–4 小时 |
| P0 | H2 | `SCHEDULER_ALLOW_CODE_EXEC` 默认改 `False`，`exec` 换成处理器注册表 | 认证用户 RCE | 0.5–1 天 |
| P0 | H4 | 部门/菜单父子加环检测；`get_child_recursion`/`get_parent_recursion` 加 visited + 深度上限 | 全量读路径 500 | 2–4 小时 |
| P0 | H3 | 认证后把 `username`/`user_id` 写入 `request.state`，操作日志落库并补 `created_id` | 审计不可用 | 2–3 小时 |
| P1 | H5 | 修 `HTTP_403_SERVICE_UNAVAILABLE` → 503，并把连接错误分支移出 `IntegrityError` | 故障期无可用报错 | 1 小时 |
| P1 | H6 | 上传内容类型强校验 + 去掉 `.svg` 内联 + 流式大小限制 + `nosniff`/`attachment` | 存储型 XSS / OOM | 0.5–1 天 |
| P1 | M12 | 去掉 `127.0.0.1` 限流豁免，加账号维度计数与成功后清零 | 爆破防护形同虚设 | 2–3 小时 |
| P1 | M11 | OAuth 域名白名单默认收紧；私网来源不再等价于「可信代理」 | 重定向劫持 / IP 伪造 | 3–4 小时 |
| P1 | M13 | `execute_sql` 抛原始异常，DDL 失败给出「不可回滚」提示与清理入口 | 半成品表残留 | 2 小时 |
| P2 | M1 | `order_by` 白名单校验，非法字段返回 400 | 500 噪音 + 排序 DoS | 2–3 小时 |
| P2 | M8 | CI 加主链路 + 越权用例，`assert_route` 不再吞异常，加覆盖率门禁 | 所有回归的护栏 | 1–2 天 |
| P2 | M2 | 权限/可见部门集合按请求缓存一次，部门子树用递归 CTE | 每请求多 1–2 次查询 | 0.5–1 天 |
| P2 | M9 | `role_ids`/`position_ids` 区分 None 与 [] | 权限残留 | 1–2 小时 |
| P2 | M4 | 代码生成/字典删除改批量写 | 事务时长与锁竞争 | 0.5–1 天 |
| P2 | M3 | 建表 SQL 只放行 `Create(kind=TABLE)` 且无 CTAS/VIEW/INDEX | 数据复制面 | 2–3 小时 |
| P2 | M5 | 时间统一「存 UTC」；修 `cleanup_expired_logs` 与 `last_login` | 日志保留 & 展示错乱 | 3–4 小时 |
| P3 | M6 | `get_keys` 换 `scan_keys`/`UNLINK` | Redis 阻塞 | 1–2 小时 |
| P3 | M7 | 在线列表改 `MGET` + 判空，去掉 `zip(strict=True)` 崩溃点 | 页面变慢 / 500 | 2 小时 |
| P3 | M10 | 引擎改 `lifespan` 惰性创建；`UPLOAD_FILE_PATH` 改绝对路径 | 多 worker / CWD 依赖 | 半天 |
| P3 | L1–L6 | 错误码统一、删死代码、修过期注释、`_effective_package_name` 再规范化、在线下线归属校验 | 可维护性/排查成本 | 1 天 |

建议的落地顺序（最小爆炸半径）：
1. **第一批（当天可完成）**：H1、H5、H3、H4、M12 — 都是低风险小改动，立刻消掉「密钥/审计/500/环/限流」五类问题。
2. **第二批**：B2（权限下沉，改完后 6 处 service 的临时校验可保留但不再是唯一防线）、M1、M9。
3. **第三批**：B1 + H2 + H6（三处「权限被放大成 RCE/XSS」的能力收口，需要产品侧确认能力边界与权限命名）。
4. **第四批**：M8 补测试护栏，其余 medium/low 按迭代消化。

---

## 5. 附：本轮确认「做得好」的部分（避免修复时误伤）

- **分层与依赖方向守得住**：`app/api/v1/routers.py` 只是路由总表；`app/core` 需要业务模型时一律函数内延迟导入并注明「守卫不变式 3」（`dependencies.py:172`、`permission.py:98-99,121`、`router_class.py:60`、`ap_scheduler.py:219-220,358`）；`app/utils`、`app/common` 不反向依赖 `modules`；`modules` 不依赖 `app.api`。
- **异步阻塞处理整体到位**：同步 SDK/CPU 密集操作普遍经 `asyncio.to_thread`（`excel_util.py:42,149`、`password_util.py:39,71`、`gencode/crud.py` 的 `_sync_*`、`storage/core/base.py:378-428` 统一包装各协议适配器），`monitor/server/service.py:27-28` 连 `socket.gethostbyname` 都做了下沉。
- **事务边界清晰**：请求级单事务 `db_getter`（`dependencies.py:21-28`），CRUD 只 `flush` 不 `commit`（`base_crud.py` 类注释）；后台任务/无上下文场景自建会话（`router_class.py:58-66`、`log/service.py:139-155`）。
- **存储源凭据处理规范**：`password` 落库前加密（`task/storage/node/service.py:116-135`）、返回模型显式排除并只暴露 `has_password`（`node/schema.py:141-153`）、未传新密码时保留旧密码 —— 与 H1 的 `SECRET_KEY` 形成鲜明对比，可作为整改模板。
- **分布式调度选主设计完整**：Redis 锁 + 续期 + 候选接管 + 退出释放（`ap_scheduler.py:76-192`），并有节点任务自愈对账（`:210-268`）。
- **静态检查干净**：`ruff check` 全量通过。
