# 用户改动：Agent v1 后端对接设计草案

日期：2026-11-17；归属 user-change；状态：待用户确认。
依据：agent/agent-io-interface-v1.md、agent/schemas.py、agent/baseline.py。
此前用户已确认职责方向；本文补充拿到真实代码后的实施选择。

## 目标

Agent 完成搜索、读取、解析、工具和模型调用、研究及引用校验。
后端处理认证、任务归属、排队、调用隔离、超时、保存及查询。
首轮覆盖 arXiv 固定来源 QA，再扩展综述与允许搜索；本地 PDF 暂缓。
保留已有任务、产物和历史开发记录，不覆盖旧结果，也不删除旧 Worker。

## 调用方案比较

1. Worker 进程内导入：简单，但要求后端也使用 Agent 的 Python 3.12 环境，
   且顶层 apis/config/schemas 导入和全局环境配置会耦合到后端。
2. 后端 Worker 启动专用 Python 3.12 子进程，桥接脚本调用 run_task：
   多一层进程协议，但保持 Agent 代码不变、独立依赖，支持父进程超时和停止管理。
3. HTTP 服务：Agent 尚未提供，当前无须新增网络服务。

建议采用方案 2。仍是函数调用，不调用现有 CLI；CLI stdout 只有结果摘要，
不能作为完整 TaskResult。桥接脚本设 agent 目录为导入路径和运行目录，使用
run_task(task, persist=False)，通过独立结果文件交换完整 JSON，避免日志污染协议。
结果文件与诊断位于每任务独立临时目录，收尾释放；父 Worker 维护心跳并限制
执行时间，超时或所有权丢失时停止子进程，不接受迟到结果。

## 请求与兼容

- 保留 /api/v1/tasks 的账户归属与幂等规则，新 Agent 请求接收 question、sources、
  allow_search、max_papers、max_steps、timeout_seconds、max_output_tokens。
- 服务端生成任务 UUID 作为 task_id，不接受用户指定其他用户任务 ID。
- task_type 如保留为 UI 分类，只存后端，不传给 Agent；旧 budget 不传给 Agent。
- question 去除首尾空白并拒绝空值；summary 默认任务说明由后端补齐。
- 不要求 Agent 请求先有本地 Paper 或 ready chunks；保留旧 paper_ids 请求的兼容路径。
  旧论文选取只有存在 arXiv 来源时才可转为 Agent sources；不静默替换本地 PDF。
- 新模式预算配置仅表达 v1 实际支持的限制，累计 Token 仅统计，不宣称强制限制。
- 来源格式以 Agent 校验为准，后端捕获校验异常，来源原文不作为文件路径执行。

## 存储和状态

- 通过新 Alembic revision 扩展任务模式及输入/结果快照，不修改既有 migration。
- 新 runner 标识 agent，原 mock/langgraph 任务保持原语义。
- 新结果独立保存完整 TaskResult JSON，不写入依赖本地 chunks 外键的 citations 表。
- completed：后端 succeeded；partial：后端 succeeded，结果中保留 partial/unresolved
  并向前端明确标注部分完成，不把它显示为全部完成。
- step_limit/time_limit/context_limit/model_error/invalid_output/invalid_citations 等其他
  停止原因：后端 failed，仍保留完整结果和诊断，失败任务也能查询停止信息。
- 校验 task_id 与领取任务一致；字段格式、大小和任务所有权校验留在后端。
- 存储真实 usage，未知 Token 保持 null，工具调用不再硬编码为 0。
- 不重跑失联 Agent 任务，避免重复模型开销；后续如需重试创建新任务。

## 前端结果

新增明确的 agent-v1 结果类型，保留旧产物渲染。
原样使用 answer、Markdown comparison_table 和 Agent 引用身份；引用链接使用
Agent URL 与物理页码，不构造本地 paper UUID 路径。
展示 unresolved、stop_reason、usage；trace/configuration 分离查询，默认不随任务
列表返回大对象。只向任务所属用户开放，返回前检查并过滤潜在凭据字段。
Agent 只在结束返回 trace，因此不伪造研究阶段的实时进度。

## 验证与交付顺序

1. Python 3.12 独立环境与离线桥接测试：真实 run_task 搭配假模型/读取器，
   完整结果序列化、异常、停止与非零退出处理，不用假结果宣称真实模型已接通。
2. 数据迁移、任务提交/领取/完成、归属和幂等测试；迟到和跨任务结果拒绝。
3. 前端适配和刷新恢复验证；旧任务及 evidence API 回归。
4. 隔离 PostgreSQL 及真实模型/arXiv 冒烟：固定来源 QA、综述、搜索、失败路径。
5. 每阶段在新 user-change 记录追加证据；无密钥时明确真实联调未完成。
