# FastapiAdmin 前端摸底审计报告（frontend/web + frontend/app）

- 审计对象：`frontend/web`（Vue3 + Vite + TS + Element-Plus）、`frontend/app`（uni-app 移动端，Vue3 + wot-ui + alova）
- 审计方式：**只读**静态审计 + 可用的静态检查实跑；后端仅作契约比对（只读）
- 审计时间：本轮
- 本轮未改任何仓库文件（唯一新增文件即本报告）

---

## 0. 结论摘要

两端类型检查与已有单测**全部通过**，但"绿灯"并不代表健康：Web 端的生产构建开关实际上**从未生效**，移动端的 **token 静默续期接口契约与后端不符**、**头像上传路径不存在**，且移动端与 Web 端存在 **49 个同名重复类型定义**，已经开始漂移（见 §3）。

| 优先级 | 问题 | 位置 | 级别 |
|---|---|---|---|
| 1 | `isProduction = mode === "prod"` 恒为 false → 生产构建不做压缩/移除 console/剔除 devtools | `web/vite.config.ts:28` | **P0 高** |
| 2 | 移动端刷新令牌请求体与后端契约不符（后端要 JSON 字符串，移动端发对象） | `app/src/api/module_system/auth.ts:34` | **P0 高** |
| 3 | 移动端头像上传路径 `/file/upload` 不存在（应为 `/common/file/upload`） | `app/src/subPages/module_system/profile/index.vue:26` | **P0 高** |
| 4 | 富文本编辑器默认上传地址为 `//file/upload`（协议相对 URL + 路径缺 `/common`） | `web/src/components/forms/fa-wang-editor/index.vue:83` | **P0 高** |
| 5 | 移动端生产环境 WebSocket 指向 `ws://localhost:5180/ws` → AI 对话生产不可用 | `app/.env.production:23` | **P0 高** |
| 6 | 所有页面 `import.meta.glob(..., {eager:true})` → 首屏加载全量页面 | `web/src/router/route-loader.ts:24` | P1 高 |
| 7 | 移动端开发环境直连生产后端 | `app/.env.development:6` | P1 高 |
| 8 | 登录页硬编码 3 个演示账号（密码均 `123456`）并支持一键填充 | `web/src/views/module_system/auth/login/index.vue:333` | P1 高 |
| 9 | 动态路由"去重"守卫是死代码；匿名路由无法被清理 | `web/src/router/route-loader.ts:326,336` | P1 高 |
| 10 | `web/src/types/auto-imports.d.ts` 被 gitignore 且是 type-check 的前提 → 全新 clone 无法通过 type-check（实测 1358 error） | `web/.gitignore:12` | P1 高 |
| 11 | 守卫里的"路由修复"函数只打日志，不修复 | `web/src/router/guards.ts:207` | P2 中 |
| 12 | 生产仪表盘直接展示 mock 数据（真实接口调用被注释掉） | `web/src/views/dashboard/home/index.vue:165` | P2 中 |
| 13 | iframe 路由无 `sandbox`，可加载任意外部 URL | `web/src/router/routes.ts:170` | P2 中 |
| 14 | TS `any` 187 处 / 65 文件，且 ESLint 显式关闭 `no-explicit-any` | `web/eslint.config.mjs:68` | P2 中 |
| 15 | 移动端路由守卫只判断登录，无任何权限/角色门禁（后台已鉴权，纯 UX/暴露面问题） | `app/src/router/index.ts:30` | P2 中 |
| 16 | 两端口径不一致：屏幕锁"加密密钥"随 `.env` 提交仓库 | `web/.env:25` | P2 中 |
| 17 | 移动端 no type-check in build / 无任何测试 | `app/package.json:31` | P2 中 |
| 18 | 应用商店合规：安卓权限申请过宽 + 微信 appid 未替换 + `urlCheck:false` | `app/manifest.config.ts:36,68,70` | P2 中 |
| 19 | 下载工具另建 axios 实例，绕过全部拦截器 | `web/src/utils/download/index.ts:23` | P3 低 |
| 20 | 4 个空目录、1 个死组件、`VITE_DROP_CONSOLE` 死配置、死导出函数 | 见 WEB-02 / WEB-14 | P3 低 |

> **状态更新（t9）**：表中 **1-5 条 P0 已修复**，逐条的文件:行号、依据与验证证据见 **§6 P0 修复记录**。其余条目仍未处理。

---

## 1. 环境与验证记录（可复现）

| 检查 | 命令 | 结果 |
|---|---|---|
| 工具链 | `pnpm -v` / `node -v` | pnpm 10.34.5 / node v24.17.0（均可用，`node_modules` 已存在） |
| Web 类型检查 | `cd frontend/web && pnpm run type-check` | **exit 0，无输出**（`vue-tsc --noEmit`） |
| App 类型检查 | `cd frontend/app && pnpm run type-check` | **exit 0，无输出** |
| Web 单测 | `cd frontend/web && pnpm run test` | **exit 0**，2 个文件 / **10 个用例全通过**（1.59s） |
| 生成文件缺失对照实验 | 拷贝 `src` 到 `/tmp`，删除被 gitignore 的 `auto-imports.d.ts`/`components.d.ts` 后跑 `vue-tsc` | **exit 2，1358 个错误**（1233 × TS2304 "Cannot find name"）；补回两文件后 **exit 0** |
| 契约比对 | 读取 `backend/app/modules/system/auth/controller.py`、`backend/app/api/v1/routers.py`、`backend/app/modules/*/**/controller.py` | 见 §3（只读，未修改后端） |
| axios 对象→FormData 行为 | 读取 `web/node_modules/axios/lib/defaults/index.js:47-110`（axios 1.16.1） | 确认 `Content-Type: multipart/form-data` + 对象体 → **axios 会转换为 FormData**，故 Web 登录**不是**缺陷（避免误报） |

未执行（本轮约束）：`pnpm build`（两端）、`lint`/`stylelint`（默认带 `--fix`，会写文件）、任何 dev/preview server、依赖安装、后端相关命令；`frontend/app` 无测试可跑（仓库内 0 个测试文件）。

> 说明：两端 `tsconfig` 均为 `strict: true`（Web 另有 `noUncheckedIndexedAccess: true`），因此"类型检查通过"本身是有含金量的结论；但 Web 端类型检查依赖**未纳入版本控制的生成声明文件**（见 WEB-11），可复现性存疑。

---

## 2. 问题清单

级别定义：**P0 高** = 生产功能不可用/构建产物异常；**P1 高** = 明显缺陷或可复现的工程风险；**P2 中** = 显著质量/安全问题；**P3 低** = 清理项。

### 2.1 Web 构建与配置

#### WEB-01【P0 高】生产构建开关恒不生效：不压缩、不删 console、打包 devtools
- 文件：`frontend/web/vite.config.ts:28`（`const isProduction = mode === "prod";`），消费点 `:66`（`minify`）、`:220-238`（gzip/brotli）、`:240`（`vueDevTools()`）
- 现象：`isProduction` 只在 `mode === "prod"` 时为真。但 `package.json:12` 的 `build` 是 `vue-tsc --noEmit && vite build`（mode 默认 `production`），`package.json:13` 的 `build:prod` 是 `vite build --mode production`。仓库中**不存在** `.env.prod` 或任何 `--mode prod` 的脚本 → `isProduction` 恒为 `false`。
- 影响：
  1. `minify: false` → 生产 JS 完全不压缩（体积成倍）；
  2. `terserOptions.compress.drop_console/drop_debugger` 不生效 → 源码里 175 处 `console.*` 全部进入生产包；
  3. gzip/brotli 预压缩产物不生成（依赖 nginx `gzip_static` 的部署方式失效）；
  4. `vite-plugin-vue-devtools` 被编进生产包（作者本意只在非生产启用），既是体积问题也是信息暴露面。
- 建议修法：把判据改为 `const isProduction = mode === "production" || mode === "prod";`（或 `import.meta.env.PROD`），并补一个 `--mode prod` 的 `.env.prod`；同时补 CI 断言：构建后校验 `dist/js` 存在已压缩文件且产物内无 `console.log`。

#### WEB-02【P3 低】`VITE_DROP_CONSOLE` 是死配置
- 文件：`frontend/web/.env.development:17`、`.env.production:13`、`src/env.d.ts:48`（声明）；全仓无任何读取处（`grep VITE_DROP_CONSOLE` 仅命中声明）
- 现象：文档描述"是否删除控制台输出"，实际由 `vite.config.ts` 的 `terserOptions` 控制，且因 WEB-01 也未生效。
- 影响：配置项误导后续维护者，会以为 console 已被剥离。
- 建议修法：删除该变量；或改为在 `vite.config.ts` 中真正读取 `env.VITE_DROP_CONSOLE` 驱动 `drop_console`。

#### WEB-03【P3 低】`chunkSizeWarningLimit: 4000` 掩盖分包问题
- 文件：`frontend/web/vite.config.ts:65`
- 现象：把 Rollup 体积告警阈值抬到 4000KB，而不是解决单 chunk 过大。
- 影响：体积回归不会被构建日志提示（配合 WEB-06 的 eager glob，风险叠加）。
- 建议修法：回落到默认 500KB，改用真实分包（见 WEB-06）消化告警。

#### WEB-04【P3 低】`serve:prod` 无代理配置，preview 下 `/api/v1` 必然 404
- 文件：`frontend/web/package.json:15`（`vite preview --mode production`）、`vite.config.ts:35-46`（只有 `server.proxy`，没有 `preview.proxy`）
- 现象：生产 `VITE_APP_BASE_API=/api/v1` 是相对路径（`web/.env.production`），依赖同源反向代理；而 `vite preview` 不读 `server.proxy`。
- 影响：本地验收生产产物时接口全 404，容易被误判为"接口挂了"。
- 建议修法：补 `preview.proxy` 与 `server.proxy` 同一份配置（抽常量复用），或在 README 明确 preview 需配合 nginx/docker 代理。

### 2.2 Web 路由与权限

#### WEB-05【P1 高】动态路由"去重"守卫是死代码，重复注册无法拦截
- 文件：`frontend/web/src/router/route-loader.ts:326`（`if (this.router.hasRoute(registrationName(menu, index).trim())) return;`）、`:376-379`（`registrationName` 定义）、`:334`（实际以 `routeRecord.name` 注册）
- 现象：`registrationName()` 返回 `Dyn_${index}_${name}`，但注册时用的名字来自 `RouteTransformer`（`route.name || firstSegment`）。全仓 `registrationName` 只有"定义 + 这次判断"两处引用 → `hasRoute()` **永远为 false**，去重逻辑失效。注释"去重：已注册过该 path 第一段则跳过"与实现不符（`firstSegment` 变量只用于壳层判断，未参与去重）。
- 影响：`guards.ts:157` 与 `refresh.ts:46` 每次都会 `new RouteRegistry(router)`，实例级 `registered` 标志无法跨实例生效；配合 WEB-06（匿名路由未被清理，见下）在"菜单刷新/重新登录"路径上可能重复 `addRoute`，出现同名路由告警、路由被后注册项覆盖、工作标签栏指向失效路由。
- 建议修法：`register()` 内改用 `router.hasRoute(String(routeRecord.name))` 做真实判断（或按 `path` 首段集合判重）；把 `RouteRegistry` 做成单例或复用 `menuStore` 中保存的清理函数。

#### WEB-06【P1 高】匿名动态路由不会被清理，菜单刷新后残留
- 文件：`frontend/web/src/router/route-loader.ts:336-341`（清理闭包 `if (name && this.router.hasRoute(name))`）、`frontend/web/src/router/MenuProcessor.ts:50`（`const name = item.route_name || undefined;`）
- 现象：后端菜单节点可以不配 `route_name` → 转换出的路由 `name === undefined` → 清理闭包直接跳过，`removeRoute` 永不执行，而路由确实被 `addRoute` 了。
- 影响：`refreshMenuAndRoutes()`（`refresh.ts:39`）先删后注册，未删掉的路由留下"幽灵页面"：菜单里已不可见，但直接输入 URL 仍能打开（权限收紧后尤其危险）。
- 建议修法：注册时保证每条动态路由都有确定性 name（如 `dyn_${index}_${path}`）并以此 name 记录清理函数；或在清理阶段按 `path` 前缀遍历 `router.getRoutes()` 移除。

#### WEB-07【P2 中】壳层路径白名单在两处不一致
- 文件：`frontend/web/src/router/guards.ts:249`（`SHELL_SEGMENTS = new Set(["home","dashboard","fastlink"])`） vs `frontend/web/src/router/route-loader.ts:371`（`["home","profile","changelog","dashboard"]`）
- 现象：路由注册器认为 `profile`/`changelog` 是壳层（跳过注册），权限校验器认为 `fastlink` 是壳层（无条件放行）。两份手工维护的清单已经不同步。
- 影响：若后端菜单出现一级 `profile`，会出现"路由不注册 + 权限校验也不认"→ 用户被静默重定向到首页；`fastlink` 整段（含 `fachat` AI 聊天壳）对所有登录用户无条件放行。
- 建议修法：抽出单一常量（例如 `router/shell-segments.ts`）供两处 import；壳层放行改为基于实际已注册的静态路由表判断，而非硬编码字符串集合。

#### WEB-08【P2 中】守卫中的"异常恢复"是空实现
- 文件：`frontend/web/src/router/guards.ts:207-213`（`repairDynamicRoutesIfMenuEmpty` 只 `console.warn`）
- 现象：函数名与调用意图（`:140`）都是"菜单空了但路由还在 → 修复"，函数体只有一行 warn，不做任何反注册。
- 影响：`RouteRegistry.unregister()` / `markAsRegistered()`（`route-loader.ts:347,365`）均无调用点，实际恢复路径依赖 `routeInitFailed` 之类的间接状态，问题被掩盖而非修复。
- 建议修法：实现真正的修复（`resetDynamicRoutesSync()` 已存在，可直接调用）或删除该函数与调用点，避免"看起来有兜底"。

#### WEB-09【P2 中】iframe 路由无 `sandbox`，且 URL 来自菜单配置
- 文件：`frontend/web/src/router/routes.ts:151-179`（`IframeView`），关键行 `:170-177`（`h("iframe", { src: iframeUrl.value, ... })`）
- 现象：`src` 来自 `IframeRouteManager` / `route.meta.link`（后端菜单可配置任意 URL），渲染时未设置 `sandbox`、`referrerpolicy` 或白名单校验。
- 影响：管理员/被篡改的菜单可让登录用户的内嵌 iframe 承载任意第三方页面，该页面与主站同窗口上下文（可发起顶层导航、读 referrer、诱导钓鱼）；虽非同源脚本执行，仍属可被利用的信任边界缺失。
- 建议修法：加 `sandbox="allow-scripts allow-same-origin allow-forms allow-popups"`（按需最小化）、`referrerpolicy="no-referrer"`，并对 `link` 做协议白名单（仅 http/https）校验。

#### WEB-10【P3 低】成功提示的过滤用子串匹配 `login`
- 文件：`frontend/web/src/utils/http/index.ts:251-252`（`!response.config.url?.includes("login")`）
- 现象：用 `includes("login")` 判断"登录/登出接口"，但 `/system/log/login/list`（登录日志）也包含 `login`。
- 影响：对登录日志的分页/导出等非 GET 请求，成功提示被静默吞掉，表现为"点了没反应"。
- 建议修法：改为精确路径匹配（`url.endsWith("/auth/login")` / `/auth/logout`）或白名单数组。

### 2.3 Web 类型、规模与死代码

#### WEB-11【P1 高】类型检查依赖被 gitignore 的生成声明文件 → 全新 clone 无法通过 type-check
- 文件：`frontend/web/.gitignore:12-13`（忽略 `src/types/auto-imports.d.ts`、`src/types/components.d.ts`）、生成方 `vite.config.ts:190,205`
- 现象：`src/types/auto-imports.d.ts`、`src/types/components.d.ts` 未被 git 跟踪（`git ls-files` 无输出），仅由 `unplugin-auto-import` / `unplugin-vue-components` 在 **vite 进程**中生成。而 `type-check` = `vue-tsc --noEmit`，不会触发生成。
- 实测证据：把 `src` 拷到 `/tmp/fa-audit-web`（软链 node_modules）后删掉这两个文件 → `vue-tsc --noEmit` **exit 2，1358 个错误（1233 个 TS2304）**；补回文件 → **exit 0**。本地之所以绿，是因为工作区里残留着上次构建生成的产物。
- 影响：CI/新同事按 `pnpm type-check` 或 `pnpm build` 的顺序执行时，若未先跑过 vite，类型门禁直接失败（且报错信息是几百条"Cannot find name 'ref'"，极难定位真因）。对照：`frontend/app/src/auto-imports.d.ts`、`components.d.ts` 是**已提交**的，两端策略不一致。
- 建议修法：二选一并写进文档——(a) 把这两个 `.d.ts` 从 `.gitignore` 移出并提交（与 app 端一致）；或 (b) 增加 `"type-check": "vite build --mode development --emptyOutDir=false ... && vue-tsc --noEmit"` 之类的"先生成后检查"脚本（或 `unplugin-auto-import` 的独立生成命令），并在 CI 中固定顺序。

#### WEB-12【P2 中】`any` 泛滥且被 lint 规则放行
- 文件：`frontend/web/eslint.config.mjs:68`（`"@typescript-eslint/no-explicit-any": "off"`）
- 现象：`grep` 统计 Web `src` 下 `: any` / `as any` / `<any>` / `any[]` 共 **187 处，分布在 65 个文件**（App 端仅 14 处）。典型：`route-loader.ts:35,44,56`（`load(): any`、`(mod as any).default`）、`vite.config.ts:141`（`assetInfo: any`）、`utils/download/index.ts:10,15`。
- 影响：路由/组件加载这条最核心的链路完全无类型保护；`any` 会把 `undefined` 传下去（如 WEB-05 的 name 问题），且 `strict` 的价值被局部抵消。
- 建议修法：规则改为 `"error"` 或至少 `"warn"`，用 `unknown` + 收窄替代；`ComponentLoader.load()` 返回 `Component`，`assetFileNames` 用 `PreRenderedAsset`。

#### WEB-13【P2 中】超大文件与单文件多职责
- 文件（行数）：
  - `web/src/views/fastlink/tutorial/index.vue` 1881
  - `web/src/views/module_task/storage/browse/index.vue` 1746
  - `web/src/views/module_system/menu/index.vue` 1319
  - `web/src/views/module_task/cronjob/job/index.vue` 1250
  - `web/src/views/module_generator/gencode/index.vue` 1224
  - `web/src/layouts/fa-work-tab/index.vue` 1083、`web/src/hooks/core/useTable.ts` 819、`web/src/hooks/core/useChart.ts` 773、`web/src/store/modules/worktab.store.ts` 670、`web/src/utils/table/index.ts` 606
- 现象：Web `src` 非声明文件合计约 **80,022 行**（App 端约 9,259 行，最大单文件 716 行）。上述页面把表单、表格列、按钮权限、Dialg、样式、i18n 文案全部塞在一个 SFC 里。
- 影响：改动冲突率高、无法按需懒加载、单测无法覆盖（整文件依赖构建期自动导入，见 `route-invariants.spec.ts` 的注释——测试只能靠 `vi.mock` 打桩）。
- 建议修法：以 `fa-table` / `fa-form` 已有的组合式 API 为基线，把超大页面拆成 `modules/` 子组件 + 列定义文件 + `useXxxPage()`；`tutorial/index.vue` 是纯文档页，建议直接改为数据驱动（`manualSections.ts` 已是数据，模板可进一步收敛）。

#### WEB-14【P3 低】死代码与空目录
- 死组件：`web/src/components/charts/fa-echarts/index.vue`（89 行）——除自身及生成的 `types/components.d.ts:139` 外无任何引用（组件卡片的图表走 `fa-line-chart` 等）。
- 死导出：`web/src/utils/http/index.ts:140`(`showError`)、`:147`(`showSuccess`)、`:29`(`ExtendedRequestConfig`)、`:49`(`ErrorLogData`) 在 `utils/http` 之外 0 引用。
- 空目录：`web/src/utils/oauth/`、`web/src/utils/socket/`、`web/src/layouts/fa-chat-window/`、`web/src/views/module_system/chat/`。
- 过期 lint 忽略项：`web/eslint.config.mjs:30` 忽略 `src/utils/console.ts`，该文件不存在。
- 建议修法：删除上述文件/目录/忽略项；对公共包（`utils/http`）保留的 API 需有调用点，否则一并删除。

### 2.4 Web 安全与数据真实性

#### WEB-15【P1 高】登录页硬编码 3 个演示账号（密码均 `123456`）且可一键回填
- 文件：`frontend/web/src/views/module_system/auth/login/index.vue:333-355`（`accounts`：`super/admin/user`，`password: "123456"`）、`:474-479`（`setupAccount()` 把用户名+密码写进 `loginForm`）
- 现象：登录页内置演示账号下拉/切换，选中即填充账号密码（`demoAccountKey` 默认 `"super"`）。
- 影响：若这些账号在部署环境中真实存在（该项目的种子数据通常包含它们），等价于把后台最高权限账号密码印在登录页上；即便部署方改了密码，仍暴露了默认口令策略与用户名枚举。
- 建议修法：改为构建期变量（`VITE_DEMO_ACCOUNTS`）+ 仅在 `import.meta.env.DEV` 或显式开关下渲染；生产构建彻底移除，并加一条构建期校验（产物中不得出现 `123456`）。

#### WEB-16【P2 中】屏幕锁"加密密钥"随 `.env` 提交仓库，锁形同虚设
- 文件：`frontend/web/.env:25`（`VITE_LOCK_ENCRYPT_KEY = s3cur3k3y4adpro`，该文件**已被 git 跟踪**）、`frontend/web/.gitignore` 未忽略该文件、消费点 `frontend/web/src/layouts/fa-screen-lock/index.vue:168,363,393`（`CryptoJS.AES.decrypt(storedPassword, ENCRYPT_KEY)`）
- 现象：锁屏密码用硬编码在仓库里的对称密钥（AES 口令模式）加密后存本地；`crypto-js` 的声明是 `declare module "crypto-js"`（`env.d.ts:77`）——**完全没有类型**。
- 影响：任何拿到仓库的人都能解密锁屏口令；锁屏从"安全控制"退化为"防误触 UI"。同时 `.env` 里出现密钥会诱导把真正的密钥也放进来。
- 建议修法：明确锁屏是 UI 层面的防误触，移除"AES 加密"叙事（改存不可逆的本地校验值，如 `hash(password+salt)`）；若确需加密，密钥改为用户输入派生而非仓库常量；同时把 `crypto-js` 补上 `@types/crypto-js` 或删除依赖（当前仅此一处使用）。

#### WEB-17【P2 中】生产仪表盘展示 mock 数据
- 文件：`frontend/web/src/views/dashboard/home/index.vue:165`（`import { getDashboardMock, ... } from "@/mock/dashboard"`）、`:176-177`（`healthList = ref(mock.health)`、`timelineData = ref(mock.timeline)`）、`:182-185`（`onMounted` 内真实接口 `DashboardAPI.getStats()` 被注释掉）
- 现象：首页的时间线/健康列表硬编码为 mock 初值，真实统计接口调用被注释；`mock/dashboard.ts` 因此被真实打进产物（`api/module_monitor/dashboard.ts:3` 也从 mock 引类型）。
- 影响：**线上展示编造数据**（用户会当成真实运维数据），并让 mock 模块无法被 tree-shake。
- 建议修法：删除 `mock` 依赖，未接后端时改为骨架屏/空态；`HealthItem` 等类型迁到 `api/module_monitor/dashboard.ts`；若必须保留演示数据，用 `import.meta.env.DEV` 包住并动态 import。

### 2.5 移动端（frontend/app）

#### APP-01【P0 高】刷新令牌请求体与后端契约不符 → 静默续期必然失败
- 文件：`frontend/app/src/api/module_system/auth.ts:34-39`（`refreshToken(body: RefreshToekenBody)`，发 `{ refresh_token }` 对象），调用点 `frontend/app/src/http/adapters/alova.ts:81-83`
- 后端事实：`backend/app/modules/system/auth/controller.py:57` —— `payload: Annotated[str, Body(description="刷新token参数")]`，即 **body 必须是 JSON 字符串**（Web 端实现正确：`web/src/api/module_system/auth.ts:25-31` 直接发 `data: refreshToken`）。
- 现象：移动端发 `{"refresh_token":"..."}`，FastAPI 对 `str` 的 body 解析会返回 422（`Input should be a valid string`）。
- 影响：**access token 过期后无法续期**，`handleUnauthorized`（`alova.ts:60-102`）每次都会走到 `catch` → 清凭据 + 跳登录页。用户表现为"用一会儿被强制登出"，而 Web 端无此问题。同时 `RefreshToekenBody` 是多端漂移的产物（Web 端没有这个类型）。
- 建议修法：改为 `http.Post(url, JSON.stringify(refreshToken), { meta: {...} })`（与 `logout(token)` 的写法一致，见 `auth.ts:58-60` 的注释——同一后端约定），删除 `RefreshToekenBody`，并补一条契约测试。
- 复现建议：`curl -s -X POST .../api/v1/system/auth/token/refresh -H 'Content-Type: application/json' -d '{"refresh_token":"x"}'` → 422；`-d '"x"'` → 进入业务逻辑。**（本轮未发请求，仅静态比对；如需 100% 确认请由后端同学执行上述 curl）**

#### APP-02【P0 高】头像上传路径不存在（缺 `/common` 前缀）
- 文件（**活代码**）：`frontend/app/src/subPages/module_system/profile/index.vue:26`
  ```ts
  const uploadAvatarAction = `${import.meta.env.VITE_API_BASE_URL || ''}${import.meta.env.VITE_APP_BASE_API || ''}/file/upload?upload_type=avatar`
  ```
  该地址交给 `wd-upload` 使用（模板 `:147`），成功后回调 `handleAvatarSuccess`（`:82-97`）。
- 文件（**同缺陷的死代码**）：`frontend/app/src/api/module_system/user.ts:27-29`（`http.Post('/file/upload?upload_type=avatar', ...)`）——全仓无调用点（`grep uploadCurrentUserAvatar` 仅命中定义本身），与 Web 端同名方法（`web/src/api/module_system/user.ts:15-19`，被 `views/fastlink/current/profile.vue:489,630` 使用）形成"有实现但没人用"的分叉。
- 后端事实：`backend/app/modules/common/file/controller.py:15`（`prefix="/file"`）挂在 `backend/app/api/v1/routers.py:63` 的 `"/common"` 域下 → 真实路径 `/api/v1/common/file/upload`；Web 端写法正确（`web/src/api/module_system/user.ts:17`：`/common/file/upload?upload_type=avatar`）。
- 现象：真实请求变成 `https://service.fastapiadmin.com/api/v1/file/upload?upload_type=avatar`（dev/prod 的 `VITE_API_BASE_URL` 都是该域名），后端无此路由。
- 影响：移动端个人中心**更换头像必然失败**（404），失败提示是通用文案（`profile.uploadFailed`），用户无法自查原因。
- 附带问题（同一处代码）：该页**绕过了统一 `http` 层**——自己拼 URL（`:26`）、自己拼 `Authorization` 头（`:27`）、自己在回调里 `JSON.parse`（`:83-84`）。因此上传请求不享受 401 静默续期（`http/adapters/alova.ts:60-102`）与统一错误提示；且 `login_type`/`VITE_APP_BASE_API` 这类拼接散落在页面里，与 API 模块重复（对照 DUP-03 的 Web 端同类问题）。
- 建议修法：
  1. 路径改为 `/common/file/upload?upload_type=avatar`；
  2. 上传能力收敛进 `api/module_system/user.ts`，页面只调用它；`wd-upload` 若要传 action，可从同一常量派生；
  3. 把"上传端点"登记进两端共享常量表（与 APP-01 一并治理），杜绝再次手抄。

#### APP-03【P0 高】生产环境 WebSocket 指向 localhost 且非加密
- 文件：`frontend/app/.env.production:23`（`VITE_APP_WS_ENDPOINT= ws://localhost:5180/ws`）、消费点 `frontend/app/src/composables/useAiChat.ts:18-25`
- 现象：`buildChatWsUrl()` 拼出 `ws://localhost:5180/ws/api/v1/ai/chat/ws?token=...`（`wsBase + apiPrefix + path`）。该地址只在"同时在本机 5180 起了一个 dev server"时才有意义。
- 影响：生产/真机上的 AI 流式对话必然连不上（小程序端还会因 `ws://` 非加密域名被拒/被平台拦截）；同一文件 `:24` 的注释还写着"不配置默认关闭 WebSocket"，与"生产给了个 localhost 值"自相矛盾。
- 建议修法：生产改为 `wss://<后端域名>`（或留空走 `VITE_API_BASE_URL` 的 `http→ws` 推导分支），并删除 `/ws` 这类路径残渣；在 `manifest`/CI 增加"生产 env 不得含 localhost"的校验。

#### APP-04【P1 高】开发环境直连生产后端
- 文件：`frontend/app/.env.development:5-6`（第 5 行是注释掉的 `http://localhost:8001`，第 6 行 `VITE_API_BASE_URL=https://service.fastapiadmin.com`），该文件**已被 git 跟踪**（`git ls-files frontend/app/.env.development`）
- 现象：`pnpm dev` 默认把所有请求打到线上 `service.fastapiadmin.com`。对比 Web 端 `frontend/web/.env.development`（**未被跟踪**）指向 `http://127.0.0.1:8001` —— 两端策略相反。
- 影响：本地调试/联调会直接读写生产库（新建工单、改公告、删数据都是真实操作）；本地登录会占用线上会话（同账号互踢）；新人 clone 后第一次 `pnpm dev` 就踩坑。
- 建议修法：`.env.development` 默认指向本地，线上地址放进不跟踪的 `.env.development.local`；与 Web 端对齐"env 文件不入库、只提交 `.example`"的策略（Web 已有 `.env.*.example` 范式）。

#### APP-05【P1 高】`wot-ui` 路由守卫只判断登录，无任何权限门禁
- 文件：`frontend/app/src/router/index.ts:30-47`（只判断 `isAuthPage` 与 `userStore.isLoggedIn()`）；`frontend/app/src/constants/storage.constant.ts:28`（`ROLE_ROOT = 'ADMIN'` 定义后**无任何使用点**）
- 现象：登录后任何用户都能进入 `subPages/module_ai/ai-models/index.vue`（AI 模型配置，可增删改含 `api_key` 的配置）、工单管理、公告管理等页面；页面本身也不做 `is_superuser`/`roles` 判断（全仓仅 `profile/index.vue:65` 把 roles 当展示字段）。
- 影响：**不构成越权**（已核对后端：`backend/app/modules/ai/chat/controller.py` 的 `/model` 各写接口均有 `Security(AuthPermission(["module_ai:chat:update"]))`），但是：(a) 普通用户会看到并进入只为管理员准备的界面，操作后拿到 403 提示，体验混乱；(b) 前端完全失去"能力可见性"这一层，菜单/入口无法按角色裁剪；(c) `ROLE_ROOT` 这类死常量会误导后续开发以为已有角色体系。
- 建议修法：登录后拉取一次权限集合（后端已有 `AuthPermission` 的权限码体系），在守卫/页面入口按权限码过滤路由与入口按钮；或复现 Web 端的"后端菜单驱动"思路（移动端用白名单路由表 + `roles` 过滤）。至少先把 `ROLE_ROOT` 删除或落地使用。

#### APP-06【P2 中】移动端无类型检查门禁、无任何测试
- 文件：`frontend/app/package.json:31`（`"build": "uni build"`，不跑 `vue-tsc`）、`:50`（`type-check` 脚本存在但无人调用）、仓库内 0 个 `*.spec.ts`/`*.test.ts`
- 现象：App 端 `type-check` 是可用的（本轮实测 exit 0），但 `build`/CI 不调用；上传 `auto-imports.d.ts`、`components.d.ts`（已提交）说明生成文件是入库的，检查成本已很低。
- 影响：类型错误不会阻断构建；核心逻辑（alova 401 队列、token 存储、路由守卫）零回归保护——APP-01/APP-02 这类契约破损正是因为缺测试才漏到线上。
- 建议修法：`build` 改成 `vue-tsc --noEmit && uni build`；为 `http/adapters/alova.ts` 的 401 队列、`useAiChat`、`storage.ts` 补最小单测（vitest 已在 Web 端跑通，配置可复用）。

#### APP-07【P2 中】应用商店合规与产品化问题
- 文件：`frontend/app/manifest.config.ts:13`（`name: 'wot-starter'`）、`:14`（`appid: '__UNI__1208592'`，模板自带）、`:36-52`（安卓权限列表）、`:68`（`appid: 'wxf306aa91619d2e1c'`，第 67 行 TODO 明确写着"替换为实际的微信小程序 appid"）、`:70`（`setting.urlCheck: false`）
- 现象：
  1. 应用名/DCloud appid 仍是 starter 模板值（页面标题却已是 FastapiAdmin）→ 名字与包标识不一致；
  2. 申请了 `READ_LOGS`、`READ_PHONE_STATE`、`GET_ACCOUNTS`、`WRITE_SETTINGS`、`MOUNT_UNMOUNT_FILESYSTEMS` 等与业务无关的高敏权限；
  3. 真实的微信小程序 appid 被提交进仓库，且"待替换"的注释长期未清理；
  4. `urlCheck: false` 关闭了微信开发者工具的域名校验（仅影响开发者工具，但常被误当配置带进发包流程）。
- 影响：应用商店（尤其国内安卓渠道/App Store）上架会被权限最小化审核驳回或要求补隐私说明；模板残留直接影响品牌与合规材料；appid 泄露本身风险低（非密钥），但 TODO 长期挂着说明发布流程无检查。
- 建议修法：替换 `name`/`appid`/`versionName`；按实际功能裁剪安卓权限（相机/相册/网络/震动通常足够）；appid 改为构建期注入（或至少移除 TODO 并确认是公开值）；`urlCheck` 收回到仅调试配置。

#### APP-08【P3 低】token 走 URL query（可缓解，但需明确）
- 文件：`frontend/app/src/composables/useAiChat.ts:24-25`（`.../ai/chat/ws?token=${encodeURIComponent(token)}`）
- 现象：为兼容小程序 WebSocket 无法自定义子协议，把 access token 放在 query。
- 影响：token 会进入网关/反代访问日志、`Referer` 类日志与错误上报；与 Web 端做法不同（Web 用 `Sec-WebSocket-Protocol`，见 `web/src/views/module_ai/chat/index.vue:99-104`，注释明确写着"避免出现在 URL 与服务端 access log 中"）。
- 建议修法：服务端支持"连接后首帧鉴权"（先 `{action:"auth",token}` 再收发业务帧）或签发一次性短时效 ws ticket，取代长时效 token 入 query；至少在文档中标注该风险并缩短 token 有效期。

#### APP-09【P3 低】存储读取把 falsy 值当作"不存在"
- 文件：`frontend/app/src/utils/storage.ts:13-17`（`const value = uni.getStorageSync(key); if (!value) return defaultValue as T`）
- 现象：`""`、`0`、`false` 被一律视为未设置；且 `JSON.parse` 失败时返回原始字符串（`:21-24`），造成同一 key 可能返回两种类型。`get()` 泛型 `T` 也因此不成立。
- 影响：布尔/数字型配置（如 `THEME_KEY`、`WATERMARK_KEY`）无法存 `false`/`0`；类型欺骗会让调用方以为拿到的是 T。
- 建议修法：用 `uni.getStorageInfoSync().keys.includes(key)` 或 `value === undefined || value === ''` 判存在；解析失败时记录告警并返回 `defaultValue`。

#### APP-10【P3 低】生产包保留逐次导航日志
- 文件：`frontend/app/src/router/index.ts:50-54`（`afterEach` 中 `console.log("📍 页面切换: ...")`）、`frontend/app/eslint.config.mjs:7`（`'no-console': 'off'`）
- 现象：每次页面切换都打日志，且 lint 允许 console。
- 影响：小程序/App 生产环境日志噪音（微信小程序还有日志体积与性能开销）。
- 建议修法：日志收敛到 `utils/console` 并受 `VITE_APP_ENV` 控制；lint 改回 `no-console: warn` 并对 `console.error/warn` 放行。

#### APP-11【P3 低】响应类型定义过于宽松 + `msg`/`message` 双字段兼容
- 文件：`frontend/app/src/http/types.ts:19-27`（`IResponse` 同时有 `msg`、`message?`、`[key: string]: any`）、`:33`（`PageParams` 也是 `[key:string]: any`）、`frontend/app/src/http/adapters/alova.ts:18-20`（`getErrorMessage` 依次尝试 `msg/message/error`）
- 现象：后端统一响应只是 `code/data/msg`（见 `backend/app/common/response.py` 的 `ResponseSchema`），移动端却按"兼容三套字段"实现。
- 影响：契约被"宽容"掩盖——真正的字段改名不会报错而会静默降级为通用提示（APP-01/APP-02 的失败提示就被吞成"请求错误"），排查成本高。
- 建议修法：`IResponse<T>` 收敛为 `{ code: number; data: T; msg: string }`，删除索引签名与 `message?`；错误提示保留 `msg` 单一路径。

### 2.6 两端重复与可复用性

#### DUP-01【P2 中】49 个同名类型在两端各有一份副本，且已发生漂移
- 证据：抽取两端 `api/`+`types/` 的 `interface/type` 名做交集 → **49 个重名**，含 `LoginFormData`、`LoginResult`、`MenuTable`、`UserInfo`、`roleSelectorType`、`positionSelectorType`、`deptTreeType`、`NoticeForm`、`TicketForm`、`BaseFormType`、`ApiResponse`、`CaptchaInfo`、`PageResult`、`DashboardStats` 等（Web 侧 222 个类型 / App 侧 84 个）。
- 现象：App 端每个 api 文件顶部注释都写着"与 web 端 module_system/xxx.ts 对齐（完整字段定义）"——即**靠人工同步**。
- 影响：漂移已经真实发生：`refresh_token` 请求体（APP-01）、上传路径（APP-02）；此外 App 端命名也不同（`LoginResult` vs Web 的 `JWTOut`/`LoginResult` 别名、`RefreshToekenBody` 拼写错误 `Toeken`）。
- 建议修法：在后端 OpenAPI 已存在的前提下，用 `openapi-ts-request`（App 依赖里已有 `@alova/wormhole`，`package.json` 也有 `alova-gen` 脚本）为两端生成共享类型/schema 包；或在 `frontend/shared/` 建一个 workspace 包存放纯类型，两端 `dependencies` 引用。

#### DUP-02【P2 中】401 静默续期逻辑在两端各写一遍，实现不一致
- 文件：`frontend/web/src/utils/http/index.ts:157-182,307-358`（axios 版：`isRefreshing` + `pendingRequests` 重放） vs `frontend/app/src/http/adapters/alova.ts:31-102`（alova 版：同样语义但用 `Method.send()` 重放）
- 现象：两段"防并发刷新 + 队列重放"逻辑语义相同、代码不同，且只有 Web 版正确（APP-01）。错误映射也是两套：Web `getErrorMessage`（`utils/http/index.ts:97-111`，i18n key）vs App `getErrorMessage`（`adapters/alova.ts:18-20`，中文字面量 `ShowMessage`）。
- 影响：修一处漏一处（本次审计已坐实）；错误文案在中英文/两端之间不一致。
- 建议修法：把这套状态机抽成不依赖具体 HTTP 客户端的纯函数模块（注入 `sendRefresh()` 与 `replay(method)`），两端各自适配；错误码→文案映射收敛为一份 key 表。

#### DUP-03【P3 低】Web 内部两套 HTTP 通道
- 文件：`frontend/web/src/utils/http/index.ts:186`（统一 `request` 实例） vs `frontend/web/src/utils/download/index.ts:23`（另建 `axios.post` 直连）
- 现象：下载工具自己拼 `baseURL + "/common/file/download"`、自己加 `Authorization`、自己弹 `ElMessage`。
- 影响：**绕过响应拦截器** → 401 不会触发续期（下载接口失效时表现为"下载失败"而非重新登录）、错误码不会归一、`Content-Type` 头不一致；同时 `let downloadLoadingInstance: any`（`:10`）又是一处 `any`。
- 建议修法：改用统一 `request`（`responseType: "blob"`，拦截器已支持 `blob` 直通与 blob 错误体解析，见 `utils/http/index.ts:235-237,288-305`），只保留 `saveAs` 部分。

#### DUP-04【P2 中】两端各有一套"菜单/路由"模型，App 端完全没有权限菜单
- 文件：Web `frontend/web/src/router/MenuProcessor.ts:36-95`（后端菜单 → `AppRouteRecord`，含目录/按钮过滤、`keep_alive`、`hidden` 映射） vs App `frontend/app/src/router/index.ts:6-25`（仅把 `virtual:uni-pages` 的静态页面列表铺平）
- 现象：同一份后端菜单数据（`MenuTable`）只有 Web 端消费；App 端页面清单是编译期静态生成的（`pages.json`），与后端权限体系无关。
- 影响：新增/下线功能需要改代码发版，无法像 Web 端那样按租户/角色动态下发；两端"同一功能不同入口"的维护成本持续上升。
- 建议修法：明确 App 端的产品边界（若本就是固定几屏，保留静态页面即可，但应删掉 App 端无用的 `MenuTable`/`permission`/`route_name` 字段与死常量 `ROLE_ROOT`，减少误导）；若要与后端菜单对齐，则复用 Web 端的菜单→页面的映射思路，只保留"权限码 → 页面白名单"这一薄层。

#### DUP-05【P3 低】Web 单测耦合后端种子数据
- 文件：`frontend/web/src/__tests__/route-invariants.spec.ts:113-117`（从 `process.cwd()` 向上找 `backend/sql/sys_menu.json` 并断言其内容）
- 现象：前端用例读取后端 SQL 种子文件，路径靠三个候选硬猜。
- 影响：前端独立仓库/CI（不带 backend 目录）时该用例失败；菜单数据迁移目录即红。当前工作区能过（本轮 10/10 通过）。
- 建议修法：把需要的菜单夹具快照进前端 `src/__tests__/fixtures/`，或把该用例移到后端/集成层。

---

## 3. 移动端与 Web 端的接口契约一致性（专项结论）

**结论：整体高度对齐，但存在 2 处已破损的硬契约 + 3 处口径不一致。**

### 3.1 已核对一致的端点（抽样）
| 功能 | Web 路径 | App 路径 | 后端路由 | 结论 |
|---|---|---|---|---|
| 登录 | `/system/auth/login`（multipart/form-data） | `/system/auth/login`（x-www-form-urlencoded） | `POST /system/auth/login`，`CustomOAuth2PasswordRequestForm`（`backend/app/core/security.py:55-92`，全 `Form`） | ✅ 一致（两种 content-type 都是 Form，合法） |
| 登出 | `/system/auth/logout`，body 为 JWT 字符串 | 同（`JSON.stringify(token)`） | `payload: Annotated[str, Body()]`（`auth/controller.py:85`） | ✅ 一致 |
| 当前用户信息 | `/system/user/current/info` | 同 | `GET /user/current/info` | ✅ |
| 修改密码 | `PUT /system/user/password/change` | 同 | ✅ | ✅ |
| 工单/公告/AI 会话 | `/system/ticket/*`、`/system/notice/*`、`/ai/chat/*` | 同 | 一致（逐条比对 `*_BASE_URL` 拼接结果） | ✅ |
| 监控 | `/monitor/online/stats`、`/monitor/server/info` | 同 | ✅ | ✅ |

### 3.2 已破损的契约（详见 §2.5）
1. **刷新令牌请求体**：后端要 JSON 字符串，Web 正确、**App 错误**（`app/src/api/module_system/auth.ts:34` → APP-01）。
2. **文件上传路径**：后端真实路径为 `/api/v1/common/file/upload`（`backend/app/api/v1/routers.py:63` + `common/file/controller.py:15`），Web 正确、**App 错误**（两处：活代码 `app/src/subPages/module_system/profile/index.vue:26`、死代码 `app/src/api/module_system/user.ts:27` → APP-02）。

### 3.3 口径不一致（不构成缺陷，但需统一）
| 项 | Web | App | 建议 |
|---|---|---|---|
| 运行时基址 | 编译期相对 `/api/v1` + dev 代理（`vite.config.ts:40`） | `VITE_API_BASE_URL + VITE_APP_BASE_API` 拼接（`app/src/http/adapters/alova.ts:108`） | 统一"相对 + 代理"或统一"绝对域名"，便于同一套 CORS/证书策略 |
| token 传递（WS） | `Sec-WebSocket-Protocol`（`web/.../module_ai/chat/index.vue:99-104`） | URL query `?token=`（`app/src/composables/useAiChat.ts:25`） | 服务端支持首帧鉴权（APP-08），两端统一 |
| 登录表单类型 | `multipart/form-data` | `application/x-www-form-urlencoded` | 都可用；建议统一为 urlencoded（语义更贴 Form，也避免 axios 隐式转 FormData） |
| 响应错误字段 | `msg`（i18n key 映射，`utils/http/index.ts:97-111`） | `msg/message/error` 三重兼容（`adapters/alova.ts:18-20`） | App 收敛为 `msg`（APP-11） |
| WS 端点变量 | `VITE_APP_WS_ENDPOINT`（dev `ws://localhost:8001`） | `VITE_APP_WS_ENDPOINT`（**prod 是 `ws://localhost:5180/ws`**） | 修 APP-03，并统一变量语义为"基址，不含业务路径" |

---

## 4. 按优先级排序的修复清单

### 第一批：先修（生产功能/产物已受影响，工作量小）
1. **WEB-01** 修正 `isProduction` 判据（1 行），并补 `.env.prod` 或改为 `import.meta.env.PROD`；重新构建后核对产物已压缩、无 `console.log`、无 devtools。→ 影响所有生产部署。
2. **APP-01** 刷新令牌改为发 JSON 字符串（与 `logout` 同一后端约定），删掉 `RefreshToekenBody`。→ 影响移动端登录态。
3. **APP-02** 头像上传路径补 `/common`（改 `profile/index.vue:26`，并把上传收敛进 `api/module_system/user.ts` 以免再分叉）。→ 影响移动端个人中心。
4. **WEB-09(富文本上传)** `web/src/components/forms/fa-wang-editor/index.vue:83`：默认 `uploadServer` 改为 `${VITE_APP_BASE_API}/common/file/upload`。→ 影响公告/工单/版本管理的富文本插图。
5. **APP-03** 生产 WS 端点改为 `wss://` 真实域名；顺带清理 `ws://localhost:5180/ws`。→ 影响移动端 AI 对话。
6. **APP-04** `.env.development` 改回本地地址，线上地址挪到不跟踪的 `.local`；与 Web 对齐 env 入库策略。→ 防止误操作生产数据。

### 第二批：紧接着修（工程防线与安全）
7. **WEB-11** 决定生成文件入库或补"先生成后检查"脚本，让 `pnpm type-check` 在新 clone/CI 上可复现。→ 影响 CI 可信度。
8. **WEB-15** 演示账号移出生产包（`import.meta.env.DEV` 或构建期变量 + 构建期校验）。→ 影响默认口令风险。
9. **WEB-06 / WEB-05** 动态路由命名与清理闭环：为每条动态路由生成确定性 name 并据此清理；修正失效的去重判断。→ 影响菜单刷新/权限收紧后的可达性。
10. **WEB-16** 锁屏改为不可逆本地校验（并补 `crypto-js` 类型或移除依赖）；`.env` 不再承载"密钥"。→ 影响安全性叙事与依赖质量。
11. **WEB-17** 首页移除 mock 依赖，改为骨架/空态。→ 影响线上数据可信度。
12. **APP-05** 移动端加权限可见性门禁（或明确边界并删除死常量 `ROLE_ROOT`）。→ 影响管理员功能暴露面与体验。
13. **APP-06** `build` 加 `vue-tsc --noEmit`；为 401 队列/token 存储补最小单测。→ 防止 APP-01/02 类问题复发。

### 第三批：规模化治理（有明确收益，需排期）
14. **DUP-01 / DUP-02** 抽共享类型包（或 OpenAPI 生成）+ 抽出"401 续期状态机"公共实现。→ 根治两端漂移。
15. **WEB-12** `no-explicit-any` 恢复为 warn/error，分批把 187 处 `any` 收敛（优先 `router/route-loader.ts`）。→ 恢复 `strict` 价值。
16. **WEB-13** 拆分 5 个 <1000 行的超大页面（先从 `fastlink/tutorial`、`module_task/storage/browse` 入手）。→ 提升可维护性与可测试性。
17. **WEB-06(性能)** 解决首屏全量加载：改为 `import.meta.glob` 默认（懒加载）+ 按目录分 chunk，同时把 `chunkSizeWarningLimit` 回落到默认值并观察真实分包收益。→ 影响首屏体积与加载时间。
18. **APP-07** 应用元数据/权限裁剪与发版检查清单。→ 影响上架合规。

### 第四批：清理（低成本，随迭代顺手做）
19. **WEB-10** 成功提示的 `includes("login")` 改精确匹配。
20. **WEB-14** 删死组件 `fa-echarts`、死导出（`showError`/`showSuccess`/`ExtendedRequestConfig`/`ErrorLogData`）、4 个空目录、ESLint 过期忽略项。
21. **WEB-02 / WEB-03 / WEB-04** `VITE_DROP_CONSOLE` 死配置、`chunkSizeWarningLimit`、`preview.proxy`。
22. **DUP-03** 下载工具改用统一 `request` 实例。
23. **DUP-05** 前端单测脱离后端 SQL 种子文件。
24. **APP-09 / APP-10 / APP-11** 存储判空、生产日志、响应类型收敛。

---

## 5. 不确定项与本轮未覆盖

1. **运行时行为未实测**：本轮未启动任何服务、未发 HTTP 请求。APP-01/APP-02 的契约结论来自"前端请求形态 vs 后端 `Body(str)`/路由注册表"的静态比对（后端代码位置已给出），真实性极高但建议由后端同学用一条 curl 复核。
2. **`pnpm-lock.yaml` 与 `package-lock.json` 并存**：`frontend/web` 同时存在 `package-lock.json`（444KB，5 月）与 `pnpm-lock.yaml`（318KB，7 月），`packageManager` 声明 pnpm，npm 锁文件是历史残留，可能导致安装产物不一致。未深入验证，列为待确认项。
3. **依赖版本前瞻性**：Web `package.json` 声明 `typescript ^6.0.3`、`vite ^7.1.5`、`eslint ^10.3.0`、`vue-router ^5.0.7`、`pinia ^3.0.4`；App 声明 `@dcloudio/*` 为 `3.0.0-4080520251106001` 这类日期快照版本。本地 `node_modules` 已满足检查，但版本组合的长期可升级性未评估（超出本轮范围）。
4. **样式与 i18n 质量未审计**：`styles/`（9 目录）、`locales/` 的完整性与 `stylelint` 实际告警数未跑（`stylelint` 默认带 `--fix`，本轮为避免改动文件未执行）。
5. **未评估 accessibility、浏览器兼容（`target: es2024` 与 `browserslist` 中 Chrome>=84 的矛盾）**：`vite.config.ts:63` 构建目标 `es2024`，而 `package.json` 的 `browserslist` 写着 `Chrome >= 84`——两者不一致会让构建产物直接使用新语法而不降级，在旧浏览器上白屏。**列为疑似问题，建议下一轮验证**（本轮未做产物分析）。
6. **App 端未跑的检查**：`uni build`（各平台）、`eslint`（`@uni-helper/eslint-config` 实际告警数）、`uni_modules/mp-html` 第三方组件安全性。

---

## 6. P0 修复记录（t9，已实施）

本轮对 §0 表中 5 条 P0 做了实现修复。**行号为本节修复后的当前行号**；`依据` 一栏说明"为什么这样改"的证据来源；`验证` 一栏是实际跑过的命令与结果。

### 修复 1 — WEB-01 生产构建开关恒不生效

| 项 | 内容 |
|---|---|
| 文件:行号（改后） | `frontend/web/vite.config.ts:37`（`isProduction`），连带生效：`:75`（`minify`）、`:76-90`（`terserOptions`）、`:233`（gzip/brotli）、`:253`（剔除 `vueDevTools`） |
| 改法 | `const isProduction = mode === "prod"` → `mode === "production" \|\| mode === "prod"`，并补注释说明脚本实际传的 mode |
| 附带修复（同一 terserOptions 块） | `frontend/web/vite.config.ts:85-89`：`format.comments: true` → `comments: "some"`。原写法是"**保留**全部注释"，与旁边的注释文字"删除注释"意图相反；它把第三方与自身源码的 JSDoc（含示例里的 `console.log(...)`）原样带进产物。改为 terser 默认语义后仅保留 `@license/@preserve/!` 版权注释（MIT 等许可证要求保留版权声明，故不能一律删光） |
| 依据 | `frontend/web/package.json:12` `build` = `vue-tsc --noEmit && vite build`（mode 默认 `production`）、`:13` `build:prod` = `vite build --mode production`；全仓无 `--mode prod` 脚本、无 `.env.prod` → 旧判据恒 false。`format.comments` 语义见 terser `format.comments`（`true`=保留全部，`"some"`=只保留版权类注释） |
| 验证 | `pnpm run build:prod` → exit 0；产物最大 app chunk `dist/js/index.D0MzHYyR.js` 仅 **2 行 / 665,571 字节**（证明已压缩）；`dist/js` 内 `.gz` 35 个、`.br` 35 个（预压缩生效）；`grep -rl 'vite-plugin-vue-devtools\|__VUE_DEVTOOLS_GLOBAL_HOOK__' dist/` = 0 个文件（devtools 已剔除）|

### 修复 2 — APP-01 刷新令牌请求体与后端契约不符

| 项 | 内容 |
|---|---|
| 文件:行号（改后） | `frontend/app/src/api/module_system/auth.ts:42-48`（`refreshToken(refreshToken: string)`，body 改为 `JSON.stringify(refreshToken)`）；调用点同步改为 `frontend/app/src/http/adapters/alova.ts:82`；删除无用类型 `RefreshToekenBody` |
| 依据 | 后端 `backend/app/modules/system/auth/controller.py:57`：`payload: Annotated[str, Body(...)]` → body 必须是 JSON **字符串**。同文件 `logout`（`auth.ts:58-60` 一带）已是"后端要字符串 → 前端 `JSON.stringify`"的既定写法；Web 端 `frontend/web/src/api/module_system/auth.ts:25-31` 直接发字符串（axios 对字符串走 `stringifySafely` → `JSON.stringify`），是可用参照 |
| 验证 | 用真实 axios（`web/node_modules/axios`）跑出 Web 端 body，与 App 修复后的 body 逐字节比较：**完全相同**，均为 `"eyJ…"`；修复前的对象形态为 `{"refresh_token":"eyJ…"}`，`JSON.parse` 得 Object → `Body(str)` 必然 422 |

### 修复 3 — APP-02 头像上传路径缺 `/common`，且绕过统一 http 层

| 项 | 内容 |
|---|---|
| 文件:行号（改后） | `frontend/app/src/api/module_system/user.ts:37-39`（路径改为 `/common/file/upload?upload_type=avatar`，返回类型改为 `UniApp.UploadFileSuccessCallbackResult`）；`frontend/app/src/subPages/module_system/profile/index.vue:36-58`（新增 `uploadAvatar: UploadMethod`），模板接线 `:179` `:upload-method="uploadAvatar"`（原 `:action` / `:header` 已删除）；`:2` 引入 `UploadMethod` 类型 |
| 改法 | 用 `wd-upload` 的 `upload-method` 钩子把上传交给 `UserAPI.uploadCurrentUserAvatar`（即统一 http 层，alova 适配器 `requestType: 'upload'`）。页面不再自拼 `VITE_API_BASE_URL + VITE_APP_BASE_API`、不再手工设 `Authorization`；请求头由 `http/adapters/alova.ts` 的 `beforeRequest` 注入 |
| 依据 | 后端 `backend/app/modules/common/file/controller.py:18-31`：路由挂载在 `/common` 下（`backend/app/api/v1/routers.py:63`），`upload_type` 是 Query、文件字段名 `file`，并要求 `module_common:file:upload` 权限 → 必须带令牌；`@alova/adapter-uniapp` 对 `requestType: 'upload'` 会把 `filePath`/`name` 作为文件字段、其余键作为 formData，并把 `header` 交给 `uni.uploadFile`（已读 `node_modules/@alova/adapter-uniapp/dist/alova-adapter-uniapp.esm.js` 确认） |
| 验证 | `pnpm run build:h5` → exit 0；产物中命中 `FO.Post("/common/file/upload?upload_type=avatar"`（`http.Post` 经压缩后的名字），且 `grep -E "['\"\`]/file/upload" dist/build/h5` **无任何输出**（不存在裸 `/file/upload`）；`eslint` 对改动文件 0 error |

### 修复 4 — APP-03 生产 WebSocket 指向 localhost

| 项 | 内容 |
|---|---|
| 文件:行号（改后） | `frontend/app/.env.production:25`：`VITE_APP_WS_ENDPOINT=ws://localhost:5180/ws` → `wss://service.fastapiadmin.com`（并把"只填基址、路径由代码拼接"写进注释） |
| 依据 | 消费点 `frontend/app/src/composables/useAiChat.ts:18-25` 的拼接是 `{VITE_APP_WS_ENDPOINT}{VITE_APP_BASE_API}/ai/chat/ws`，因此变量只能是**基址**，旧值多带了 `/ws` 又指向 localhost；后端 WS 路由确认在 `backend/app/modules/ai/chat/controller.py:194`（`@ChatRouter.websocket("/ws")` + `/ai` + `/chat` → `/api/v1/ai/chat/ws`）。站点为 HTTPS，`ws://` 会被浏览器/小程序拦截，故用 `wss://` |
| 验证 | `pnpm run build:h5` 产物中 `wss://service.fastapiadmin.com` 命中 1 个文件（`assets/subPages-module_ai-chat-index.*.js`）；`grep -rl "localhost:5180" dist/` = **0** 个文件 |

### 修复 5 — APP-04 开发环境直连生产后端

| 项 | 内容 |
|---|---|
| 文件:行号（改后） | `frontend/app/.env.development:7`：`https://service.fastapiadmin.com` → `http://127.0.0.1:8001`；同文件 `:26` `VITE_APP_WS_ENDPOINT` 由 `wss://service.fastapiadmin.com` 改为 `ws://127.0.0.1:8001`（同类缺陷：dev 构建连生产 WS） |
| 依据 | 与 `frontend/web/.env.development` 的 `VITE_API_BASE_URL = http://127.0.0.1:8001` 保持同一策略（Web 端该文件不入库、只提交 `.example`，本条使 App 的开发指向与之一致）。`frontend/app/.env.development` 本身**已被 git 跟踪**，之前默认把本地调试打到线上库 |
| 验证 | `pnpm run build:h5` 产物中 `localhost:8001` / `127.0.0.1:8001` 命中 0（生产构建读 `.env.production`，符合预期）；`type-check` exit 0。**未做运行时联调**（本轮未起服务），需本地起后端后确认 127.0.0.1:8001 可达 |
| 注意 | 本次只改地址、未写入任何密钥；`.env.production` 的 `VITE_API_BASE_URL` 保持生产域名不变 |

### 本轮修复的验证命令汇总

| 命令 | 结果 |
|---|---|
| `cd frontend/web && pnpm run type-check` | exit 0，无输出 |
| `cd frontend/app && pnpm run type-check` | exit 0，无输出 |
| `cd frontend/web && pnpm run build:prod` | exit 0，30s 级完成 |
| `cd frontend/app && pnpm run build:h5` | exit 0（仅 Sass `@import` 弃用告警与 unocss 图标告警，均为既有问题） |
| `cd frontend/web && grep -rc "console\." dist/js \| awk -F: '{s+=$2} END {print "console 出现次数:", s+0}'` | **5**（非 0，逐条分类见下） |
| `cd frontend/app && node_modules/.bin/eslint <4 个改动文件>` | exit 0 |
| `cd frontend/web && node_modules/.bin/eslint vite.config.ts` | exit 0 |

**关于 `console 出现次数: 5`（未达到 0 的原因，逐条核查）**：这 5 处**没有一处是可执行的 console 调用**：

| # | 产物 | 形态 | 说明 |
|---|---|---|---|
| 1 | `index.D0MzHYyR.js` | **字符串字面量** | 教程页展示给用户的示例代码块 `console.log('编辑器内容:', html)`（`views/fastlink/tutorial/index.vue` 的文档内容） |
| 2 | `wangeditor.*.js` | **英文提示字符串** | `… output logs to console. Ignoring \`debug: true\` …`，第三方库的告警文案 |
| 3 | `echarts.*.js` | **非调用引用** | `"undefined"!=typeof console&&console.warn&&console.log;` —— 值被丢弃的特性检测表达式 |
| 4 | `async-validator.*.js` | **非调用引用** | `catch(p){console.error,f.suppressValidatorError\|\|setTimeout(…)}` —— `console.error` 作裸引用参与逗号表达式 |
| 5 | `exceljs.*.js` | **非调用引用** | `"undefined"==typeof console\|\|console.error` 与 `"object"==typeof console&&console.warn` |

terser 的 `drop_console` 只删除 **调用语句**，不会修改第三方库里"把 `console.x` 当值用"的守卫表达式；若强行清零需开启 `compress.unsafe`（会改变其他压缩语义，风险大于收益）或改动第三方/用户可见文案，**故未做**。

**第一方源码 console 已被彻底剥离**（决定性证据：以下 9 个只出现在 `console.*` 参数里的特征串在产物中全部为 0 个文件）：
`路由已注册`、`[路由配置]`、`[MenuProcessor]`、`[IframeRouteManager]`、`[HTTP Error]`、`[路由守卫]`、`[Download]`、`网络请求失败`、`接口请求失败` — 覆盖 `router/`、`utils/http`、`utils/download`、`stores` 等模块。

### 修复过程中新发现（本轮**未**改，建议后续项）

- `frontend/app/src/http/adapters/alova.ts:115-119`：默认请求头写的是 `ContentType: ...`（**缺连字符**，不是 `Content-Type`），因此所有 App 请求实际没有显式 Content-Type，靠平台默认值（`application/json`）工作。修正它会波及全部请求，尤其可能覆盖 `uni.uploadFile` 自动生成的 multipart 边界从而**打破刚修好的上传**，故本轮不动，建议单独一轮处理并回归上传/登录/JSON 三类请求。

