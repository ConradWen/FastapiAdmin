# FastapiAdmin 前端 UX/UI 审计报告（Web + 移动端）

- 审计轮次：摸底审计第 1 轮（**只读，未修改任何仓库文件**，本报告为唯一新增文件）
- 审计对象：`frontend/web`（Vue3 + Vite + TS + Element Plus 2.14.3 + Tailwind v4 + Pinia）、`frontend/app`（uni-app + wot-ui + UnoCSS presetWot）、`frontend/docs`（VitePress）
- 需求基准：`REQUIREMENTS.md`
- 审计方式：静态代码证据（grep / AST 级脚本统计 / 依赖包类型定义核对 / 后端模型注释交叉验证）
- 未执行：未启动 dev server、未安装依赖、未截图、未上真机。所有需运行期或设备才能确认的项均归入第 8 节「需人工/真机验证清单」，**不计为缺陷**。

---

## 1. 结论摘要

| 维度 | Web | 移动端 | 结论 |
|---|---|---|---|
| 状态设计完整性 | 加载/骨架/空态/二次确认**齐全**；**错误态与重试入口系统性缺失** | 骨架/空态/下拉刷新/二次确认齐全；错误态缺失，且失败被误渲染为「不存在」 | 两端共同短板是**错误态** |
| 交互一致性 | 分页+搜索+批量+导入导出 | 触底加载+搜索+筛选 Tab，无批量/导出 | 差异多为平台合理差异，但**确认机制与状态色语义**真不一致 |
| 可访问性 | 76 处可点击元素无键盘可达性；表单无 label；图标按钮无替代文本 | 0 个 aria 属性（原生端可访问性依赖系统 TalkBack/VoiceOver） | Web 侧问题可静态证明 |
| 设计体系一致性 | **236 处硬编码色值散落在 50 个业务文件**，绕过动态主题令牌 | 81 处 / 11 文件（其中 44 处集中在 3 个登录类页面）；共享组件基本走令牌 | Web 偏离显著重于移动端 |
| 文案与术语一致性 | **101 个 views 文件中 85 个完全不含 i18n**；1063 处硬编码中文 | 14 个页面 **100% 走 i18n** | 两端 i18n 纪律差距最大 |

**最高优先级 4 项（P1）**：P1-1 通知状态枚举两端语义冲突、P1-2 Web i18n 近乎未落地、P1-3 列表页无错误态/重试、P1-4 移动端把接口失败渲染成「不存在」。

**先要说清的口径修正**：任务背景描述「Web 端 … + uno.config.ts」与事实不符。`uno.config.ts` 只存在于 `frontend/app/uno.config.ts`（UnoCSS + `@wot-ui/unocss-preset`）；Web 端使用的是 **Tailwind v4**（`frontend/web/src/styles/tailwind.css` 的 `@theme` 块，`package.json` 依赖 `@tailwindcss/vite` + `tailwindcss@^4.3.0`，无 unocss 依赖）。因此「设计令牌」在两端是**两套独立体系**，Web 侧令牌载体是 `@theme` + `:root`/`.dark` CSS 变量，移动端是 `presetWot` + `theme.json` + `uni.scss`。

---

## 2. 可验证问题清单

级别定义：**P1 高**（用户可见的错误信息 / 无法完成的交互 / 数据语义错误）；**P2 中**（一致性或可访问性缺陷，影响部分用户或造成理解成本）；**P3 低**（维护性与体验打磨）。

### 2.1 P1 — 高

#### P1-1 通知公告 `status` 枚举在 Web 端与后端/移动端语义冲突（数据被错误呈现）

- **现象**：同一后端字段 `status`，三处定义不一致：

| 来源 | 取值语义 | 证据 |
|---|---|---|
| 后端模型（权威） | `0:草稿 1:已发布 2:已归档` | `backend/app/modules/system/notice/model.py:16` |
| 移动端 | `0:草稿 1:已发布 2:已归档` | `frontend/app/src/subPages/module_system/notices/index.vue:25-27`、`:31` |
| **Web** | `0:启用 1:停用`（**缺 2**） | `frontend/web/src/views/module_system/notice/index.vue:188-191`、`:254`、`:403-404` |

- **影响**：
  1. 状态为 `2`（已归档）的公告，在 Web 列表里落到 `resolveTagText` 的兜底分支，渲染为**灰色标签 + 原始数字「2」**（`frontend/web/src/components/display/fa-descriptions/index.vue:64-72`）；搜索栏的「状态」下拉也只有 0/1 两项（`:226`），**无法筛选已归档公告**。
  2. 状态 `0/1` 的语义在 Web 被标成「启用/停用」而非「草稿/已发布」，审核流程判断会被误导。
- **建议**：以 `backend/app/modules/system/notice/model.py` 的注释为单一真值，Web 端 `STATUS_OPTIONS`/列 map/详情 map（`:188-191`、`:254`、`:403-404`）补 `2:已归档` 并改为 `0:草稿 1:已发布 2:已归档`；两端共用一份枚举常量。**这是本轮唯一发现的数据语义级错误，建议优先核对是否已有线上影响。**

#### P1-2 Web 端 i18n 近乎未落地（切英文后业务界面仍为中文）

- **现象**：
  - `frontend/web/src/views/**/*.vue` 共 **101** 个文件，其中 **85 个（84%）完全不含 `$t(` / `useI18n`**。
  - `<template>` 内硬编码中文字符共 **1063 处**，分布在 **87 个 .vue 文件**（统计口径见第 9 节；已剔除 HTML 注释）。TOP 文件：`views/fastlink/tutorial/index.vue`(1114 字符)、`views/module_task/storage/browse/index.vue`(480)、`views/module_generator/gencode/components/FaGenBasicStep.vue`(324)、`components/others/fa-cron/index.vue`(215)。
  - 高频硬编码位置类型：文本节点 638、`label` 201、`placeholder` 89、`title` 56、`description` 22、`content` 22。
- **对照事实（说明这是纪律问题而非能力问题）**：移动端 14 个页面 **0 个**缺 i18n；模板内硬编码中文仅 `frontend/app/src/components/PrivacyPopup.vue` 1 个文件 4 字符（且为微信小程序隐私协议默认值，属合理豁免）。两端 locale 键的 zh/en **完全对齐**（Web 509/509，移动端 331/331，无缺失键），Web 的 `locales/index.ts` 也完整可用。
- **影响**：Web 端语言切换器形同虚设；英文用户在所有业务页（用户/角色/菜单/字典/工单/存储/定时任务/代码生成…）看到中文。
- **建议**：分批治理，优先共享组件与系统模块。共享组件是放大器，先修 `frontend/web/src/components/tables/fa-table/index.vue:230`、`fa-table-header-left/index.vue`、`hooks/core/useConfirm.ts`、`hooks/core/useChart.ts:495`、`modal/fa-export-dialog/index.vue`、`modal/fa-import-dialog/index.vue`、`others/fa-cron/index.vue`。

#### P1-3 列表页系统性缺失「错误态 + 重试入口」，失败被降级为「暂无数据」

- **现象（Web）**：`hooks/core/useTable.ts` 已维护 `loadingState: "idle"|"loading"|"success"|"error"` 与 `error` ref（`:203-208`、`:463-468`），但 **16 个使用 `useTable` 的页面无一读取 `error`**（`grep -rn "error," --include="*.vue" views/` 无命中）。全仓仅 1 处渲染持久错误条：`views/module_ai/chat/components/FaChatMessages.vue:12`。页面普遍写成：

```ts
} catch {
  // ignore      ← frontend/web/src/views/module_system/ticket/index.vue:516-518
}
```

  由于 `utils/http/index.ts` 只在拦截器里弹一次 `ElMessage.error`，用户看到的是「一个会消失的 toast + 一张写着『暂无数据』的空表」，**无法区分「本来没数据」与「加载失败」**，也没有重试按钮。
- **典型受害页面**：
  - `frontend/web/src/views/module_monitor/server/index.vue:214-221`：`catch { /* 静默忽略错误 */ }`，且 `server` 保持全 0 初值 → 接口失败时页面显示 **CPU 0% / 内存 0% / 磁盘表空**，看起来像「服务器空闲」，**无任何异常指示、无重试**。
  - `frontend/web/src/views/module_system/params/index.vue:433-438`：`onMounted` 内 `await configStore.getConfig()`，无加载态、无失败分支；加载期间 `fieldsMap` 为空 → 左侧 Tab 全空白，用户以为页面坏了。
  - `frontend/web/src/views/module_system/ticket/index.vue:877-880`：评论加载失败仅 `// ignore`，评论区显示为空，用户以为「没有评论」。
  - `frontend/web/src/views/module_ai/chat/components/FaChatInput.vue:176-178`：模型列表加载 `catch { /* 静默失败 */ }`，模型下拉静默变空。
- **现象（移动端）**：`frontend/app/src/composables/useListPage.ts:31,57` 同样暴露了 `error`，但 `subPages/module_system/tickets/index.vue:82-90` 与 `notices/index.vue:33-36` 都只写了 `onError: () => toast.error(t('common.loadFailed'))`，未消费 `error` 做 UI。
- **建议**：为 `FaTable` 增加 `error`/`@retry` 两个 prop（放在 `frontend/web/src/components/tables/fa-table/index.vue`，一次修复覆盖 23 个消费页），`FaTable` 内 `v-if="error"` 渲染 `ElResult` + 重试按钮，`empty` 槽位仅在 `!error` 时启用；移动端在 `SkeletonPage` 旁增加 `ErrorState` 组件并在 `useListPage.onError` 中置位。

#### P1-4 移动端把「接口失败」渲染为「不存在 / 空资料」

- **现象**：
  - `frontend/app/src/subPages/module_system/ticket-detail/index.vue:38-46` 加载失败 → `ticket` 仍为 `null`；模板 `:244` 的 `wd-empty v-else :tip="t('ticketDetail.notFound')"` 命中的是**「工单不存在或已删除」**。网络抖动会让用户以为工单被删了。
  - 同文件 `:55-60`：`loadComments` 失败只 `console.error`，**连 toast 都没有**（`finally` 也不复位任何可见状态）。
  - `frontend/app/src/subPages/module_system/profile/index.vue:38-45`：失败后 `userProfile` 为 `null`，而模板 `:141` 的骨架条件 `v-if="loading && !userProfile"` 不再成立 → 直接进入 `v-else`，渲染**满屏 `-` 占位**（`deptText`/`roleText` 兜底 `'-'`，`:29-33`），无错误提示、无重试。
  - `frontend/app/src/pages/index/index.vue:270-286`：`Promise.allSettled` + `catch { /* silent */ }`，失败时统计卡显示 `-`，无错误态与重试。
- **建议**：`ticket-detail` 增加 `loadError` 状态区分「失败」与「不存在」；`profile` 增加错误分支（骨架条件改为 `v-if="loading"`，`v-else-if="loadError"` 渲染错误态）；`index` 增加错误态与重试。

### 2.2 P2 — 中

#### P2-1 Web `module_monitor/cache` 页面完全没有加载反馈（`:loading` 是无效属性）

- **现象**：`frontend/web/src/views/module_monitor/cache/index.vue:116` 与 `:179` 写作 `<ElTable :loading="loading">` / `:loading="subLoading"`。经核对 Element Plus 2.14.3 类型定义，`TableProps` 共 49 个 prop，**不含 `loading`**（`node_modules/element-plus/es/components/table/src/table/defaults.d.ts`；该文件中的 `loading?: boolean` 属于 `TreeNode` 接口，是树形懒加载字段，与表格加载态无关）。渲染层 `table.mjs` 也不读取 `loading`。
- **佐证**：`loading`/`subLoading` 两个 ref 被完整维护（`:321,328,346,354,371,385,409,417`）却无任何消费者，属明显的「以为设了加载态」。
- **影响**：该页两个表格在请求期间**无任何反馈**，用户会重复点击「清理全部缓存」（危险操作）。
- **建议**：改为 `v-loading="loading"`，或整体换用 `FaTable`。

#### P2-2 Web 键盘可达性：76 处可点击元素既无 `tabindex` 也无 `role`

- **现象**：全仓 `@click` 挂载在 `<div>/<span>/<li>/<td>` 上、且同一标签内无 `tabindex` / `role=` / `@key*` 的共 **76 处**（`layouts/` 31、`views/` 24、`components/` 21）。而全仓实现正确模式（`role="button"` + `tabindex="0"` + `@keydown.enter`）的仅 **3 处**：`components/tables/fa-table-header/index.vue:189-196`（已封装成 `useToolButtonAttrs`）、`views/module_system/user/components/FaDeptTree.vue:21-25`、`views/module_ai/chat/components/FaWelcomeScreen.vue:14-21`。
- **确定性样例（顶级控件，非菜单项，鼠标之外无可达路径）**：
  - `frontend/web/src/components/base/fa-back-to-top/index.vue:11-17` — 返回顶部按钮（`<div @click>`）。
  - `frontend/web/src/layouts/fa-settings-panel/widgets/FaSettingHeader.vue:4-8` — 设置面板关闭按钮。
  - `frontend/web/src/layouts/fa-header-bar/index.vue:73-79` — 顶栏全局搜索触发器。
  - `frontend/web/src/layouts/fa-header-bar/index.vue:21` — Logo 回首页。
  - `frontend/web/src/components/cards/fa-image-card/index.vue:3` — 整卡可点击。
  - `frontend/web/src/components/forms/fa-search-bar/index.vue:143` — 展开/收起筛选开关。
  - `frontend/web/src/components/tables/fa-table-select/index.vue:11`、`components/others/fa-icon-select/index.vue:6` — 弹层触发器。
  - `frontend/web/src/components/banners/fa-basic-banner/index.vue:39`、`components/banners/fa-card-banner/index.vue:13,24` — Banner 按钮。
- **对比正向样例**：`frontend/web/src/views/dashboard/home/modules/quick-links.vue:33-40` 用原生 `<button type="button">` + `:aria-label` 实现卡片删除，是本仓最规范写法。
- **建议**：把 `fa-table-header/index.vue:189-196` 的 `useToolButtonAttrs` 提升为 `hooks/core/useClickable.ts` 并全仓替换；或对纯装饰容器改用原生 `<button>` / `ElButton link`。

#### P2-3 Web 登录/注册/忘记密码表单没有 label（输入框无可访问名）

- **现象**：`ElFormItem` 只写了 `prop`，**没有 `label` 也没有 `#label` 插槽**，可访问名只能依赖 `placeholder`（输入后即消失，且不是 label 的合法替代）：
  - `frontend/web/src/views/module_system/auth/login/components/forms/FaLoginAccountForm.vue:31`（username）、`:45`（password）
  - `frontend/web/src/views/module_system/auth/login/components/panels/FaLoginRegisterPanel.vue:12,24,37,55`
  - `frontend/web/src/views/module_system/auth/login/components/panels/FaLoginForgetPanel.vue:12`
  - 同类还有 `views/module_generator/gencode/components/FaGenBasicStep.vue:107,128,139,157,200,219`、`views/module_system/role/components/FaPermissonDrawer.vue:35`、`components/others/fa-comment-widget/index.vue:4,12,21`、`components/modal/fa-import-dialog/index.vue:21`。
- **全仓统计**：`ElFormItem` 共 70 处，**27 处无 `label`**。
- **对照**：移动端统一使用 `wd-form-item :label="t(...)"`（如 `frontend/app/src/subPages/module_system/tickets/index.vue:259-279`），label 覆盖完整——**这是移动端做得比 Web 好的一处**。
- **建议**：登录/注册/忘记密码这类「极简设计」场景用 `label` 配 `label-position="top"` + `sr-only` 类，或至少补 `:aria-label`；`ElTooltip` 的 `content`（`:44`）不能替代表单 label。

#### P2-4 Web 图标按钮缺可访问名（含同一区域内不一致）

- **现象**：`ElButton` 内容仅为图标、且自身无 `aria-label`/`title` 的共 **12 处**（其中若干被 `el-tooltip` 包裹，见下方说明）：
  - `frontend/web/src/views/module_ai/chat/components/FaChatInput.vue:99-107` — **发送**按钮无任何名称；而紧邻的 `:88-95` 停止按钮写了 `title="停止生成"`。**同一行内的不自洽是最硬的证据。**
  - `frontend/web/src/views/module_ai/chat/components/FaAiModelConfigPanel.vue:125`（显示/隐藏 API Key）、`:132`（复制 Key）— 无 tooltip、无 aria-label。
  - `frontend/web/src/views/module_ai/chat/components/FaMessageItem.vue:16-23` — 复制消息按钮。
  - `frontend/web/src/components/actions/fa-copy-button/index.vue:3` — 通用复制组件（被复用，影响面放大）。
  - `frontend/web/src/views/module_task/storage/workflow/components/FaStorageNodePanel.vue:7`、`FaEdgeConfigPanel.vue:7` — 面板关闭按钮。
  - `frontend/web/src/components/others/fa-ai-assistant/index.vue:5` — 悬浮球。
- **说明（避免误判）**：`views/module_task/storage/browse/index.vue:41,46,113`、`FaAiModelConfigPanel.vue:92` 等同类按钮**已被 `el-tooltip` 包裹**，EP 会为触发器生成 `aria-describedby`；但「描述」不等于「名称」，屏幕阅读器读到的是空按钮 + 描述。是否可接受需人工验证（见第 8 节）。
- **建议**：统一补 `aria-label`；`fa-copy-button` 加 `ariaLabel` prop 并默认取 `t('common.copy')`。

#### P2-5 移动端错误文案未国际化（英文语言下全是中文）

- **现象**：`frontend/app/src/http/tools/enum.ts:53-80` 的 `ShowMessage()` 对 400/401/403/404/408/500/501/502/503… 全部返回**硬编码中文**（`'请求错误(400)'`、`'未授权，请重新登录(401)'`…）；`frontend/app/src/http/adapters/alova.ts:19`（`` `HTTP请求错误[${statusCode}]` ``）、`:142`、`:165`、`:176`（`'网络错误，请检查您的网络连接'`）、`:178`（`'请求超时，请重试'`）、`:180`、`:189` 同样硬编码。
- **影响**：移动端虽然页面文案 100% i18n，但**所有网络/服务端错误的提示语仍是中文**——这是最容易被漏掉的一层（它在 `.ts` 里，不在 `<template>` 里，常规 i18n 检查扫不到）。
- **Web 侧同类**：`frontend/web/src/utils/http/index.ts:273`（`"服务器连接失败，请检查后端服务是否正常运行"`）、`:277`（`"网络连接错误，请检查您的网络设置"`）为硬编码中文；其余分支已正确使用 `$t("httpMsg.*")`，且 `httpMsg` 键在 zh/en 中均存在。
- **建议**：两端 HTTP 层的错误文案统一改走 i18n（`httpMsg.status.400` 等），移动端补 10 个 `httpMsg` 键。

#### P2-6 移动端危险操作确认机制不统一（原生 `uni.showModal` vs wot `wd-dialog`）

- **现象**：同一类「确认后执行破坏性操作」，两种实现并存：
  - 原生 `uni.showModal`（不可主题化；H5 下退化为浏览器原生 dialog，样式与 App 内其他弹窗割裂）：`frontend/app/src/subPages/module_system/tickets/index.vue:154`、`subPages/module_ai/chat/index.vue:107`、`subPages/module_ai/ai-models/index.vue:106,123`、`composables/useSubscribeMessage.ts:116`、`components/GlobalMessage.vue:13`。
  - wot `wd-dialog`（经 `useGlobalDialog`，与设计体系一致）：`frontend/app/src/subPages/setting/index.vue:93`、`pages/mine/index.vue:38`。
- **建议**：统一收敛到 `globalDialog.confirm`，`useSubscribeMessage.ts` 的系统级订阅弹窗可保留原生。

#### P2-7 空态无法区分「筛选无结果」与「本来为空」

- **现象**：
  - Web：`FaTable`（`frontend/web/src/components/tables/fa-table/index.vue:230`）、`FaCardList`（`components/cards/fa-card-list/index.vue:51`）、`FaCardGrid`（`components/cards/fa-card-grid/index.vue:141`）、图表（`hooks/core/useChart.ts:495`）的空态文案**固定为「暂无数据」**，无「筛选无结果」变体。除 `views/module_system/ticket/index.vue:53` 传了 `empty-text="暂无工单"` 外，无页面覆盖。
  - Web locale（509 键）中**不存在任何通用空态键**（`empty`/`noData` 类仅命中 `notice.empty`、`common.delNoData`、`httpMsg.notFound`）。移动端有 **10 个**专用空态键并已区分两种语义（`common.noMore`、`tickets.empty`/`tickets.emptyWithFilter`、`notices.empty`/`emptyWithFilter`、`chat.empty`、`aiModels.empty`、`ticketDetail.emptyComments`、`ticketDetail.notFound`、`work.emptyTip`），实现见 `frontend/app/src/subPages/module_system/tickets/index.vue:215`。
- **建议**：Web 补 `table.empty` / `table.emptyFiltered`，`FaTable` 接收 `hasFilter` 或 `filtered` 标记后切换文案。

#### P2-8 同一后端枚举的**状态色**两端不一致；「启用/停用」词形也不一致

- **现象（颜色，标签文字一致、颜色不一致）**：工单 `status`，Web 用 `statusTagType`（`frontend/web/src/views/module_system/ticket/index.vue:608-613`）：`0→warning(橙)`、`1→info(灰)`、`2→success(绿)`、`3→info(灰)`；移动端用 `StatusBadge`（`frontend/app/src/components/StatusBadge.vue:33-36`）：`0 pending→draft(灰)`、`1 processing→primary(蓝)`、`2 completed→enabled(绿)`、`3 closed→disabled(灰)`。即**「处理中」在 Web 是灰、在移动端是蓝；「待处理」在 Web 是橙、在移动端是灰**。
- **现象（词形）**：Web 系统模块统一用「**启用/停用**」（`views/module_system/user/index.vue:457-458`、`role/index.vue:318-319`、`position/index.vue:224-225` 等，共 73 处字面量），移动端 `common.status.disabled` = 「**禁用**」（`frontend/app/src/locales/langs/zh.json`）。
- **现象（术语，同一实体三种叫法）**：同一条公告，Web 业务页叫「**公告通知**」（`views/module_system/notice/index.vue:275-278`、`:304`、`:203`），Web 顶栏通知区叫「**通知**」（locale `notice.title`），移动端叫「**通知公告**」（locale `notices.title`、`pages.json:152`）。
- **建议**：以「后端 comment 文字」为唯一词表来源，抽 `constants/status.ts` 供两端共用；状态色按语义（进行中=主色蓝、待处理=警示橙、完成=成功绿、终止=中性灰）统一。

#### P2-9 移动端主题令牌存在四份互相冲突的定义

- **现象**：同一份「主题色 → 背景色」值被声明了 4 次，且暗色值互相矛盾：

| 位置 | 内容 | 证据 |
|---|---|---|
| SCSS 变量层 | `--drop-base-a/-c` 等 6 主题色 | `frontend/app/src/styles/theme.scss:16-21,45-49,65-69,85-89,105-109,125-129` |
| Pinia store | `THEME_NAV_BG`（同 6 值） | `frontend/app/src/store/themeStore.ts:13-20` |
| 根组件 | `THEME_PAGE_BG`（同 6 值） | `frontend/app/src/App.ku.vue:9-14` |
| 原生主题文件 | `theme.json`（仅 blue + dark） | `frontend/app/src/theme.json`（经 `manifest.config.ts:74,93` 的 `themeLocation` 生效） |

  逐值核对：`themeStore.THEME_NAV_BG` 的 6 个值与 `theme.scss --drop-base-a` **完全一致**；`App.ku.THEME_PAGE_BG` 的 6 个值与 `--drop-base-c` **完全一致**。
- **冲突点**：`theme.json` 的 `dark.bgColor = #000`、`dark.navBgColor = #000000`，而运行时实际使用的是 `#272B3B`（`store/themeStore.ts:76`、`App.ku.vue:23`；该值与 wot 令牌 `--wot-coolgrey-9: #272B3BFF` 一致，见 `node_modules/@wot-ui/ui/styles/theme/base/color.scss:160`、`theme/dark.scss:60`）。
- **影响**：深色模式下原生窗口背景（由 `theme.json` 决定）与 App 页面背景（`#272B3B`）不是同一个颜色 → 冷启动/下拉回弹时可能出现可见色差或闪烁。（静态可证「值不一致」；**视觉表现需真机确认**，见第 8 节。）
- **建议**：`theme.scss` 作为唯一真值源，`themeStore`/`App.ku.vue` 改读 CSS 变量或从同一常量模块导入；`theme.json` 的 dark 值改为与 `--wot-filled-content` 对齐。

#### P2-10 Web 组件与视图大量硬编码 Element Plus 默认调色板，绕过动态主题色

- **现象**：`#409eff`（EP 默认主色，非项目 `--theme-color`/`$fa-primary:#4080ff`）出现 6 次；EP 默认语义色 `#909399`(16)、`#e6a23c`(5)、`#f56c6c`(1)、`#c0c4cc`(4)、`#67c23a`(1)、`#606266`、`#f5f7fa` 等贯穿业务代码。项目明明提供了 `--el-text-color-*`/`--el-color-*`/`--fa-gray-*` 令牌（`frontend/web/src/styles/tailwind.css:215-232`）。
- **暗色模式受害样例**（这些浅色专用灰**不会**随 `.dark` 切换，属可静态证明的对比度风险）：`frontend/web/src/views/module_task/storage/browse/index.vue:88,213,233,260,275,284,289,348,433,444,471,476,492,514,1685`；`views/module_generator/gencode/components/FaGenPreviewStep.vue:16,22`；`views/module_task/storage/workflow/index.vue:99`。
- **完整分布统计见第 6 节。**

#### P2-11 Web 字号/圆角绕过令牌（含不受用户设置影响的固定圆角）

- **现象**：
  - Tailwind `@theme` 已定义字号 5 档 `--font-size-xs..xl` = 11/12/13/15/18px（`frontend/web/src/styles/tailwind.css:56-62`），但仍有 **33 处任意值 class**：`text-[13px]`×15、`text-[10px]`×7、`text-[14px]`×6、`text-[11px]`×6、`text-[19px]`×3、`text-[16px]`×2、`text-[18px]`、`text-[12px]`；`<style>` 内另有 `font-size: 12px`×32、`14px`×30、`13px`×25、`16px`×13、`11px`×7。
  - 项目提供了 `rounded-custom-xs/sm`（`tailwind.css:66-72`）与 `--custom-radius`（用户在设置面板可调，影响 20+ 处 calc 表达式），但仍有 **17 处 `border-radius: 6px`、14 处 `8px`、13 处 `4px`** 固定值 → **用户调圆角时这些元素不变**。样例：`components/skeleton/fa-dashboard-skeleton/index.vue:229`、`layouts/fa-work-tab/index.vue:909,970`、`layouts/fa-menus/fa-sidebar-menu/index.vue:633`、`views/module_ai/chat/components/FaMessageItem.vue:138,150,201`、`views/module_task/storage/workflow/components/FaWorkflowDesignDrawer.vue:901`。
  - 间距硬编码（`<style>` 内 `padding/margin/gap: Npx`，共 231 处）：`8px`×61、`12px`×31、`16px`×28、`4px`×19、`6px`×18、`10px`×17。
- **建议**：`@theme` 补 `--font-size-md:14px` 等实际在用档位；`rounded-6/8` 等封装为走 `--custom-radius` 的工具类；对 `text-[Npx]` 用 stylelint 自定义规则（`declaration-property-value-disallowed-list` 已有 stylelint 基建，`frontend/web/package.json` 的 `lint:stylelint`）拦截新增。

#### P2-12 文档站 zh/en 术语与正文范围不对齐

- **现象**：VitePress 侧边栏同一份文档，中文标签为「**移动端开发指南**」，英文为「**Miniprogram Development Guide**」（`frontend/docs/.vitepress/config.mts` 的 `zhGuideSidebar` / `enGuideSidebar`）；正文页标题同样中英不等（`frontend/docs/src/guide/miniprogram.md:4` = 「FastApp 移动端开发指南」 vs `frontend/docs/src/en/guide/miniprogram.md:4` = 「Miniprogram Development Guide」），而正文同时覆盖 **H5 / 微信·支付宝小程序 / iOS·Android**。英文标签把 App 端排除了。
- **正向事实**：docs 中英文件数 1:1（`guide/` 与 `en/guide/` 均为 9 个 .md），无缺页。
- **建议**：英文标签改为 "Mobile Development Guide"，与 App 端 `README` 中 "mobile application" 的用词对齐。

### 2.3 P3 — 低

| ID | 现象 | 文件:行号 | 建议 |
|---|---|---|---|
| P3-1 | `useConfirm` 的确认框标题/按钮文案硬编码中文，绕过 locales | `frontend/web/src/hooks/core/useConfirm.ts:8,17,30,38` | 改走 `t()`；`common.confirm/cancel/tips` 键已存在 |
| P3-2 | 破坏性操作确认框标题词表不统一（「警告」「提示」「批量删除」「危险！」「确认清空」「同步差异预览」），且部分走 `t()` 部分硬编码 | `useConfirm.ts:9,21,30`、`views/module_task/storage/browse/index.vue:1322`、`views/module_monitor/cache/index.vue:391`、`views/module_system/ticket/index.vue:799`、`views/module_ai/chat/index.vue:328` | 统一 `useConfirm` 出口与标题键（`type` 已统一为 `warning`，无需改） |
| P3-3 | 空态「暂无数据」硬编码在 10 个位置（含 3 个共享组件），无法随语言切换 | `components/tables/fa-table/index.vue:230`、`components/cards/fa-card-list/index.vue:51`、`fa-card-grid/index.vue:141`、`hooks/core/useChart.ts:495`、`views/module_monitor/cache/index.vue:118,185`、`views/module_monitor/server/index.vue:163`、`views/module_generator/gencode/components/FaGenColumnsStep.vue:87`、`FaImportDbTableDialog.vue:49`、`views/module_system/user/components/FaDeptTree.vue:47`、`views/module_task/cronjob/job/index.vue:151` | 随 P2-7 一并治理 |
| P3-4 | `fa-table-v2` 为死代码：53 行、无任何消费方（`grep -rn "FaTableV2\|fa-table-v2"` 在组件目录外 0 命中），且未实现 loading/empty | `frontend/web/src/components/tables/fa-table-v2/index.vue` | 删除或补齐状态并与 `FaTable` 收敛 |
| P3-5 | 移动端 `GlobalLoading.vue`、`GlobalMessage.vue` 实际未用于任何页面（仅其自身 composable 引用，`grep` `useGlobalLoading(`/`useGlobalMessage(` 无业务命中） | `frontend/app/src/components/GlobalLoading.vue`、`GlobalMessage.vue` | 确认后删除，或接入使用 |
| P3-6 | 死样式：`.el-dropdown-selfdefine` 是 Element Plus 遗留类，EP 2.14.3 的 JS 在 `node_modules/element-plus/es/**` 中**不产出**该 class（仅 theme-chalk CSS 残留），本条覆盖规则永不生效 | `frontend/web/src/styles/element-plus/_overrides.scss:273-275` | 删除；焦点可见性依赖 EP 自身实现（`:465-469` 已有 `.el-tooltip__trigger:focus-visible` 正例） |
| P3-7 | 移动端工单页把表单提交 loading 与列表 loading 复用同一个 ref | `frontend/app/src/subPages/module_system/tickets/index.vue:135,151`（配合 `:212`、`:245`、`:285`） | 用独立 `submitting` ref（同仓 `ai-models/index.vue:226` 已是正确写法） |
| P3-8 | 移动端 `chat` 页内联样式 12 处硬编码 rpx/px，与同仓其它页面的 UnoCSS/wot 令牌写法不一致 | `frontend/app/src/subPages/module_ai/chat/index.vue:207,218,247,252,275,276,283` 等 | 抽成 UnoCSS class 或 `styles/` 下的具名类 |
| P3-9 | 移动端页面导航标题中文常量与 i18n 双真值源：`pages.json` 17 处 + `definePage` 13 处为中文常量，靠 `useI18nNavTitle` 在 `onShow` 覆盖 | `frontend/app/src/pages.json:23,34,45,54,63,72,80,88,102,113,123,134,143,152,161,170`；`composables/useI18nNavTitle.ts` | 覆盖率已 100%（14/14 有标题的页面均已接入），仅存在首屏闪中文的可能 → 见第 8 节 |
| P3-10 | Web `dashboard/analysis`、`dashboard/workplace` 两个首页级页面**零**加载/骨架/错误处理（101 个 views 文件中仅这两处完全没有 `loading`/`Skeleton`/`ElEmpty`） | `frontend/web/src/views/dashboard/analysis/index.vue`、`views/dashboard/workplace/index.vue` | 复用 `FaDashboardSkeleton`（`views/dashboard/home/index.vue:3` 已有正例） |
| P3-11 | 系统模块「启用/停用」字面量在同一页面重复 3~4 次（`columns` 的 tag map、详情 map、搜索项、编辑项各写一遍），共 73 处 | `views/module_system/user/index.vue:395,457,491,623`；`role/index.vue:318,390,514,584`；`position/index.vue:224,295,371,473`；`notice/index.vue:189,254,403` | 抽 `constants/status.ts` 共享 map（同时解决 P2-8） |
| P3-12 | Web `<img>` 无 `alt` 5 处（24 个图片标签中 19 个有 alt） | `components/cards/fa-image-card/index.vue:6`、`actions/fa-upload/index.vue:47`、`layouts/fa-settings-panel/widgets/FaThemeSettings.vue:11`、`FaMenuStyleSettings.vue:17`、`FaMenuLayoutSettings.vue:12` | 先判定是否纯装饰；装饰图加 `alt=""`，其余补描述性 alt |
| P3-13 | 移动端 5 个 `<image>` 均无 `alt`（H5 构建下会渲染为无替代文本的 `<img>`） | `frontend/app/src/pages/login/index.vue:248,328,336,344,352` | 品牌 logo 加 `alt`；第三方图标可 `alt=""`（装饰） |

---

## 3. 状态设计完整性（逐页抽样）

图例：✅ 有 / ❌ 缺 / ➖ 不适用（非数据页）。「空态」对 Web 指 `FaTable`/`ElEmpty`（组件内建也算 ✅）。

### 3.1 Web 抽样（23 个页面使用 `FaTable`，16 个使用 `useTable`）

| 页面 | 加载/骨架 | 空态 | **错误态** | **重试** | 危险操作二次确认 | 关键行号 |
|---|---|---|---|---|---|---|
| `views/module_system/user/index.vue` | ✅ | ✅ | ❌ | ❌ | ✅ `confirmDelete`/`confirmBatchDelete` | `:554,915-922` |
| `views/module_system/role/index.vue` | ✅ | ✅ | ❌ | ❌ | ✅ | `:363,657` |
| `views/module_system/menu/index.vue` | ✅ | ✅ | ❌ | ❌ | ✅ | `:825,1281` |
| `views/module_system/dept/index.vue` | ✅ | ✅ | ❌ | ❌ | ✅ | `:272,526` |
| `views/module_system/dict/index.vue` (+`DictDataPanel`) | ✅ | ✅ | ❌ | ❌ | ✅ | `:440`、`DictDataPanel.vue:630` |
| `views/module_system/notice/index.vue` | ✅ | ✅ | ❌ | ❌ | ✅ | `:501,556` |
| `views/module_system/position/index.vue` | ✅ | ✅ | ❌ | ❌ | ✅ | `:514,528` |
| `views/module_system/log/index.vue` | ✅ | ✅ | ❌ | ❌ | ✅ | `:415,459,669,713` |
| `views/module_system/version/index.vue` | ✅ | ✅ | ❌ | ❌ | ✅ | `:490` |
| `views/module_system/ticket/index.vue` | ✅ | ✅ `暂无工单` | ❌ | ❌ | ✅ | 列表 `:516-518`；评论 `:877-880` ❌ |
| `views/module_example/demo/index.vue` | ✅ | ✅ | ❌ | ❌ | ✅ | `:636,649` |
| `views/module_ai/memory/index.vue` | ✅ | ✅ | ❌ | ❌ | ✅ | `:118,222` |
| `views/module_monitor/online/index.vue` | ✅ | ✅ | ❌ | ❌ | ✅ `强退所有` | `:123,256` |
| **`views/module_monitor/cache/index.vue`** | **❌ 无效 prop** | ✅ | ❌ | ⚠️ 仅 toast | ✅ | `:116,179`（见 P2-1） |
| **`views/module_monitor/server/index.vue`** | **❌** | ✅ 磁盘表 | **❌ 静默** | ❌ | ➖ | `:214-221` |
| **`views/module_system/params/index.vue`** | **❌** | ➖ | **❌** | ❌ | ➖（保存无确认，但有「已修改」标记） | `:433-438` |
| `views/module_task/cronjob/job/index.vue` | ✅ | ✅ | ❌ | ❌ | ✅ 含「关闭调度器」 | `:744,1005,1017,1085` |
| `views/module_task/cronjob/node/index.vue` | ✅ | ✅ | ❌ | ❌ | ✅ | `:382,491` |
| `views/module_task/storage/node/index.vue` | ✅ | ✅ | ❌ | ❌ | ✅ | `:445,962` |
| `views/module_task/storage/transfer/index.vue` | ✅ | ✅ | ⚠️ 空态文案含「加载失败」 | ❌ | ✅ | `:851,861`（取消/删除均有确认） |
| `views/module_task/storage/browse/index.vue` | ✅ | ✅ 区分「加载失败」/「该目录下没有内容」 | ⚠️ 文案级 | ❌ | ✅ | `:254`、`confirmAction:1320-1331`、`deleteRow:1333`、`batchDelete:1349` |
| `views/module_task/storage/workflow/index.vue` | ✅ | ✅ | ❌ | ❌ | ✅ | `:401,784`（含删除节点/连线确认） |
| `views/module_generator/gencode/index.vue` | ✅ | ✅ | ✅ **全仓唯一** | ✅ 保留了重试路径 | ✅ | `:667-668` |
| `views/dashboard/analysis/index.vue` / `workplace/index.vue` | ❌ | 仅图表内建空态 | ❌ | ❌ | ➖ | 见 P3-10 |

**Web 状态设计小结**：加载态 21/23 ✅、空态 22/23 ✅、**错误态 1/23 ✅**、**重试 1/23 ✅**、危险操作确认 100% ✅（含批量/关闭调度器/清理全部缓存/强退所有/删除工作流节点与连线）。
**Web 的「二次确认」是全仓质量最高的一环**，`hooks/core/useConfirm.ts` + `ElPopconfirm` 双轨覆盖到位；短板完全集中在错误态与重试。

### 3.2 移动端抽样

| 页面 | 骨架 | 空态 | **错误态** | **重试** | 二次确认 | 下拉刷新 | 触底加载 |
|---|---|---|---|---|---|---|---|
| `subPages/module_system/tickets/index.vue` | ✅ `:212` | ✅ 区分筛选 `:215` | ❌ 仅 toast `:89` | ❌ | ✅ `uni.showModal:154`（机制见 P2-6） | ✅ `:174` | ✅ `:170` |
| `subPages/module_system/notices/index.vue` | ✅ `:138` | ✅ 区分筛选 `:141` | ❌ 仅 toast `:35` | ❌ | ✅ `:101` | ✅ | ✅ `:163` |
| `subPages/module_system/ticket-detail/index.vue` | ✅ `:145` | ✅ `:220,244` | **❌ 失败→误显示「不存在」`:244`** | ❌ | ➖ | ✅ | 手动分页 `:237` |
| `subPages/module_system/profile/index.vue` | ⚠️ 仅首次 `:141` | **❌ 失败→满屏 `-`** | ❌ `:38-45` | ❌ | ➖ | ✅ | ➖ |
| `subPages/module_ai/ai-models/index.vue` | ✅ `:150` | ✅ `:153` | ❌ 仅 toast `:52` | ❌ | ✅ `uni.showModal:106,123` | ✅ | ➖（一次全量） |
| `subPages/module_ai/chat/index.vue` | ✅ `:226` | ✅ `:234` | ❌ 仅 toast `:67,101` | ❌ | ✅ `:107` | ➖ | ✅ |
| `pages/index/index.vue` | ✅ `:431` | ➖（`-` 占位） | ❌ 静默 `:270-286` | ❌ | ➖ | ✅ | ➖ |
| `subPages/setting/index.vue` | ➖ | ➖ | ➖ | ➖ | ✅ `wd-dialog:93` | ➖ | ➖ |
| `pages/mine/index.vue` | ✅ | ➖ | ➖ | ➖ | ✅ `:38`（退出登录） | ✅ | ➖ |
| `pages/work/index.vue` | ➖ | ✅ `:127` | ➖ | ➖ | ➖ | ➖ | ➖ |
| `pages/login/*`、`pages/login/register`、`pages/login/forget` | ➖ | ➖ | ✅ 滑块失败重置+toast `login/index.vue:141,147` | ⚠️ 需手动重滑 | ✅ 注册协议勾选 | ➖ | ➖ |

**移动端状态设计小结**：骨架/空态/下拉刷新/触底加载/表单校验覆盖良好，**错误态与重试同样是系统性缺口**，且比 Web 更严重的是**错误被渲染成「不存在」**（P1-4）。

### 3.3 表单校验提示（两端均 ✅）

- Web：`FaForm` + `rules`，例如 `views/module_system/user/index.vue:130`（`:rules="rules"`）配合 `:736`（`const rules = reactive({...})`）；`ElForm` 上挂 `@keyup.enter` 提交（`FaLoginAccountForm.vue:11`）。
- 移动端：`wd-form :schema` / `wd-form-item` + 手动校验，例如 `subPages/module_system/tickets/index.vue:131-134`（标题必填 toast）、`pages/mine/index.vue:98-102`（两次密码一致性）。
- 差异：Web 依赖 `trigger: "blur"` 的字段级即时提示；移动端多为**提交时**集中校验（如工单标题）。属平台习惯差异，**不算缺陷**，但同一表单两端提示时机不同，需在验收标准中明确。

---

## 4. Web 与移动端交互一致性（同操作对比）

| 操作 | Web | 移动端 | 判定 |
|---|---|---|---|
| 列表分页 | 页码分页 `FaPagination`（`components/tables/fa-pagination/index.vue:5`），23 个页面复用 | 触底无限加载 `useListPage.loadNext()` + `onReachBottom`（`tickets/index.vue:170-173`） | **合理差异**（平台习惯），但两端都需保证「到底提示」：移动端有 `common.noMore`（`:246`），Web 无等价提示 |
| 列表刷新 | `FaTableHeader` 刷新按钮（`refreshData`）+ 列显隐 | 下拉刷新 `enablePullDownRefresh` + `onPullDownRefresh` | **合理差异**；移动端未提供显式刷新按钮，Web 未提供下拉刷新（Web 有 `Ctrl+Enter` 搜索，见下） |
| 搜索 | `FaSearchBar` + 展开/收起 + 重置 + **Ctrl/Cmd+Enter 快捷搜索**（`components/forms/fa-search-bar/index.vue:199-205`，提示文案 `table.searchBar.searchTooltip`） | `wd-search` + 筛选 Tab + 下拉类型筛选（`tickets/index.vue:188-209`） | 能力对齐，`@clear="onReset"` 已覆盖清空。**建议**：移动端 `onReset`（`:108-112`）重置了关键词与类型但**保留状态 Tab**，Web 的「重置查询」会清空全部筛选项（`table.searchBar.resetTooltip`=「清除所有筛选条件」）→ **语义不一致，建议统一** |
| 批量操作 | ✅ 多选 + 批量删除（`useTableSelection` + `confirmBatchDelete`），11 个页面具备 | ❌ 仅左滑单条删除（`tickets/index.vue:125-129`） | **能力缺口**（移动端通常不需要，但需在需求文档中显式声明为「不支持」而非遗漏） |
| 导入 / 导出 | ✅ `FaImportDialog` / `FaExportDialog` / `FaExcelExport` / `FaExcelImport`，按权限 `perm-export` 控制（`user/index.vue:52-53`） | ❌ 无 | **能力缺口**，建议在 `REQUIREMENTS.md` 中登记 |
| 新增/编辑 | `FaDrawer` 抽屉 + `FaForm` + `:confirm-loading` 防重复提交（`user/index.vue:85-95`） | `wd-popup` 底部弹窗 + 手动 `submitting`/`loading`（注意 P3-7） | 形式差异合理；**移动端提交中的防重复覆盖不全** |
| 危险操作确认 | `ElMessageBox.confirm`（统一 `type: warning`）+ `ElPopconfirm` | 混用 `uni.showModal` 与 `wd-dialog` | **不一致 → P2-6** |
| 退出登录 | `ElMessageBox.confirm` + i18n（`layouts/fa-header-bar/widgets/FaUserMenu.vue:151`） | `globalDialog.confirm` + i18n（`pages/mine/index.vue:38-44`） | ✅ 一致（且都用 i18n） |
| 工单状态展示 | `FaStatusTag` 颜色映射 | `StatusBadge` 颜色映射 | **颜色语义不一致 → P2-8** |
| 状态切换（启用/停用） | `handleMoreClick("enable"/"disable")` → `status/batch` | 编辑弹窗内 `wd-radio-group` 单选 | 交互路径不同但结果一致；**词形不一致（停用 vs 禁用）→ P2-8** |
| 空态文案 | 固定「暂无数据」，不区分筛选 | 区分 `empty` / `emptyWithFilter` | **不一致 → P2-7** |

---

## 5. 可访问性（静态证据 + 需人工项）

### 5.1 可用静态代码证明（计入缺陷）

| 项 | 证据 | 级别 |
|---|---|---|
| 无 label 的表单控件 | Web `ElFormItem` 70 处中 **27 处无 `label`**（第 2.3 节 P2-3）；移动端 `wd-form-item` label 覆盖完整 | P2 |
| 图标按钮无可访问名 | Web **12 处**（P2-4）；移动端 `wd-icon` 均配可见文字或为装饰 | P2 |
| 自定义可点击元素键盘不可达 | Web **76 处** `@click` 的 div/span/li/td 无 `tabindex`/`role=`/`@key*`，仅 3 处实现正确模式（P2-2） | P2 |
| ARIA 使用量 | Web 全仓：`aria-label` ×7、`aria-hidden` ×5、**`aria-live` ×0、`aria-describedby` ×0、`aria-expanded` ×0**；移动端 `pages/subPages/layouts/components` 下 **aria-\* = 0** | P2 |
| 图片替代文本 | Web 24 个图片标签中 5 个无 `alt`（P3-12）；移动端 5 个 `<image>` 均无 `alt`（P3-13） | P3 |
| 焦点可见性 | Web 有 10 个文件定义了 `:focus-visible`/`:focus` 样式（`styles/element-plus/_overrides.scss:470-474`、`layouts/fa-work-tab/index.vue:818-823`、`views/module_ai/chat/components/FaWelcomeScreen.vue:110-113` 等），并有 2 处 `outline: none` 但**均提供了替代视觉反馈**（`styles/pages/_login.scss:411` + `:419-422` 的 focus 边框；`fa-work-tab/index.vue:819` + `:820` 的 inset 阴影）→ **未发现「移除焦点但无替代」的缺陷** | 通过 |
| 快捷键 | `Ctrl/Cmd+Enter` 提交搜索已实现并配提示文案 | 通过 |
| 语义化结构 | `layouts/index.vue:15,20` 使用 `<aside aria-label>` / `<main aria-label>`；`layouts/fa-breadcrumb/index.vue:3` 用 `<nav aria-label>` | 通过 |

### 5.2 不能用静态代码判断（**不得计为缺陷**，验证步骤见第 8 节）

- 对比度（需渲染后取实际前景/背景，尤其暗色模式下 P2-10 的硬编码灰色）。
- 屏幕阅读器实际朗读（`el-tooltip` 包裹的图标按钮是否可被读出名称；`ElMessage` toast 是否有 `aria-live` 通告——源码里没有，但 EP 内部实现需实测确认）。
- 触摸目标尺寸（移动端，需真机量取；仅能确认存在 `size="small"` 与 `w-4 h-4` 等小尺寸类，如 `views/dashboard/home/modules/quick-links.vue:35` 的 16px 删除按钮）。
- 键盘 Tab 顺序与焦点陷阱（`ElDialog`/`wd-popup` 内）。
- 移动端 H5 构建下的键盘可达性与小程序端 `aria-role` 支持。

---

## 6. 设计令牌偏离统计

### 6.1 令牌体系现状（三套并存）

| 端 | 令牌载体 | 说明 |
|---|---|---|
| Web | ① `src/styles/tailwind.css` 的 `@theme`（字号 5 档 + `--color-primary/g-100..900` 等映射到 `--fa-*`）；② 同文件 `:root` / `.dark` 的 `--fa-*`、`--default-*`、`--app-bg`（约 **45 个** CSS 变量）；③ `src/styles/core/_fa-tokens.scss`（SCSS 侧 6 个功能色，文件头注释明确声明「整个项目只有这一处定义 success/warning/danger/error/info 的 hex 值」）；④ `--custom-radius`（用户可调） | 设计意图清晰，但 `_fa-tokens.scss:4` 的「单一来源」约定**已被违反**（见 6.3） |
| 移动端 | ① `presetWot({ baseTokens: true })`（`uno.config.ts:27-29`）产出的 `--wot-*`；② `theme.json`（uni 原生暗色）；③ `uni.scss`（uni 内置 SCSS 变量）；④ 本项目自建 `--drop-*`（`styles/theme.scss`）；⑤ `composables/types/theme.ts` 的 `primaryShades` | 四份主题色相关定义重复（P2-9） |
| 文档站 | VitePress 默认主题，无共享令牌 | — |

### 6.2 硬编码色值统计

**Web**（`frontend/web/src`，`regex #hex{3,8}`）：

| 分区 | 出现次数 | 文件数 |
|---|---|---|
| `src/styles/**`（设计体系层，**合理**） | 64 | 8 |
| `views/module_task` | 38 | 12 |
| `views/dashboard` | 37 | 9 |
| `components/`（charts 27 + 其它 38） | 65 | 17 |
| `views/module_system` | 20 | 6 |
| `config/` + `hooks/` + `router/` | 66 | 5 |
| `views/fastlink` / `module_generator` / `layouts` | 10 | 4 |
| **合计** | **300**（其中 `src/styles/**` 外 **236**） | 58 |

**`src/styles/**` 之外的 TOP 文件**：`config/index.ts` 31、`hooks/core/useChart.ts` 21、`views/module_task/storage/browse/index.vue` 19、`views/dashboard/home/modules/banner.vue` 13、`components/charts/fa-map-chart/index.vue` 13、`views/module_system/auth/login/components/backdrops/FaLoginLeftView.vue` 10、`views/module_task/storage/workflow/components/protocol.ts` 9、`config/modules/fastEnter.ts` 8、`components/forms/fa-drag-verify/index.vue` 8。

**高频值与分布**（Web 全仓）：

| 值 | 次数 | 性质 | 样例 |
|---|---|---|---|
| `#fff`/`#ffffff` | 27+3 | 中性（多数合理） | `styles/**` |
| `#909399` | 16 | **EP 默认 info 灰**（绕过 `--el-text-color-secondary`） | `views/module_task/storage/browse/index.vue:88,213,233,284,289,433,444,471,476,492,514`、`views/module_generator/gencode/components/FaGenPreviewStep.vue:16,22`、`views/module_task/storage/workflow/index.vue:99` |
| `#333` | 8 | 浅色专用文本色（暗色下不可读） | `components/banners/fa-basic-banner/index.vue:156,173`、`components/charts/fa-map-chart/index.vue:188`、`views/dashboard/home/modules/banner.vue:62`、`views/dashboard/home/modules/it_banners.vue:53`、`components/forms/fa-drag-verify/index.vue:91` |
| `#409eff` | 6 | **EP 默认主色**（应为 `--el-color-primary`/`--theme-color`） | `views/fastlink/pricing/index.vue:348,377,385`、`views/module_task/storage/workflow/components/FaEdgeConfigPanel.vue:73,147`、`views/module_task/storage/workflow/components/protocol.ts:7-9` |
| `#e6a23c` | 5 | EP 默认 warning（应为 `--el-color-warning`） | `views/module_task/storage/browse/index.vue:221,260,503`、`protocol.ts:10-13`、`FaFileBrowserDialog.vue:58` |
| `#c0c4cc` | 4 | EP 默认 disabled 文本 | `views/module_task/storage/browse/index.vue:275,1685`、`FaDynamicEdge.vue:58`、`FaWorkflowDesignDrawer.vue:654` |
| `#67c23a` | 1 | EP 默认 success | `components/cards/fa-progress-card/index.vue:56` |
| `#f56c6c` | 1 | EP 默认 danger | `views/module_system/auth/login/components/forms/FaLoginAccountForm.vue:81` |
| `#606266` | 1 | EP 默认 regular 文本 | `views/module_task/storage/browse/index.vue:348` |
| `#f5f7fa` | 1 | EP 默认填充色 | `components/cards/fa-image-card/index.vue:12` |

> **判定**：`_fa-tokens.scss:1-4` 声明「整个项目只有这一处定义功能性色 hex」，但上述 EP 默认语义色在**业务代码**中被反复硬编码，**共 51 处**（`#909399`16 + `#409eff`6 + `#e6a23c`5 + `#c0c4cc`4 + `#67c23a`1 + `#f56c6c`1 + `#606266`1 + `#f5f7fa`1 + `#67C23A`1 + 其它）。这直接导致：用户切换主题色 / 切换暗色模式时这些元素**不跟随**。

**移动端**（`frontend/app/src`，排除 `uni_modules`）：

| 分区 | 出现次数 |
|---|---|
| 令牌源（`composables/types/theme.ts`、`App.ku.vue`、`styles/theme.scss`、`uni.scss`、`theme.json`） | 127 |
| `pages/login/index.vue` | 26（其中 `:327,335,343,351` 为微信/QQ/Gitee/GitHub **第三方品牌色，属合理豁免**；其余为 `var(--wot-*, #fallback)` 形式的 fallback） |
| `pages/index/index.vue` | 16（ECharts 系列色 + `#FFFFFF` 文本 + `isDark` 双色） |
| `store/themeStore.ts` | 11（`THEME_NAV_BG` 与 theme.scss 重复，P2-9） |
| `pages/login/register` / `forget/index.vue` | 9 / 9（同上，fallback 形式） |
| `composables/useGlobalToast.ts` | 4（`#07c160`/`#fa5151`/`#10aeff`/`#ff9f0a`，微信语义色，**合理豁免**） |
| 其余 5 个文件 | 各 1-2 |
| **`src/styles/**` 之外的合计** | **81 / 11 文件** |

**结论**：移动端 81 处中约 **60 处**是 `var(--wot-primary-6, #1C64FD)` 这类「带 fallback 的引用」写法（引用令牌但硬编码兜底值——**严格说是重复真值源，但不是绕过令牌**），真正的绕过集中在 `pages/index/index.vue:173-174,237-238,247-248,366,437,454,471,587,681,688,712` 与 `subPages/module_system/tickets/index.vue:223`、`pages/login/index.vue:587` 等。**共享组件层（`components/SkeletonPage.vue`、`StatusBadge.vue`、`GlobalDialog.vue` 等）几乎全部使用 wot 令牌**，这是移动端明显优于 Web 的地方。

### 6.3 圆角 / 字号 / 间距偏离

| 类别 | Web 硬编码统计 | 令牌替代 |
|---|---|---|
| 圆角 | `6px`×17、`8px`×14、`4px`×13、`999px`×4、`12px`×3、`2px`×2 等（另 `50%`×18 属合理） | `rounded-custom-xs/sm`（`tailwind.css:66-72`）、`--custom-radius`、`--el-border-radius-base`（`_overrides.scss:34-37` 已映射） |
| 字号 | `<style>` 内 `12px`×32、`14px`×30、`13px`×25、`16px`×13、`11px`×7…；任意值 class **33 处** | `--font-size-xs..3xl`（11/12/13/15/18/22/28） |
| 间距 | `<style>` 内 `padding/margin/gap` 固定 px 共 **231 处**（`8px`×61 占比最高） | Tailwind 间距刻度（0.5/1/2/3/4…） |

> **注意**：14px 这个最高频字号在 `@theme` 中**没有对应档位**（`--font-size-base: 13px`、`--font-size-lg: 15px`），说明令牌刻度与实际设计稿存在缺口 → 建议补 `--font-size-md: 14px`。这条是「令牌不完整」而非「开发者不守规矩」，建议在整改时区分对待。

---

## 7. 中文/英文文案与术语一致性

### 7.1 正向结论（先说不该修的）

| 项 | 事实 |
|---|---|
| locale 键完整性 | Web `zh.json`/`en.json` 各 509 键，**键集合完全相同**（无缺失、无多余）；移动端各 331 键，**完全相同** |
| 命名空间 | Web 24 个顶层命名空间（`common`、`login`、`register`、`setting`、`menus`、`table`、`httpMsg`…）；移动端 17 个（`common`、`login`、`register`、`setting`、`tickets`、`notices`…） |
| 移动端页面 i18n 覆盖率 | 14/14 页面（100%），模板内硬编码中文仅 1 文件 4 字符（微信隐私协议，合理） |
| 移动端空态文案 | 10 个专用键，且区分 `empty` / `emptyWithFilter` |
| 文档站 | zh/en 文件 1:1（各 9 篇） |

### 7.2 不一致清单

| 项 | Web | 移动端 | 判定 |
|---|---|---|---|
| 顶层命名空间复用率 | 24 个 | 17 个 | **仅 4 个共享**（`common`/`login`/`register`/`setting`），**两个字面 shared 键的英文值 10 个里有 5 个措辞不同**：`login.noAccount`（`No account yet?` vs `Don't have an account?`）、`login.sliderSuccessText`（`Verification successful` vs `Verified`）、`login.sliderText`（`Please slide to verify` vs `Slide to verify`）、`register.title`（`Create account` vs `Create Account`）、`register.toLogin`（`To login` vs `Login`）→ 建议建共享词表 |
| 「启用/停用」 | 停用（`common` 侧 73 处字面量） | 禁用（`common.status.disabled`） | 不一致 |
| 同一实体「公告」 | 业务页「公告通知」/ 顶栏「通知」 | 「通知公告」 | 三选一 |
| 状态词表 | 各页面各写一份（`user/role/position/notice` 共 73 处字面量） | 集中 `common.status.*`（14 个键） | Web 缺少集中词表 |
| 错误提示语言 | 2 处硬编码中文（`utils/http/index.ts:273,277`），其余 `$t` | **全部硬编码中文**（`http/tools/enum.ts` + `http/adapters/alova.ts`，约 15 处） | 两端均有缺口，移动端更彻底 |
| 文档站移动端术语 | 中文「移动端开发指南」 | 英文「Miniprogram Development Guide」（正文含 App/H5） | 不一致（P2-12） |

---

## 8. 需人工 / 真机验证清单

> 以下项**均不得当作已确认缺陷**；每项给出可直接执行的验证步骤。本轮未启服务、未上真机，故不下结论。

### 8.1 视觉与对比度

1. **暗色模式硬编码灰的可读性**（对应 P2-10）
   - 步骤：`cd frontend/web && pnpm dev` → 打开 `/module_task/storage/browse`、`/module_generator/gencode` → 右上角切「暗色模式」→ 用浏览器 DevTools 拾色器取 `text-[#909399]` 文字与其实际背景的对比度。
   - 判定：WCAG 2.1 AA 正文需 ≥ 4.5:1。
2. **深色模式冷启动是否出现原生背景色差**（对应 P2-9）
   - 步骤：真机（Android/iOS）系统切深色 → 冷启动 App（先杀进程）→ 录屏并逐帧观察导航栏/页面顶部是否出现 `#000000` → `#272B3B` 的跳变；同时测下拉回弹区。
3. **`theme.json` 是否真的被原生层应用**（对应 P2-9）
   - 步骤：构建小程序/App 后检查产物中 `app.json` 的 `themeLocation`，并在系统深色下观察窗口背景。若未生效，则 P2-9 应降级为「死配置」而非「色差」。
4. **暗色模式下圆角/间距令牌切换是否生效**（对应 P2-11）
   - 步骤：Web 设置面板切换圆角档位，逐页观察 6px/8px 元素是否跟随。

### 8.2 屏幕阅读器与键盘

5. **`el-tooltip` 包裹的图标按钮是否可被读出名称**（对应 P2-4）
   - 步骤：VoiceOver（macOS Safari/Chrome）或 NVDA（Windows Chrome）逐 Tab 遍历 `/module_task/storage/browse` 的后退/前进/刷新按钮，听是否读出「后退/前进/刷新」。
   - 若读出 → P2-4 中的 tooltip 类可豁免；未读出 → 结论升级。
6. **表单无 label 的实际影响**（对应 P2-3）
   - 步骤：在登录页 `/login`，用键盘 Tab 定位用户名/密码输入框，听 SR 是否朗读名称；再输入内容后确认 SR 是否仍能识别字段。
7. **自定义可点击元素的 Tab 顺序**（对应 P2-2）
   - 步骤：在 `/dashboard/home` 全程 Tab，确认「返回顶部」「设置面板关闭」「顶栏搜索」是否可达。
8. **弹窗焦点陷阱与 Esc 关闭**（ElDialog / wd-popup）
   - 步骤：打开 `FaDrawer` 与 `wd-popup`，Tab 是否循环在弹窗内、Esc 是否关闭、关闭后焦点是否回到触发按钮。
9. **toast 是否有无障碍通告**（`ElMessage` / `wd-toast`）
   - 步骤：触发一次失败请求，SR 是否播报错误。源码层未见 `aria-live`，需实测（EP 内部可能实现）。

### 8.3 移动端真机

10. **触摸目标尺寸**（WCAG 2.5.8 建议 ≥ 24×24 CSS px，iOS HIG 建议 44×44）
    - 步骤：真机打开工单列表，长按/开发者模式量取左滑删除按钮、`wd-fab`、Tabbar 项、以及 `views/dashboard/home/modules/quick-links.vue` 同类的 16px 小按钮（Web 侧是 `w-4 h-4`）。
11. **安全区与底部遮挡**（`env(safe-area-inset-bottom)`）
    - 步骤：全面屏机型（iPhone 15 / Android 手势条），检查工单页浮动按钮（`tickets/index.vue:252` `:gap="{ bottom: 40 }"`）与底部 tabbar 是否遮挡列表最后一条、`ticket-detail` 输入栏（`:253`）是否被 Home 条覆盖。
12. **`wd-slide-verify` 在真机的初始化与重置**（`pages/login/index.vue:64-85` 已针对小程序布局时序做处理）
    - 步骤：微信小程序 + iOS/Android App + H5 三端各登录失败 2 次，确认滑块能出现、能重置、能通过。
13. **导航栏标题首屏是否闪中文**（对应 P3-9）
    - 步骤：语言设为 English → 冷启动 → 录屏观察导航栏标题是否先显示中文再被 `useI18nNavTitle` 覆盖。
14. **`uni.showModal` 在 H5 下的实际外观**（对应 P2-6）
    - 步骤：`pnpm dev:h5` 打开工单页左滑删除，观察是否弹浏览器原生 confirm（外观与 App 内其他对话框不一致）。
15. **下拉刷新与触底加载的边界**
    - 步骤：弱网（DevTools/真机限速）+ 空列表下拉、最后一页触底，确认 `uni.stopPullDownRefresh()` 一定被调用（`useListPage.ts:66-79` 的 `finally` 已保证，但需实测不会卡住指示器）。

### 8.4 需求/契约层（需与需求方确认，非缺陷）

16. 移动端**不支持批量操作与导入导出**（`REQUIREMENTS.md` 是否登记为已知范围外？）。
17. 移动端**搜索重置保留状态 Tab** 是否符合两端统一的预期语义（第 4 节）。
18. `notice.status` 的正确语义（P1-1）请后端确认 `model.py:16` 注释即权威，并确认线上是否已有 `status=2` 数据。
19. 移动端 `loginFormData.captcha = 'verified'` 占位值（`pages/login/index.vue:138`）是后端约定还是历史遗留（`// 占位值，后端只校验 captcha_key 状态`），需与后端确认后端是否确实忽略坐标校验。
20. Web 端将语言切到 English 后，**业务菜单名来自后端数据库**（不是 locales），因此即使补齐前端 i18n，菜单仍是中文——需确认后端是否提供 i18n 字段（这决定 P1-2 的整改半径）。

---

## 9. 附录：统计口径与复现命令

所有统计均在仓库根目录 `/Users/tao/workspace/FastapiAdmin` 下执行，只读。

**模板内硬编码中文（第 1 节 / P1-2）**
```bash
# 口径：取 <template> 到 <script> 之间的片段，剔除 <!-- --> 注释后，
# 统计 (a) 非 : 开头属性值含 CJK 的出现次数，(b) 纯文本节点含 CJK 的出现次数
python3 - <<'PY'
import re, os
cjk = re.compile(r'[\u4e00-\u9fff]')
files=tot=0; hits=0
for root,dirs,fs in os.walk('frontend/web/src'):
    for f in fs:
        if not f.endswith('.vue'): continue
        s=open(os.path.join(root,f),encoding='utf-8').read()
        m=re.search(r'<template>(.*?)</template>\s*(?=<script)', s, re.S)
        if not m: continue
        tpl=re.sub(r'<!--.*?-->','',m.group(1),flags=re.S); files+=1; n=0
        for am in re.finditer(r'([a-zA-Z:@\-\[\]]+)\s*=\s*"([^"]*)"', tpl):
            if not am.group(1).startswith(':') and cjk.search(am.group(2)): n+=1
        for tm in re.finditer(r'>([^<>{}]*[\u4e00-\u9fff][^<>{}]*)<', tpl):
            if tm.group(1).strip(): n+=1
        if n: tot+=1; hits+=n
print(f"files={files} files_with_cjk={tot} cjk_occurrences={hits}")
PY
# → files=215 files_with_cjk=87 cjk_occurrences=1063
```

**i18n 覆盖率（P1-2）**
```bash
cd frontend/web/src && T=0; N=0
for f in $(find views -name "*.vue"); do T=$((T+1)); grep -q '\$t(\|useI18n' "$f" || N=$((N+1)); done
echo "views=$T no_i18n=$N"     # → views=101 no_i18n=85
cd ../../app/src && T=0; N=0
for f in $(find pages subPages -name "*.vue"); do T=$((T+1)); grep -q '\$t(\|useI18n' "$f" || N=$((N+1)); done
echo "pages=$T no_i18n=$N"     # → pages=14 no_i18n=0
```

**硬编码色值（第 6.2 节）**
```bash
# Web：全量
grep -rhoiE "#[0-9a-f]{3,8}\b" --include="*.vue" --include="*.scss" --include="*.ts" --include="*.css" frontend/web/src | wc -l   # → 300
# Web：排除设计体系层
grep -rniE "#[0-9a-f]{3,8}\b" --include="*.vue" --include="*.scss" --include="*.ts" frontend/web/src | grep -v "/styles/" | wc -l  # → 236 / 50 文件
# 移动端：排除 uni_modules 与令牌源
grep -rniE "#[0-9a-f]{3,8}\b" --include="*.vue" --include="*.ts" --include="*.scss" frontend/app/src \
  | grep -vE "uni_modules|composables/types/theme.ts|App\.ku\.vue|uni\.scss" | wc -l                          # → 81 / 11 文件
```

**键盘可达性（P2-2）**
```bash
# 口径：<div|span|li|td> 且同标签内含 @click，且不含 tabindex / role= / @key*
python3 - <<'PY'
import re, os
n=0
for root,dirs,fs in os.walk('frontend/web/src'):
    for f in fs:
        if not f.endswith('.vue'): continue
        s=open(os.path.join(root,f),encoding='utf-8').read()
        for m in re.finditer(r'<(div|span|li|td)\b([^>]*?)>', s, re.S):
            a=m.group(2)
            if ('@click' in a or 'v-on:click' in a) and not ('tabindex' in a or '@key' in a or 'role=' in a): n+=1
print(n)   # → 76
PY
grep -rn 'role="button"\|tabindex' --include="*.vue" frontend/web/src    # → 正确模式仅 3 处
```

**ElTable `loading` 无效属性（P2-1）**
```bash
grep -rn "loading" frontend/web/node_modules/element-plus/es/components/table/src/table/defaults.d.ts | head
# loading 位于 interface TreeNode（:292），TableProps（49 个 prop）不含 loading
grep -rn "loading" frontend/web/node_modules/element-plus/es/components/table/src/table.mjs   # → 无命中
```

**locale 键对齐（7.1）**
```bash
python3 -c "
import json
def flat(d,p=''):
    o={}
    for k,v in d.items():
        kk=f'{p}.{k}' if p else k
        o.update(flat(v,kk)) if isinstance(v,dict) else o.__setitem__(kk,v)
    return o
for b in ['frontend/web/src/locales/langs','frontend/app/src/locales/langs']:
    en=set(flat(json.load(open(b+'/en.json',encoding='utf-8'))))
    zh=set(flat(json.load(open(b+'/zh.json',encoding='utf-8'))))
    print(b, len(en), len(zh), 'only-en', sorted(en-zh), 'only-zh', sorted(zh-en))
"
# → web 509/509 [] []；app 331/331 [] []
```

**其他一次性核对命令**
```bash
grep -c "ElFormItem\|el-form-item" -r frontend/web/src --include="*.vue"   # form-item 70 处，无 label 27 处
grep -rn "useListPage" -A 12 frontend/app/src/pages frontend/app/src/subPages  # error 未被任何页面消费
grep -rn "void=ElMessageBox\|ElPopconfirm" frontend/web/src --include="*.vue"  # 二次确认覆盖：11+ 文件
sed -n '16p' backend/app/modules/system/notice/model.py   # 状态(0:草稿 1:已发布 2:已归档)
```

**本轮未执行的验证方式（重要）**：未运行 `pnpm dev`/`pnpm build`/`vitest`/`eslint`/`stylelint`，未截图，未上真机，未做页面性能与网络抓包。所有「未验证」结论已在正文与第 8 节标明。

---

## 10. 建议整改优先级（供 captain 汇总用）

| 顺序 | 动作 | 覆盖问题 | 预估成本 |
|---|---|---|---|
| 1 | 修正 Web 通知 `status` 枚举（+2 已归档，改 0 草稿/1 已发布） | P1-1 | 1 文件 / 3 处 |
| 2 | `FaTable` 增加 `error`/`retry` prop，移动端增加 `ErrorState` 组件并消费 `error` | P1-3、P2-7 | 2 个共享组件 + 16/2 页接入 |
| 3 | 移动端区分「加载失败」与「不存在/空」，修 3 个页面 | P1-4 | 3 文件 |
| 4 | 共享组件 + HTTP 层文案先走 i18n（Web 8 个文件 / 移动端 2 个文件） | P1-2 的 80% 收益、P2-5、P3-1、P3-3 | 10 文件 |
| 5 | `useClickable`/`aria-label` 批量补齐 + 修 `module_monitor/cache` 的 `v-loading` | P2-1、P2-2、P2-4 | 机械替换 |
| 6 | 抽 `constants/status.ts` 统一状态词表与色板，两端共用 | P2-8、P3-11 | 新增 1 文件 + 6 文件 |
| 7 | 移动端 `theme.scss` 收敛为唯一主题真值源，对齐 `theme.json` | P2-9、P2-10（App 侧） | 3 文件 |
| 8 | Web EP 默认色 → 语义令牌；`--font-size-md` 补齐；stylelint 规则拦截新增硬编码 | P2-10、P2-11 | 渐进 |
| 9 | 清理死代码与死样式 | P3-4、P3-5、P3-6 | 4 文件 |
