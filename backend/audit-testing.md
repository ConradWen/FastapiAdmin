# FastapiAdmin 测试与可验证性审计（t3 / 只读审计）

- 审计人：测试工程师（team `fastapiadmin-audit`，task `t3`）
- 工作区：`/Users/tao/workspace/FastapiAdmin`
- 审计范围：`backend/tests`、`backend/pyproject.toml` 的 pytest 配置、`frontend/web` 的 vitest 与用例、`frontend/app`（uniapp）测试能力、仓库级 CI 配置
- 本轮约束：只读，除本报告外未修改/删除任何仓库文件；未安装依赖、未启服务、未提交 git

---

## 0. 结论摘要（TL;DR）

| 维度 | 现状 | 结论 |
| --- | --- | --- |
| 后端 pytest 用例数 | **2 个**（收集 2 / 通过 2 / 失败 0 / 跳过 0 / 退出码 0） | 能跑通，但等于没有回归网 |
| 后端被测模块 | 216 个 `.py`、28519 行 → 仅 `/monitor/health/check/` 1 个接口被断言 | 209 个 OpenAPI 操作里 1 个有断言 |
| 历史测试规模 | 2026-07-17（commit `158c14a4`）前仓库内 9 个测试文件共 **238 个 test 函数**；`.pytest_cache` 记录过 38 个文件 / **761 个 node id** | 测试能力被"重构"清空，无替代物 |
| 断言有效性 | 唯一的行为测试断言的是恒为 `True/0` 的字段 | 该用例无法失败 |
| 夹具质量 | 手写 AsyncMock Redis（未用已声明的 fakeredis）+ 模块级 `patch().start()` + 无逐用例隔离 | 夹具本身会掩盖缺陷 |
| 迁移测试 | 只覆盖 SQLite 下 `create_all ≡ metadata`；`app/alembic/versions/` **没有任何迁移文件** | `alembic upgrade` 路径零覆盖 |
| 前端 web vitest | **有真实可运行用例**：2 文件 / 10 用例 / 全通过 / 退出码 0 | 能力存在，但未进门禁 |
| uniapp | 无 vitest/jest、无 `test` script、0 个 spec | 测试能力为零 |
| CI | 仓库根 `.github/` 为空且未跟踪（`git ls-files .github` = 0）；`frontend/web/.github`、`frontend/app/.github` 不在仓库根 → **GitHub 不会运行任何 workflow** | 零门禁 |

一句话：**后端"可运行但无验证力"，前端 web 有少量真用例却无一环节强制运行，uniapp 与 CI 是空白。当前任何回归都只能靠人工点测发现。**

---

## 1. 命令与真实输出

### 1.1 后端：`cd backend && uv run pytest -q`

环境：`uv 0.12.10`（/opt/homebrew/bin/uv），Python 3.12.12，pytest 9.0.2，pytest-asyncio 1.4.0，anyio 4.12.1，`backend/.venv` 已存在。

**第一次（原样执行，未改任何环境变量）**：

```text
$ cd backend && uv run pytest -q
error: Failed to initialize cache at `/Users/tao/.cache/uv`
  Caused by: failed to open file `/Users/tao/.cache/uv/sdists-v9/.git`: Operation not permitted (os error 1)
EXIT=2
```

→ 失败原因是 `uv` 需要写 home 下的缓存目录（`~/.cache/uv`），在该沙箱内不可写，**与项目代码无关**。

**第二次（把 uv 缓存重定向到 /tmp，同一命令语义）**：

```text
$ cd backend && UV_CACHE_DIR=/tmp/uv-cache-test uv run pytest -q
..                                                                       [100%]
2 passed in 1.80s
EXIT=0
```

**详细模式（收集清单 + 结果）**：

```text
$ cd backend && UV_CACHE_DIR=/tmp/uv-cache-test uv run pytest -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.2, pluggy-1.6.0 -- .../backend/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /Users/tao/workspace/FastapiAdmin/backend
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.4.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, ...
collecting ... collected 2 items

tests/test_main.py::test_check_health PASSED                             [ 50%]
tests/test_migrations.py::test_bootstrap_matches_metadata PASSED         [100%]

============================== 2 passed in 2.02s ===============================
EXIT=0
```

**真实结果汇总**：收集 2、通过 2、失败 0、跳过 0、错误 0、退出码 0、耗时 ≈1.8–2.0s。

> 后续所有复现（探针脚本）改用 `backend/.venv/bin/python` 与带 `--no-sync` 的形式，避免 `uv` 再次触碰锁文件（见 §7 环境说明）。

### 1.2 前端 web：vitest

`frontend/web` 的 `node_modules` 已就绪（vitest 4.1.7）。

```text
$ cd frontend/web && ./node_modules/.bin/vitest run

 RUN  v4.1.7 /Users/tao/workspace/FastapiAdmin/frontend/web

 ✓ src/__tests__/smoke.spec.ts (3 tests) 24ms
stdout | src/__tests__/route-invariants.spec.ts > 静态路由 — 中间层不挂组件（深度跳级的前提） > ...
[i18n] 使用默认语言: zh

 ✓ src/__tests__/route-invariants.spec.ts (7 tests) 111ms

 Test Files  2 passed (2)
      Tests  10 passed (10)
   Duration  1.05s (transform 126ms, setup 0ms, import 91ms, tests 135ms, environment 1.36s)
EXIT=0
```

**真实结果汇总**：2 个测试文件、10 个用例、全部通过、退出码 0。

### 1.3 未执行的项目（说明原因，避免"看起来跑过了"）

| 项目 | 原因 |
| --- | --- |
| `pnpm test`（web） | `pnpm` 走 npm 源/网络，本轮禁止安装依赖；已直接用 `node_modules/.bin/vitest` |
| uniapp 任何测试 | 无测试脚本、无测试依赖、无用例，无可跑对象 |
| `pytest --cov` | `pytest-cov` / `coverage` 未安装（`import pytest_cov` → `ModuleNotFoundError`），且本轮不装依赖 → **无法给出行覆盖率数字**，报告中的"覆盖缺口"由路由表、模块清单与代码路径证据推导 |
| 集成/端到端、压测 | 本轮不启服务、不连真实 MySQL/Redis |

---

## 2. 测试资产现状与夹具审计

### 2.1 分层：名义三层，实际一层

| 层 | 目录/文件 | 实际内容 |
| --- | --- | --- |
| 单元测试 | — | **不存在**（历史上有 `tests/test_unit.py` 47 个用例，已不在仓库） |
| 集成/API 测试 | `tests/test_main.py` | 1 个健康检查断言 |
| 迁移守卫 | `tests/test_migrations.py` | 1 个 `create_all ≡ metadata`（SQLite）断言 |
| 共享夹具 | `tests/conftest.py`（277 行） | session 级 TestClient + 手写 Redis mock + 自建 lifespan |

`conftest.py` 自己声明的能力（第 1–5 行）是"模块化 API 接口测试共享 fixture"，但仓库里已经**没有任何调用 `assert_route` 的用例**（`grep -rn assert_route backend/tests` 只命中定义处），也就是这套夹具的消费者全部被删除了。

### 2.2 `conftest.py` 逐项问题（带行号）

1. **导入期副作用**（L26–L46）：在 import 时创建临时 SQLite 文件并改写 `os.environ` 与全局 `settings`；甚至用 `sys.path.insert` 兜底（L17）。任何新测试文件只要 import `conftest`，全进程配置即被改写。
2. **临时库即业务库、用完不删**（L26）：`tempfile.NamedTemporaryFile(suffix=".db", delete=False).name`，每次 session 生成新文件、从不清理；`/tmp` 会持续积累。
3. **无逐用例隔离**：`_api_client` 是 session 级 TestClient（L204–208），`auth_headers` 是 session 级（L223–232），全程共享同一个 app、同一个 SQLite 库、同一个 token。没有任何 per-test 事务回滚/清库 → **用例顺序会互相影响**，且无法并行（`-n`）。
4. **测试专用 lifespan 覆盖真实 lifespan**（L173–197）：只跑 `init_db()` + 注入 mock redis，并用 `UPDATE` 把 admin 密码重置成 `admin123`。真实启动路径中的 `init_agno_tables`、`redis_connect`、`ParamsService.init_cache`、`DictDataService.init_cache`、`SchedulerUtil.init_scheduler` 全部被绕过 → 启动期回归完全无覆盖；同时"改业务表数据"这个动作本身是测试污染。
5. **用手写 AsyncMock 顶替 Redis，而 `fakeredis` 才是已声明依赖**（L53–161）：`pyproject.toml` dev 组声明了 `fakeredis>=2.21.0,<3`，但全仓库除该行外**没有任何 `import fakeredis`**。手写 mock 的语义与真实 Redis 不一致：
   - `_redis_ttl` 恒返回 3600 或 -2（L85–86）→ TTL/续期逻辑无法验证；
   - `_redis_expire` 恒返回"键是否存在"且不改 TTL（L89–90）→ 过期语义假通过；
   - `_redis_keys` 只做前缀切割，不支持 `user:*:x` 等通配（L75–78）；
   - **缺失被业务代码使用的方法**：`incr`、`eval`、`mget`、`scan_iter`、`publish`、`pubsub`、`call`（`grep -rhoE '\bredis\.[a-z_]+\(' app` 的结果与 mock 白名单对比）。
     后果 1：`LoginService._check_login_rate_limit`（`auth/service.py:155–173`）用 `redis.incr` → 拿到 `MagicMock`，`count > settings.LOGIN_RATE_LIMIT_MAX_ATTEMPTS` 抛 `TypeError` → 被 `except Exception` 吞掉并仅 warning → **登录限流在测试环境静默失效**。
     后果 2：`RedisCURD.compare_and_set` / `unlock` 依赖 `redis.eval`（`redis_crud.py:170、223`）→ `result == 1` 恒 False → **会话续期的 CAS 路径在测试里永远走失败分支**。
6. **模块级 `patch(...).start()` 永不 stop**（L161–164）：`redis.asyncio.Redis.from_url`、`SchedulerUtil.init_scheduler/shutdown` 被进程级替换，跨测试文件持续生效，且失败时不留痕迹。
7. **`assert_route` 把异常当通过**（L268–277）：

   ```python
   try:
       response = test_client.request(method, path, **kwargs)
   except Exception:
       # 后端代码异常（500 等），路由存在即不计为测试失败
       return
   ...
   assert response.status_code != 404, ...
   ```

   → 5xx/未捕获异常被计为"路由存在"，**接口挂掉也能绿**；默认断言只查 `!= 404`。当前无调用者，但它是后续补测试时最容易误用的"绿色陷阱"。
8. **完全没有异步夹具**：`pyproject.toml` 配了 `asyncio_mode = "auto"` + `asyncio_default_fixture_loop_scope = "function"`，但 `tests/` 内 `async def test_` / `async def fixture` 数量为 **0**。新增异步 DB 用例时若直接复用应用全局 `async_engine`（session 级 TestClient 在独立线程/事件循环中运行），会踩"连接绑定到另一个事件循环"的坑——现有夹具没有为这件事提供任何支撑（缺 async session/事务夹具）。
9. **pytest 配置过薄**（`pyproject.toml:155–157`）：无 `markers`、无 `--strict-markers`、无 `filterwarnings = error`、无 `timeout`、无覆盖率插件与阈值、无 `-p no:randomly`（无随机序，掩盖顺序依赖）。

### 2.3 是否依赖真实 MySQL / Redis

- **不依赖**：`conftest` 强制 `DATABASE_TYPE=sqlite` + 临时库文件，Redis 用 AsyncMock 顶替（L28–32、L141–178）。
- **代价**：
  - 生产主用 MySQL/Postgres，但测试只在 SQLite 上跑 → 方言相关代码（`information_schema` / `pg_catalog` 查询、`ON UPDATE CURRENT_TIMESTAMP`、`UNSIGNED`、`COLLATE`、JSON 列、`server_default` 渲染）**零覆盖**；
  - `app/modules/generator/gencode/crud.py:178–243` 的 MySQL/Postgres 物理表分页 SQL 分支只在真实方言下成立，测试永不会执行；
  - 真实 Redis 的 Lua 脚本（`eval`）、`incr`、SCAN 语义无覆盖（见 §2.2.5）。

### 2.4 迁移测试的有效性

`tests/test_migrations.py` 两个守卫确实有意义（守卫一：布局阶段 `app/alembic/versions/` 不得新增文件；守卫二：显式 `autogenerate` 必须零产出），但存在三个边界：

1. **`app/alembic/versions/` 里只有 `__init__.py`，没有任何迁移文件**。也就是说项目声明的"双轨制"（新装走 `create_all` + `stamp head`，存量走 `alembic upgrade`）目前只剩单轨：`alembic upgrade head` 无版本可升。**迁移链本身的正确性（upgrade/downgrade、数据回填、`stamp` 基线）100% 无测试**，而 `app/scripts/initialize.py:61–123` 里对空 `alembic_version` 的处理（清空、提示、跳过 stamp）也只是被间接启动过一次。
2. **只覆盖 SQLite 方言**：注释里已承认"MySQL 方言的 DDL 渲染差异由 dev 启动时的自动迁移承担"——而 dev 启动只发生在开发者本机，CI/无本地启动场景下无人守。
3. **守卫二有写仓库副作用**：`command.revision(cfg, autogenerate=True)` 会把产物写进 `app/alembic/versions/` 再删除（L31–34）。这是本次唯一会写仓库的测试路径；若未来在只读检出或并行执行（`pytest -n`）中运行，会互相打架或留下残留文件。

### 2.5 前端 web 的 vitest：**真有可运行用例** ✅

- 配置：`frontend/web/vitest.config.ts`，`environment: jsdom`、`globals: true`、`include: ["src/**/*.{test,spec}.{ts,js}"]`，并同步了 `__APP_INFO__` 与 `@/` 等别名（配置质量不错）。
- 用例 1 `src/__tests__/smoke.spec.ts`（3 例）：断言 `MenuTypeEnum` 四个取值、代码生成枚举模块可导入。属于**冒烟级别**，价值低但零成本。
- 用例 2 `src/__tests__/route-invariants.spec.ts`（7 例）：把"有 children 的路由记录不得挂 component"（Vue Router 深度跳级 + 单层 KeepAlive 的前提）固化成断言，并校验后端 `backend/sql/sys_menu.json` 中目录节点不得配 `component_path`。**这是全仓库质量最高的一组测试**（带历史回归说明、有明确失败信息）。
- 缺口：
  - `package.json` 有 `"test": "vitest run"`、`SKILL.md` 也写了 `pnpm test`，但**没有任何环节会执行它**（CI 不跑、husky 的 `pre-commit` 只跑 `lint-staged`）；
  - **无覆盖率能力**：未安装 `@vitest/coverage-v8` 等 provider（`node_modules/@vitest/` 不存在），`vitest --coverage` 无法产出数据；
  - `@vue/test-utils`、`jsdom` 已安装，但 `src/` 中**没有任何组件挂载测试**（`grep -rn "@vue/test-utils" src/` 无命中）→ 组件/交互层零覆盖；
  - `route-invariants.spec.ts` 依赖仓库相对路径读取后端 `sql/sys_menu.json`（三个候选路径兜底）→ 前端用例与后端数据文件形成隐式耦合，脱离仓库根目录单独签出 web 会失败（首例带清晰报错，属可接受的取舍，但需要写进交接文档）。

### 2.6 uniapp（`frontend/app`）：测试能力为零

- `package.json` 无 `test` script，无 vitest/jest/@vue/test-utils（只有 `type-check`、`lint`）。
- 全目录 0 个 `*.spec.*` / `*.test.*` 文件。
- 自带的 `.github/workflows/ci.yml` 里的三步"测试"是：

  ```yaml
  - name: Test H5 dev mode
    shell: bash
    run: |
      timeout 30s pnpm dev:h5 || true
      echo "✅ H5 dev mode test completed"
  ```

  `|| true` + 仅打印 ✅ → **无论开发服务器是否启动成功都返回成功**，不构成任何验证（且 `windows-latest` + `shell: bash` 下 `timeout` 行为同样可疑）。

### 2.7 CI 覆盖：仓库级 **0**

- 仓库根 `.github/workflows/` **是空目录**，且 `git ls-files .github` 返回 0 → 未被跟踪。GitHub Actions **不会在本仓库运行任何 workflow**。
- `frontend/web/.github/workflows/ci.yml`：内容认真（`pnpm install --frozen-lockfile` → `type-check` → `lint` → `build:dev`），但 (a) 目录不在仓库根，不会被触发；(b) 即使被触发，也**只跑 type-check/lint/build，不跑 `vitest`**。
- `frontend/app/.github/workflows/ci.yml`：同上，且"测试"步骤是 `|| true` 空跑。
- 后端：**没有任何 workflow**，`pytest` 全靠人手敲。
- `deploy.sh` / `deploy-artifacts.sh` 只做打包与发布，不跑测试（仅在排除列表里提到 `.pytest_cache`）。
- 仓库的成文约定与实现不符：`SKILL.md:57/67/121` 要求"后端 `uv run pytest`；前端 `pnpm ts:check`、`pnpm lint`、`pnpm test`"，实际无任何自动执行点。

---

## 3. 覆盖缺口清单（含证据）

### 3.1 宏观证据

| 证据 | 数值 |
| --- | --- |
| 后端 Python 文件 / 行数（`backend/app`） | 216 个 / 28519 行 |
| OpenAPI 路径 / 操作 | 205 / 209（`app.openapi()` 实测；GET 79、POST 63、PUT 26、DELETE 30、PATCH 11） |
| `AuthPermission(...)` 调用 | 187 处（另有类定义等共 212 行出现该标识符） |
| 现有 pytest 用例 | 2 |
| 有断言的接口 | 1（`/monitor/health/check/`） |
| 历史用例数（`158c14a4^`，2026-07-17） | 238（`test_api_module_system.py` 92、`platform` 54、`task` 39、`monitor` 19、`generator` 12、`example` 9、`ai` 6、`common` 5、`test_main` 2） |
| 历史 node id（`.pytest_cache/v/cache/nodeids`） | 761 个 / 38 个文件（`test_codegen.py` 99、`test_api_module_system.py` 95、`test_api_module_platform.py` 90、`test_api_system.py` 72、`test_api_module_plugin.py` 58、`test_unit.py` 47、`test_permission_logic.py` 28、`test_integration.py` 20、`test_data_scope.py` 5 …） |
| `.pytest_cache/v/cache/lastfailed`（2026-09-06） | 120 个失败 id（含 `test_permission_logic.py` 21、`test_api_module_system.py` 21、`test_integration.py` 20） |
| 删除轨迹 | `158c14a4`(2026-07-17) 删 7 个模块化 API 测试文件；`d470c7eb`(2026-09-06) 删 `test_api_module_system.py`；`tests/__pycache__` 还残留 `test_sse_once/test_api_system/test_routes/test_architecture` 的 `.pyc` |

> 结论：**测试不是"从未有"，而是被两次重构清空且没有替代物**；`.pytest_cache` 显示本地曾存在 `test_codegen.py`(99)、`test_permission_logic.py`(28)、`test_data_scope.py`(5) 等成套用例，且当时已有 120 条失败——这些用例本身也需要重建而非"恢复"。

### 3.2 按模块的缺口（附只读探针实测）

探针脚本：`/tmp/probe_tests.py`（临时目录，不落仓库；`SECRET_KEY`/SQLite 环境变量隔离，不连真实 MySQL/Redis）。实测输出节选：

```text
resolve_condition('like','a')            : OK -> ['probe_tbl.id LIKE :id_1']
resolve_condition('in', [])              : OK -> ['false']                      # 空集合 → 恒假，合理
resolve_condition('between',[1])         : OK -> []                             # 长度≠2 → 静默丢弃条件
resolve_condition('date','2026-10-04')   : OK -> ['probe_tbl.id >= :id_1', 'probe_tbl.id < :id_1']
resolve_condition('month','2026-12')     : OK -> ['probe_tbl.id >= :id_1', 'probe_tbl.id < :id_1']
resolve_condition('date','not-a-date')   : ValueError: time data 'not-a-date' does not match format '%Y-%m-%d'
resolve_condition('unknown_op','x')      : OK -> []                             # 未知算子 → 无 WHERE，结果被静默放大
build_conditions unknown key             : AttributeError: type object 'ProbeModel' has no attribute 'no_such_col'
JWT tampered 'a.b.c'                     : CustomException: 无效认证,请重新登录
JWT empty                                : CustomException: 认证不存在,请重新登录
PwdUtil.hash/verify                      : OK -> True / verify wrong -> False
camel/snake 转换、bytes2human            : OK -> 'UserName' / 'user_name' / '1.0GB'
get_child_recursion(1, {1:[2],2:[1]})    : RecursionError: maximum recursion depth exceeded   # 无环检测
```

| 模块 | 关键代码 | 缺口与风险（有据） |
| --- | --- | --- |
| 认证 entry | `app/core/dependencies.py:43–189`（`get_current_user` / `_authenticate`） | **11 条 401 抛出点（`grep -c "status_code=401"` = 11）全部无测试**：空 token、`Bearer` 后为空、`is_refresh` 令牌、缺 `session_id`、session 不存在、session 数据不完整、超最大存活时长、缺 `user_name`、`user_status==1` 停用、缺 `user_id`、每请求查库确认用户存在且未删除；滑动续期（TTL==-1 兜底、`SESSION_MAX_LIFETIME_SECONDS` 绝对上限、双键同时续期）同样无测试 |
| RBAC 接口权限 | `app/core/dependencies.py:192–234`（`AuthPermission`） | 超管旁路（L216）、`permissions` 为空即放行（L219–220）、`*` / `*:*:*` 通配放行（L222）三条"放行"逻辑与"无权限 403"分支均无测试。187 处调用 ↔ 0 个用例；任何一处语义翻转都会静默放开或锁死全部接口 |
| 数据权限 | `app/core/permission.py` 全文；`app/utils/common_util.py:162–196` | 3 种 `data_scope`（SELF/DEPT_AND_CHILD/ALL）、`created_by.dept_id` 关系判定、`UserModel` 特例、`hasattr(model,"created_id")` 缺失模型、部门树异常时"降级为本部门"（L109–117）全部无测试；`get_child_recursion` 对 `parent_id` 成环会 `RecursionError`（探针实测），当前被 `except Exception` 兜成降级+warning → **权限范围静默收窄且只留一条 warning** |
| 登录/防爆破 | `auth/service.py:122–270`（`LoginService`）、`:540–649`（`CaptchaService`） | 用户不存在 / 密码错 / 停用 三类失败与登录日志写入、限流窗口、验证码开关、`ENVIRONMENT != PROD` 时的 docs Referer 豁免均无测试。两处已可见问题：① 限流对 `127.0.0.1/unknown/localhost` 直接 return（L161–162）→ 反代/本机部署形同不限流；② "用户不存在"与"账号或密码错误"文案不同（L217/L231）→ 用户名枚举 oracle |
| 会话与令牌 | `auth/service.py:349–539`（`create_token`/`refresh_token`/`logout`）、`core/redis_crud.py:147–245` | refresh 轮换、`compare_and_set` CAS 语义、`lock/unlock` Lua 原子性、`logout` 需同时清 `access_token:{sid}` / `refresh_token:{sid}` / `user_session:{sid}` 三键（`service.py:531–533`），全部无测试；且现有 Redis mock 缺失 `eval` → CAS 路径在测试中恒失败（§2.2.5） |
| 分页/查询封装 | `core/base_crud.py:104–182`（`count/get_list/page`）、`:303–387`（`_build_conditions/_resolve_condition/_parse_order`）、`utils/common_util.py:87–126`（`search_to_dict`） | `page()` 的 `total/has_next/page_no(=offset//limit+1)/limit=0`、软删 `is_deleted` 自动过滤与 `include_deleted`、`load_columns`/`preload` 与 COUNT 拆分的等价性，全部无测试；异常一律被包装成 `CustomException("分页查询失败: ...")`（L181–182）→ 非法 `date`（ValueError）、未知排序字段（AttributeError）、未知 search key（AttributeError）都退化成同一条"分页失败"，**无法区分 4xx 与 500**；未知算子静默返回空条件列表 → 查询范围被放大却无报错。`search_to_dict` 的 `_start/_end` 合并、`_time` 列表、`json_schema_extra={"q": ...}` 打包是所有列表接口过滤语义的唯一入口，无测试 |
| 代码生成器 | `gencode/service.py:375–449`（`create_table`）、`gencode/crud.py:148–350`（系统表分页 / `execute_sql`）、`gencode/gen_util.py`（309 行纯函数）、`jinja2_template_util.py`（759 行模板） | ① DDL 白名单：`has_create = any(isinstance(s, Create))` + 禁用 `(Delete, Drop, Insert, TruncateTable, Update)`；sqlglot 的 `Create` 同时涵盖 `CREATE VIEW/INDEX/DATABASE`，**会被放行并执行**；`Alter` 用字符串包含判定（`"SET " not in upper` 等）脆弱（合法的 `ON DELETE SET NULL` 反被拒）。② 物理表列表查询按方言走 `information_schema`/`pg_catalog`（L178–243），SQLite 测试永不触达。③ `GenUtils.get_db_type/get_column_length/split_column_type/arrays_contains/replace_first/convert_class_name` 等纯函数边界（`tinyint(1)`→boolean、`int UNSIGNED`、`COLLATE`、`integer[]`、`timestamp without time zone`、`decimal(10,2)`、空括号）无测试。④ 模板渲染产物语法正确性无测试 |
| 操作日志与脱敏 | `core/router_class.py:33–40`（`_redact_sensitive`）、`:59–134`（`OperationLogRoute`） | 敏感键递归脱敏（含请求体表单、响应体 → token 不得明文入库）、>2000 字符截断为"请求参数过长"、非 JSON 体兜底、后台写库失败仅告警，均无测试。这是"日志泄露 token/密码"的直接防线 |
| 中间件/异常 | `core/middlewares.py`、`core/exceptions.py`、`common/response.py` | 限流、XSS、请求 ID、`CustomException → ResponseSchema` 映射（`success/code/msg/status_code` 契约）、`ErrorResponse` 语义无测试 |
| SSE / WebSocket | `core/sse_manager.py`、`dependencies.py:52–87`（`get_websocket_token` 子协议解析、`websocket_authenticate`） | 无测试（`tests/__pycache__/test_sse_once.*.pyc` 说明曾经有过）；WS 鉴权、子协议回显、`?token=` 兜底都属于易回归点 |
| AI 会话 / 存储 / 任务 | `modules/ai/chat`（agno）、`modules/task/storage/*`（S3/OBS/OSS/COS/SFTP）、`modules/task/cronjob`、`core/ap_scheduler.py`（609 行） | 0 测试；外部 SDK（`boto3`/`esdk-obs-python`/`alibabacloud-oss-v2`/`cos-python-sdk-v5`/`paramiko`）全部无 mock 边界测试 |
| OAuth | `auth/oauth_service.py`（479 行，github/gitee/wechat/qq 换 token 与取 profile） | 0 测试（需 HTTP mock）；state 校验与前端跳转兜底无测试 |
| 迁移/schema | `tests/test_migrations.py`、`app/scripts/initialize.py:50–123` | 见 §2.4：无迁移文件、仅 SQLite、无 upgrade/downgrade 链路测试 |
| 前端 web | `frontend/web/src/**` | 覆盖仅限枚举与路由结构；`store`（pinia）、`utils`（request/axios 拦截器、storage、crypto）、`router` 动态路由加载（`route-loader.ts`）、权限指令、组件均无测试；无组件挂载测试 |
| uniapp | `frontend/app/src/**` | 0 测试、0 测试基建 |

### 3.3 断言有效性问题（最容易被忽略的一条）

唯一的行为测试 `tests/test_main.py`：

```python
response = test_client.get("/monitor/health/check/")
assert response.status_code == 200
assert body["success"] is True
assert body["code"] == 0
```

而 `app/modules/monitor/health/controller.py`：

```python
info = await HealthService.collect(redis)
ok = info.db_status == 1 and info.redis_status == 1
return SuccessResponse(data=info, msg=f"系统健康-{settings.VERSION}" if ok else f"服务异常-{settings.VERSION}")
```

`SuccessResponse` 的 `success`/`code` 恒为 `True`/`0`（`app/common/response.py:29–42`）。也就是说该用例**即使 DB 与 Redis 全部探活失败也会通过**——它只验证了路由存在 + JSON 形状，没有验证 `data.db_status/redis_status`，也没验证 `msg`。全仓唯一的行为断言是**不可失败断言**。

---

## 4. 最该先补的 10 个测试点（含验证方式）

排序原则：安全相关（越权/凭据）> 影响全部接口的公共封装 > 不可逆操作（DDL/迁移）> 业务模块。

---

### T1. 接口权限矩阵（`AuthPermission`）与认证失败矩阵 ✅最高优先

- **为什么**：187 处 `AuthPermission(...)` 调用、0 个用例；三条放行分支（超管 / 空权限 / 通配符）中任何一条回归都等于全站越权。
- **验证方式**
  - 新增 `backend/tests/test_auth_permission.py`（纯单元，无 DB）：
    ```python
    @pytest.mark.parametrize(("is_superuser", "user_perms", "required", "expect"), [
        (True,  [],                 ["system:user:create"], "allow"),   # 超管旁路
        (False, [],                 ["system:user:create"], "allow"),   # self.permissions 为空 → 放行
        (False, ["*"],              ["system:user:create"], "allow"),
        (False, ["*:*:*"],          ["system:user:create"], "allow"),
        (False, ["a:b:c"],          ["system:user:create"], "403-errcode"),  # 无权限分支
        (False, [],                 ["x:y:z", "a:b:c"],     "allow"),
    ])
    async def test_matrix(...):
        with_403 = pytest.raises(CustomException)
    ```
  - 组装 `AuthSchema(user=CoreUserSchema(id=1, is_superuser=..., ...), permissions=user_perms)` 直接 `await AuthPermission(required)(auth=...)`；对 403 分支断言 `code == RET.NO_PERMISSION.code`（而非只有 HTTP 状态码）。
  - 接口层（用现有 `test_client` 夹具）对任一受保护接口断言四类 401：无 `Authorization`、`Bearer` 空、随机串、签名正确但 session 已删（先 `logout` 再请求）。
- **验收**：T1 里"无权限 → 403"与"超管 → 200"两类用例必须同时存在，防止只测放行不测拦截。

### T2. 数据权限 `Permission` 的数据范围矩阵

- **为什么**：这是"用户 A 看到用户 B 数据"的唯一闸门，当前零覆盖；`created_id`/`dept_id`/`created_by.dept_id` 三条取值路径 + 降级逻辑都很绕。
- **验证方式**
  - 新增 `backend/tests/test_data_scope.py`，用内存 SQLite（`create_async_engine("sqlite+aiosqlite:///:memory:")`，独立于 conftest 的全局库）建 3 部门（1 → 2 → 3）+ 3 用户 + 若干带 `created_id` 的示例行。
  - 对 `Permission(model, auth, db)._permission_condition()` 断言生成的条件类别，而不是断言数据量：
    ```python
    cond = await Permission(UserModel, auth, db)._permission_condition()
    assert cond is None                                  # is_superuser 或 DATA_SCOPE_ALL
    sql = str(cond.compile(compile_kwargs={"literal_binds": True}))
    assert "dept_id IN (1, 2, 3)" in sql or "created_id = 2" in sql
    ```
  - 必测分支：`data_scope=ALL → None`、`DEPT_AND_CHILD → dept 子树包含自身`、`SELF → created_id = 当前用户`、模型无 `created_id` → `None`、`_load_dept_children` 抛异常 → 降级为"仅本部门"且捕获到 `logger.warning`（用 `caplog`）。
  - 顺带固化 §3.2 的环检测缺陷：构造 `parent_id` 自引用（`{1: [2], 2: [1]}`），断言**期望行为**是"不抛 `RecursionError`、返回有限集合"——当前会失败，正好作为修复工单的验收依据。
- **验收**：每条 `data_scope` 至少 1 个正例 + 1 个反例；环用例先标 `xfail(strict=True)` 并附 issue 说明，修复后转正。

### T3. 会话令牌全生命周期（create / refresh / logout / 滑动续期）

- **为什么**：令牌是唯一凭据；`compare_and_set`（CAS）+ 双键续期 + 绝对存活上限都是"并发下悄悄失效"的高危逻辑，且现有 Redis mock 缺失 `eval` 使它**不可能被测到**。
- **验证方式**
  - 先改夹具（这是本轮报告给出的必要前置）：把 `conftest` 的手写 `AsyncMock` 换成 `fakeredis.asyncio.FakeRedis`（依赖已在 dev 组声明），或至少补齐 `incr/eval/mget/scan_iter/publish/pubsub/call` 的语义实现。
  - 新增 `backend/tests/test_session_lifecycle.py`：
    - `create_token` 后断言 Redis 中同时存在 `access_token:{sid}` / `refresh_token:{sid}` / `user_session:{sid}` 三键且 TTL ≈ 配置值；
    - `refresh_token` 后断言旧 session 失效（返回 401）、`is_refresh` 令牌不能直接访问业务接口；
    - `logout` 后断言三个键都被删除、原 token 请求返回 401（`service.py:531–533` 少删一个键即为漏登出）；
    - CAS：写入 key→A 后并发/串行地先改成 B，再调 `compare_and_set(key, expected="A", ...)`，断言返回 `False` 且值仍为 B；
    - 滑动续期：`TOKEN_SLIDING_EXPIRE=True` 时把 session 值里的 `created_at` 设到 `SESSION_MAX_LIFETIME_SECONDS` 之前，断言请求被拒且键被删除（覆盖 `dependencies.py:125–156` 的三条分支）。
- **验收**：CAS 的成功与失败两条路径都必须有断言（现在测试环境恒为失败）。

### T4. 登录认证与防爆破（`LoginService.authenticate_user`）

- **为什么**：最直接的攻击面；且现有夹具**必然测不到限流**（`incr` 缺失 + 127.0.0.1 跳过）。
- **验证方式**
  - 新增 `backend/tests/test_login.py`（沿用 `test_client`）：
    - 三类失败：不存在用户、错误密码、`status=1` 停用 → 断言 HTTP 200 + 业务错误码 + `msg` 文案；同时断言 `LoginLogModel` 落库（`status=2` 与对应 `msg`）——这同时覆盖了 `_write_login_log`。
    - 成功登录：断言返回 `access_token`、Redis 有 session、`last_login` 被更新。
    - 限流：用 fakeredis + `X-Forwarded-For`（或 monkeypatch `get_client_ip` 返回 `10.0.0.9`）连续请求 `LOGIN_RATE_LIMIT_MAX_ATTEMPTS + 1` 次，断言第 N+1 次被拒；**并单独写一条用例固化"`127.0.0.1/unknown` 跳过限流"的既有行为**，让这个安全取舍显式可见。
    - 验证码：`CAPTCHA_ENABLE=True` 时缺 `captcha_key` → 明确报错；`ENVIRONMENT=PROD` 时 `Referer: .../docs` 不再豁免。
- **验收**：限流用例必须在"非本机 IP"下运行，否则等于没测。

### T5. `CRUDBase.page()` 的分页/软删语义

- **为什么**：所有列表接口都走它；`total/has_next/page_no` 算错会导致前端分页器错乱，软删过滤算错会导致数据泄漏。
- **验证方式**
  - 新增 `backend/tests/test_crud_page.py`：独立内存 SQLite + 一个测试模型（同时含 `is_deleted`、`created_id`），插入 25 行（其中 3 行 `is_deleted=True`）。
  - 断言矩阵：
    | 入参 | 期望 |
    | --- | --- |
    | `offset=0, limit=10` | `total=22, page_no=1, page_size=10, has_next=True, len(items)=10` |
    | `offset=20, limit=10` | `page_no=3, has_next=False, len(items)=2` |
    | `offset=25, limit=10` | `items=[]`, `has_next=False` |
    | `limit=0` | 不抛 `ZeroDivisionError`，`page_size` 回落到 10 |
    | `include_deleted=True` | `total=25` |
    | `page()` 与 `get_list()` 同参 | 行集合一致（COUNT/数据两趟查询的条件等价） |
    | `order_by=[{"id":"desc"}]` / 多字段 | 顺序与预期一致 |
  - 断言 `page()` 抛出的异常类型是 `CustomException` 且 `msg` 可区分（不要只断言"抛异常"）。
- **验收**：`limit=0` 与多字段排序必须入用例（前者是边界除零，后者是 `_parse_order` 的循环语义）。

### T6. 查询算子与查询参数封装（含非法输入的错误语义）

- **为什么**：决定了所有列表接口的过滤语义与错误码；探针已证实**未知算子静默丢弃条件**、非法日期抛裸 `ValueError` 后被包装成统一的"分页查询失败"。
- **验证方式**
  - 新增 `backend/tests/test_query_operators.py`，参数化 `CRUDBase._resolve_condition`（纯静态方法，零依赖）：
    | 输入 | 期望 |
    | --- | --- |
    | `("None", None)` / `("not None", None)` | `IS NULL` / `IS NOT NULL`，不依赖 val |
    | `("like", "a")` | `LIKE '%a%'` |
    | `("in", [])` | `false()`（恒假，不得退化为"无条件"） |
    | `("between", [1])` | 长度非法 → 明确行为（当前 `[]`，建议改为拒绝） |
    | `("date", "2026-10-04")` | `>= 00:00` 且 `< 次日 00:00` |
    | `("month", "2026-12")` | 跨年到次年 1 月 1 日 |
    | `("date", "not-a-date")` | **期望** `CustomException`（清晰 4xx），当前 `ValueError` |
    | `("unknown_op", "x")` | **期望** 抛错或忽略但记录告警，当前静默返回 `[]` |
    | `_OPERATOR_MAP` 8 个比较符 | `attr.__eq__/__ne__/__gt__/...` 映射正确 |
  - 同一文件覆盖 `search_to_dict`：`xxx_start`/`xxx_end` 合并为 `("between", [s, e])`、`xxx_time` 列表合并、`json_schema_extra={"q": "like"}` 打包、`None` 值被排除。
- **验收**：非法日期这条用例的断言应指向"统一 `CustomException`"，把"500 类错误伪装成业务错误"的问题钉住。

### T7. 代码生成器 `create_table` 的 DDL 白名单（安全）

- **为什么**：这是"用户提交 SQL → 服务端执行 DDL"的路径，白名单一旦漏判就是任意建表/建视图/建索引；当前 0 测试。
- **验证方式**
  - 新增 `backend/tests/test_codegen_create_table.py`：不连库，`monkeypatch` 掉 `GenTableCRUD.execute_sql`（记录被执行的语句）、`check_table_exists`（恒 False）、`get_gen_table_by_name`（恒 None），直接 `await GenCodeService(auth, db).create_table(sql)`。
    | SQL 输入 | 期望 |
    | --- | --- |
    | `CREATE TABLE t1 (id INT PRIMARY KEY)` | 通过，且执行语句集合 == {该 DDL} |
    | `DROP TABLE t1` / `INSERT` / `UPDATE` / `DELETE` / `TRUNCATE` | 拒绝，`msg` 命中"禁止的关键操作" |
    | `CREATE TABLE t1 (...); DROP TABLE t1;` | 整体拒绝（破坏性语句检测在 has_create 之后仍生效） |
    | `CREATE TABLE t1 (...); ALTER TABLE t1 ADD CONSTRAINT fk FOREIGN KEY (a) REFERENCES b(id);` | 通过 |
    | `ALTER TABLE t1 DROP COLUMN c;` | 拒绝 |
    | `ALTER TABLE t1 ADD CONSTRAINT fk FOREIGN KEY (a) REFERENCES b(id) ON DELETE SET NULL;` | **当前会误拒**（含 `SET `）→ 用例固化预期行为，暴露字符串判定缺陷 |
    | `CREATE VIEW v AS SELECT 1` / `CREATE INDEX i ON t1(id)` | **当前会被放行** → 用例断言必须先确定安全预期（建议归为拒绝），作为加固依据 |
    | 表已存在 / 已在代码生成模块存在 | 拒绝，`msg` 区分两种原因 |
  - 断言"未执行的语句不被执行"（例如含 DROP 的多语句输入下，`execute_sql` 调用次数为 0）。
- **验收**：`CREATE VIEW`/`CREATE INDEX` 与 `ON DELETE SET NULL` 三条必须显式入用例，否则等于没有白名单。

### T8. 代码生成元数据纯函数 + 模板渲染

- **为什么**：`gen_util.py`（309 行）+ `jinja2_template_util.py`（759 行）是"生成代码给用户跑"的核心，边界输入容易产出语法错误的 Python；纯函数测试成本极低（毫秒级、零依赖）。
- **验证方式**
  - 新增 `backend/tests/test_gen_util.py`，参数化：
    - `get_db_type`：`tinyint(1)`→`boolean`、`tinyint`→`tinyint`、`int UNSIGNED`→`int`、`varchar(64) COLLATE utf8mb4_bin`→`varchar`、`integer[]`/`ARRAY[INTEGER]`→`array`、`timestamp without time zone`→`timestamp`、`""`→`""`；
    - `get_column_length`：`varchar(255)`→255、`decimal(10,2)`→10、`numeric(20, 0)`→20、无括号→0、`varchar()`→0、`text`→0；
    - `split_column_type`：`decimal(10,2)`→`["10","2"]`、无括号→`[]`；
    - `arrays_contains`：大小写不敏感、`COLLATE`/`UNSIGNED` 修饰剥离、`TINYINT(1)` 与 `tinyint` 的基类型比较；
    - `replace_first` / `convert_class_name`（`sys_user`→`SysUser`）；
    - `StringUtil`（`app/utils/string_util.py`）的同族转换。
  - 模板：对 `jinja2_template_util` 用最小 `GenTableSchema` 渲染一轮，断言 `compile(rendered, "<gen>", "exec")` 不抛 `SyntaxError`（比逐字快照更稳，能挡住"生成的代码是坏的"这类真实事故）；再对 1–2 个关键模板做字符级快照防意外改动。
- **验收**：模板用例的断言必须是"能编译"而非"包含某段字符串"。

### T9. 操作日志脱敏与响应契约

- **为什么**：这是阻止"密码/token 明文入库"的唯一防线；`_redact_sensitive` 是纯函数，测试成本极低。
- **验证方式**
  - 新增 `backend/tests/test_operation_log.py`：
    - 纯单元（无 DB）：`_redact_sensitive({"Password": "x", "nested": {"access_token": "y"}, "list": [{"client_secret": "z"}]})` → 三个值均为 `"******"`，非敏感键原样保留；大小写混写（`Authorization`、`SECRET_KEY`）命中断言。
    - 路由层：`test_client` 打 `/system/auth/login`（含密码表单）与一个返回 token 的接口，断言 `OperationLogModel.request_payload` 不含明文密码、`response_json` 不含 `access_token` 明文；
    - 长度：构造 > 2000 字符的请求体，断言 `request_payload == "请求参数过长"`；
    - 非 JSON：`Content-Type: text/plain` 请求，断言记录走 `errors="ignore"` 兜底且不抛异常；
    - 写库失败：`monkeypatch` 使 `async_db_session` 抛异常，断言响应仍为 200（日志失败不得影响主流程）。
- **验收**：`Authorization`/`access_token` 两个键必须各有一条"明文不得出现"的负向断言。

### T10. 迁移与 schema 一致性守卫升级

- **为什么**：迁移漂移是"本地好、线上崩"的典型来源；现有守卫只覆盖 SQLite，且 `versions/` 为空使 upgrade 路径完全没被验证。
- **验证方式**（扩展现有 `backend/tests/test_migrations.py`，不新建平行文件）
  - 守卫 1/2 保留，新增守卫 3：断言 `ALEMBIC_VERSION_DIR` 的实际状态与启动路径一致——当目录为空时，断言 `init_db` 走的确实是"create_all（不 stamp）"分支（可断言 `alembic_version` 表不存在或为空 + 捕获对应日志），避免未来悄悄变成"空库被 stamp head"。
  - 守卫 4（关键）：把一致性检查从 SQLite 扩到 MySQL/Postgres。**注意：`MigrationContext.configure(dialect_name="mysql")` + `compare_metadata` 无法离线使用**（本次实测三种方言均直接 `AssertionError`，因为 `compare_metadata` 需要真实 `Connection` 做反射），所以分两条腿：
    1. **离线多方言 DDL 渲染**（无需数据库，可进常规 CI）：先 `from app import create_app; create_app()` 把全部模型 import 进来（否则 `UserModel.__table__` 会因 `sys_user_roles → sys_role` 外键找不到表而抛 `NoReferencedTableError`），然后逐方言编译：
       ```python
       from sqlalchemy.dialects import mysql, postgresql
       from sqlalchemy.schema import CreateTable
       from app.core.base_model import MappedBase          # 实测 29 张表

       for name, dialect in (("mysql", mysql.dialect()), ("postgresql", postgresql.dialect())):
           for table_name, table in MappedBase.metadata.tables.items():
               ddl = str(CreateTable(table).compile(dialect=dialect))   # 实测：sys_user → 1586/1199 字符
               assert ddl.strip(), f"{name}.{table_name} 渲染为空"
               # 断言口径二选一：① 关键表 DDL 字符级快照；② 规则断言（如禁止 "VARCHAR" 无长度、
               # 禁止 MySQL 专有修饰出现在 Postgres 渲染结果里），避免快照噪音过大。
       ```
       用途：挡住"某字段在 MySQL 下渲染出非法/退化 DDL（如 `UNSIGNED`、`ON UPDATE`、`COLLATE`、无长度 `VARCHAR`）"这类只在方言上暴露的问题。
    2. **真连接等价检查**（`@pytest.mark.integration`，按需开启，仓库已有 `docker/mysql` compose）：连上真实 MySQL/Postgres 后
       ```python
       with engine.connect() as conn:
           diffs = compare_metadata(MigrationContext.configure(conn), MappedBase.metadata)
           assert diffs == [], diffs          # 实测 SQLite 真连接下为 0 diff
       ```
  - 守卫 5：让迁移用例在**只读检出**下也能跑——把 `command.revision(autogenerate=True)` 的写法改为在临时目录（`tmp_path` + 覆盖 `script_location`）中执行，消除测试写仓库的副作用（当前 `test_migrations.py:31–34` 会向 `app/alembic/versions/` 写文件再删）。
  - 若后续补回迁移文件：新增一条"`alembic upgrade head` 从空库升到 head 后，`compare_metadata` 零 diff"的端到端用例（这是当前最大盲区）。
- **验收**：多方言断言必须真编译一次 DDL（不得只 mock `CreateTable`），且**不要**使用 `MigrationContext.configure(dialect_name=...)` 冒充等价检查；真连接等价检查须放在有 DB 的 job / 本地显式开启；迁移用例执行后 `git status` 必须保持干净。

---

## 5. 落地顺序建议（3 个批次）

| 批次 | 内容 | 目的 | 门禁 |
| --- | --- | --- | --- |
| **第 1 批（≤2 天）** | T1、T6、T8、T9（纯函数/纯单元为主，不需要新夹具）+ 重建 `pytest-cov` 与覆盖率基线 | 用最低成本拿到"安全 + 公共封装"的回归网 | 后端 `uv run pytest` 纳入 CI，覆盖率设"不回退"而非固定阈值 |
| **第 2 批（3–5 天）** | 夹具改造（fakeredis 替换手写 mock、`assert_route` 改为对 5xx 失败、增加 async session/事务夹具、逐用例隔离）+ T3、T4、T5、T2 | 让"测试能失败"，覆盖凭据与数据权限 | 新增 async 夹具后开启 `filterwarnings = error`；`pytest -q --strict-markers` |
| **第 3 批（1–2 周）** | T7、T10 + 启动路径（真实 lifespan）冒烟 + 前端 vitest 扩展（request 拦截器、storage、route-loader）+ uniapp 最小 vitest 接入 | 覆盖不可逆操作与真实启动链 | 仓库根新建 `.github/workflows/ci.yml`：backend（ruff + pytest）+ web（type-check + lint + **vitest run**）+ app（type-check + lint） |

配套的"制度性"修复（与测试点同等重要，均属零成本配置）：

1. **在仓库根建 CI**（当前为空目录，`git ls-files .github` = 0）：把 `frontend/web/.github/workflows/ci.yml` 的内容上提并补 `pnpm test`；后端加 `uv sync --group dev && uv run pytest -q`。
2. **保留 `frontend/web` 的 vitest 并扩面**：它已有 10 个真用例，只要进 CI 就能立刻防住路由结构回归。
3. **修正 `assert_route`**（`backend/tests/conftest.py:240–277`）：`except Exception` 应转为失败（或改为显式允许 5xx 白名单），默认断言从"`!= 404`"升级为"status < 500"。
4. **把 `fakeredis` 用起来或从 dev 组删掉**：声明了却不用，是明确的误导信号。
5. **`SKILL.md` 与实现对齐**：文档要求 `pnpm test` / `uv run pytest`，实际无执行点；要么加门禁，要么改文档。

---

## 6. 附：本次审计用到的只读命令

```bash
# 1) 后端测试（uv 缓存需重定向；详见 §1.1）
cd backend && uv run pytest -q                      # 原样执行：uv 缓存权限失败，exit 2
cd backend && UV_CACHE_DIR=/tmp/uv-cache-test uv run pytest -q      # exit 0, 2 passed
cd backend && UV_CACHE_DIR=/tmp/uv-cache-test uv run pytest -v      # 收集清单
cd backend && .venv/bin/python -m pytest -q         # 等价路径（不再触碰 uv.lock）

# 2) 前端测试
cd frontend/web && ./node_modules/.bin/vitest run   # exit 0, 2 files / 10 tests

# 3) 规模与路由统计（只读探针，见 /tmp/probe_tests.py）
cd backend && .venv/bin/python -c "from app import create_app; print(len(create_app().openapi()['paths']))"   # 205
find backend/app -name '*.py' | wc -l ; find backend/app -name '*.py' -exec cat {} + | wc -l                  # 216 / 28519

# 4) 测试资产溯源
git ls-files .github                                  # 0（根 CI 为空）
git log --diff-filter=D --name-only -- backend/tests  # 删除轨迹
python3 -c "import json;print(len(json.load(open('backend/.pytest_cache/v/cache/nodeids'))))"                 # 761
```

## 7. 环境与合规说明（重要）

1. **工作区在本次审计开始前即为脏**（其他 teammate 的并行产物）：`git status --porcelain` 显示已修改 `backend/app/config/setting.py`、`backend/pyproject.toml`、`backend/requirements.txt`、`backend/uv.lock`、`docker/.env.example`，未跟踪 `backend/requirements/`、`backend/audit-requirements.md`、`docker/audit-deploy.md`、`deploy-artifacts.sh`、`.agent-teams/`。其中 `pyproject.toml` 的 mtime 为 03:29（早于本会话），改动内容是把 mysql/pg 驱动从核心依赖迁到 `optional-dependencies`。
2. **`backend/uv.lock` 的 mtime 被本次 `uv run pytest -q`（未加 `--no-sync`）刷新为 03:58**。该文件的 diff 内容与上述 03:29 的 `pyproject.toml` 改动严格对应（`aiomysql`/`asyncpg`/`pymysql`/`psycopg` 从核心组迁入 `optional-dependencies`，并新增 `all-db` 组），未发现与之无关的内容变化；后续所有命令已改为 `backend/.venv/bin/python` 或 `--no-sync`，不再触碰锁文件。**此为本轮唯一可能非预期的写操作，特此披露。**
3. 除本报告文件 `backend/audit-testing.md` 外，**未新建、修改或删除仓库内任何文件**；未安装依赖、未启服务、未执行 git 提交。
4. `backend/app/alembic/versions/`、`backend/tests/` 在审计前后内容一致（分别只有 `__init__.py` / 3 个 `.py`）。
5. 本报告中的"探针实测"结果来自 `/tmp/probe_tests.py`（临时目录），仅使用内存/SQLite 与纯函数路径，未连接真实 MySQL、PostgreSQL 或 Redis。
6. 未取得**行覆盖率数字**：`pytest-cov` 与 `@vitest/coverage-*` 均未安装，且本轮不安装依赖。所有"缺口"结论基于：OpenAPI 路由清单、模块清单、`AuthPermission` 引用计数、代码路径静态审读与上述探针行为实测。
