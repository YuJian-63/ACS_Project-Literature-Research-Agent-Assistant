# Research Workspace Redesign Implementation Plan

用户已批准 docs/design-proposals/2026-11-14/refined.html 的 A+B/C 设计。直接在现有工作区实施，不创建分支、不提交、不修改后端或调用真实模型/arXiv。

## 设计与边界

A 的绿色工作台统一五类页面；B 的衬线正文和章节阅读用于研究结果；C 的固定列矩阵与右侧来源用于跨论文比较。保留上传、搜索、导入历史、筛选、跨页选文、幂等提交、任务轮询、模拟标识、错误恢复、引用页码和语言设置。

结果使用真实产物和输入论文。正文、比较、执行记录分开；引用与比较单元格联动证据面板。手机采用逐篇比较和可关闭来源抽屉。不得把生成正文随着界面语言切换自动翻译。

## 任务

- [x] 公共框架与设计规范：App.tsx、styles.css、LocaleProvider.tsx、DESIGN.md；导航、面包屑、字体、色彩和移动端入口统一。保留路由和原有语言选择。
- [x] 五类页面布局：PapersPage.tsx、SearchPapersPage.tsx、NewTaskPage.tsx、TasksPage.tsx、TaskDetailPage.tsx；压缩上传区、搜索与导入记录分栏、改善研究表单与记录列表。
- [x] 结果与证据：ArtifactView.tsx 负责正文/比较视图；新增 EvidencePanel.tsx 和 ComparisonView.tsx，按真实 citation_keys 联动；TaskDetailPage.tsx 将执行记录和统计放入独立页签。输入标题来自 task.paper_ids 对应的论文，缺失时用已显示的引用标题与明确回退。
- [x] 双语与响应式：messages.ts 增补界面文案；使用自托管拉丁字体与系统中文字体回退，避免误用样例字符子集承载任意内容。覆盖载入、空结果、失败、进行中、模拟和无引用状态。
- [x] 验证：保留既有 review 检查，新增浏览器回归覆盖正文引用、矩阵来源、执行记录、移动抽屉、语言持久化与五类页面溢出。先在原界面运行新交互回归确认失败，再在实现后验证通过。构建、类型检查、运行适当既有检查并检查截图。

## 接口

ArtifactView({artifact: Artifact, papers?: Paper[]})；ComparisonView({comparison: ComparisonTable, papers: Paper[], citations: Citation[], onSelect: (citationKey: string, trigger: HTMLElement) => void})。
EvidencePanel({citations: Citation[], papers: Paper[], selectedKey?: string, tab: string, onTabChange: (tab: string) => void, open: boolean, onClose: () => void, onSelect: (citationKey: string) => void, onReturn: () => void})。

使用现有 paperFileUrl(paper_id, page_number) 和 useTask，不新增接口。长标题自动换行；不将未知值显示为零，不虚构研究数据或运行统计。

## 实施记录

2026-11-14：已检查 React/Ant Design 页面与现有自动预算、搜索韧性、幂等提交实现。设计已由用户批准。按上述顺序实施，完成后记录实测结果。

2026-11-14 实施与验证：

- 已完成公共工作台、五类页面和正文/比较/执行记录视图；引用使用真实引用键、论文标题、原文和页码。移动端逐篇比较、来源抽屉及关闭后的键盘焦点恢复已验证。
- 新增 DESIGN.md 与自托管拉丁字体（附 OFL）；补充双语界面文案，不自动翻译已生成的研究内容。
- 新浏览器用例先在旧界面失败（缺少 citation-trigger），实现后通过；覆盖重复选择同一引用时退出输入论文页签、正文代码保持字面量、已有 Markdown 引用链接、六篇比较和无引用摘要/模拟标识。
- npm.cmd run build 通过（包含 TypeScript 类型检查）；npm.cmd run verify:review 和 runtime/verify-i18n-core.cjs 通过。
- frontend/checks/workspace-browser.py 通过，覆盖五类页面 390/768/1440px、语言切换与刷新、执行记录、运行/失败状态、来源页码与抽屉焦点。
- 既有 frontend/checks/review-browser.py 在 5191 临时 Vite 上通过，覆盖自动预算、幂等提交、双语进度与刷新恢复；既有 runtime/verify-search-resilience-ui.py 的离线检查通过，覆盖错误后保留旧结果、分页重试、冷却、导入独立性和移动布局。两项只在内存中替换测试服务地址。
- 已检查论文库、搜索、新建研究、研究记录、结果正文、比较及移动端截图。截图和浏览器夹具位于忽略的 runtime/redesign/；不作为产品数据。
- 浏览器检查均拦截 API，未调用真实 arXiv/模型、未修改数据库。本次不处理用户明确推迟的 arXiv 非法响应问题。
- 独立只读代码审查未发现需要修复的正确性、可访问性或原流程回归问题；git diff --check 通过。已停止本次创建的 5191 临时 Vite，未操作用户原有服务。
