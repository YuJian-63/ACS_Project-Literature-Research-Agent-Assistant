# MVP-1B：证据约束的真实摘要与问答

## 状态与目标

待用户审核。依据 Proposal、API 契约、数据库设计与 MVP-1A。保留 Mock/API 兼容性，新增基于已解析片段的真实摘要和论文问答；后端核验引用来源后，原子写入产物、引用与成功状态。

## 方案

独立 Runner 接口 + 可替换模型适配器。Mock 与真实 Runner 分开执行，共用租约、心跳、事件、超时监控和终态写入。首个适配器对接通过环境配置提供的 OpenAI-compatible Chat Completions 服务。真实 Runner 配置缺失时，提交端返回 `503 RUNNER_NOT_CONFIGURED`，不落任务且不得静默降级成 Mock。

## 范围

- 真实 Runner 只开放 `summary`、`qa`；`review`、搜索、跨论文比较、OCR、向量库、Agent 工具调用留到后续阶段。
- Mock 行为不变：`is_mock=true`、无引用、无伪造 usage。服务端配置选择 Runner，客户端不能切换。
- 真实任务只接受 `ready` 论文；绑定任务创建时冻结的论文集合及 SHA-256。
- MVP 检索不依赖向量库：问答按问题词项做有界词法排序；摘要按论文分布式抽取片段。严格限制上下文片段数/字符数。
- 模型返回结构化 Markdown 正文及引用候选；服务端生成稳定 `C1…Cn` 键与正文标记，不信任模型自报键。
- 更新结果 UI，真实引用可查看论文、物理页码和原文；不开放任意 chunk API。

## 数据流

1. `submit_task` 按服务端设置冻结 `runner_type`、model ID 和 workflow/prompt 版本；真实模式拒绝 `review` 和未 ready 论文。
2. Runner Worker 领取对应任务，复用数据库行锁、租约、心跳、超时监控及失主拒写策略。
3. 读取选定论文和 chunks，确认状态和哈希仍匹配；检索器构建有界上下文并保留 paper/chunk/page 身份。
4. 版本化提示调用模型适配器，取得结构化草稿及供应商 usage；超时、步骤和 token 预算均须生效。
5. 校验器核实 chunk 属于任务选定论文、页码吻合、quote 是存储内容原样子串、引用键唯一且正文标记完整。无证据只能明确说明证据不足。
6. 完成事务再次核验 owner/lease，原子写入 Artifact、Citation、已知 usage、succeeded 状态和事件。非法结果报 `INVALID_AGENT_RESULT`；网络/模型错误报通用 `AGENT_EXECUTION_FAILED`。

## 配置与安全

- 环境配置包含 `TASK_RUNNER=mock|langgraph`（默认 mock）、模型 base URL、model ID、API key (`SecretStr`)、网络超时及上下文预算；选用真实 Runner 时必填项缺失由提交服务检查并返回 `503 RUNNER_NOT_CONFIGURED`。
- API key 不入库、不进入 run_config、日志、事件或错误详情；论文文本和模型原始响应也不写日志。
- 论文内容视为不可信数据，不开放模型工具。预算耗尽要失败而非静默截断；供应商 usage 不可用时保留 null。
- 不新增迁移；复用 `paper_chunks`、`citations`、现有 artifact 与 task usage 字段。

## 兼容与验收

- 保持端点和响应结构；API 契约说明 Runner 模式、可用 task type、ready 前置条件、缺少模型配置时行为及错误码。
- Mock API/Worker 回归通过；假模型测试覆盖有效引用、错 paper/chunk/page、伪造 quote、缺/多标记、无证据、非法结构、超时、预算、模型异常。
- 失去租约、任务超时或写入异常后不能留下 artifact/citation/usage 半成品；成功时产物、引用、统计、状态、事件事务一致。
- 前端正确呈现真实引用及 Mock 提示；后端测试和前端生产构建通过。

## 依赖与限制

当前无 LangGraph/模型 SDK 依赖，工作区也未配置模型地址/凭据。先实现可注入模型接口、OpenAI-compatible adapter 和假模型端到端测试；真实服务联调需部署环境变量。具体 TACC 地址由部署方提供，不写入默认值。
