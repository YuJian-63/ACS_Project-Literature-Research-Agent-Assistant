# Agent 远程作业入口实施计划

用户授权：先将此前后端、Agent 修改分别提交到 backend-dev-v2，再进行下一阶段；只提交本地，不推送远程。已完成本地提交 2cf1acf（后端）与 f8dd0ee（Agent）。

## 目标与边界

实现可供之后 TACC 作业调用的独立入口：接收后端 input.zip、预期 dispatch_id 和 manifest SHA-256，安全展开到临时工作目录，注入 SourceReader 执行现有 Agent，原子保存完整结果信封和状态文件。只改 Agent 与说明文档，不启动服务、不访问真实模型/数据库/TACC、不自动提交本阶段代码。TACC CLI 的上传、提交、轮询、下载属于后续传输桥接。

## 模块设计

- agent/agent_io/contracts.py：独立的派发清单、运行配置、严格 JSON 与结果来源检查，复用 Agent Task 和 LocalSource，不导入后端包。
- agent/agent_io/bundle.py：受控 ZIP 检查与临时展开，校验所有文件大小和摘要，退出仅清理本次创建的临时目录。
- agent/agent_io/job.py：独占执行锁、运行状态、调用 run_task、原子结果信封、相同输入的结果复用及 CLI。
- agent/run_dispatch.py：项目根目录可调用的薄入口。
- agent/tests/test_dispatch_bundle.py、test_dispatch_job.py：合成 PDF 与脚本模型的离线测试。

## 实施步骤

1. 先写来源/ZIP/身份和执行入口测试，确认缺少入口时失败。
2. 实现协议与安全展开：只允许 manifest.json、task.json、sources.json 及授权 PDF，拒绝重复、越界、链接、加密、额外成员与超限数据；要求 Task/清单严格一致。
3. 实现执行与原子输出：显式 persist=False；模型任务失败仍返回完整研究结果；包装器异常仅写脱敏状态，不伪造 TaskResult；重复完成结果复用，进行中或失败不会静默重新执行。
4. 更新接口、双平台操作说明及后端集成边界；完整 Agent/后端离线回归和差异检查。

## 固定协议

- 输入摘要校验 manifest.json 原始字节；可信调用方必须通过参数传入预期值。
- 输出 agent-result-v1 信封，保存 dispatch_id、input_sha256、可空 remote_job_id 和完整 TaskResult，默认上限 16 MiB。
- status.json 使用 agent-job-status-v1。初始设计的 running/finished/failed 已由 2026-11-19-agent-status-simplification.md 更新为 running/succeeded/failed；旧 finished 仅兼容读取。下方初始测试数量为当时验收记录。
- 同一输出目录由原子创建的执行锁保护；完成后重复调用复用同一结果；崩溃遗留锁不自动抢占。失败必须显式检查后重建任务，不隐式重复计费。
- 工作目录允许临时清理，output-dir 必须由操作者指定为持久化位置；状态/错误只保留代码与异常类型，不写原始异常信息、凭据或主机路径。

## 重点验收

可信摘要错误、UUID 错误、任务/来源/runtime 不一致、重复键、路径逃逸、ZIP 链接或炸弹、PDF 被篡改时，模型调用次数为零。正常输入可由脚本模型读到原始 PDF 并形成后端兼容信封。重复执行不再次调用模型；异常和结果超限不发布部分 result.json；原有 arXiv 与本地来源测试继续通过。


## 实施结果（2026-11-19）

步骤 1–4 已完成。新增独立 agent_io 包与 run_dispatch.py；后端和 Agent 不共享运行依赖，研究仍执行既有 baseline。补充了异常分类、计数与入库边界、NUL 字符、执行锁、重放与脱敏测试。仅对作业边界模块放宽 BLE001，以便捕获任意提供方异常后只返回安全代码/类型，不输出原始异常。

验证记录：

- 最初新增用例因缺少 agent_io 失败；补充执行异常用例也先验证失败，再修正解包上下文，避免把研究期间 OSError 误报为坏输入。
- 50 项 ZIP/入口协议测试通过；包含安全解包、身份与内容校验、原始 PDF 证据、完整信封、原子发布、失败隔离与结果复用。
- Agent 全量离线测试 188 通过、4 跳过；跳过的是数据库实测与 Windows 符号链接权限相关用例。
- 后端 unittest 共 193 项，123 通过、70 数据库用例跳过，未连接业务数据库。
- 后端实际 export_bundle → Agent 独立 Python 环境读取原始 PDF 与脚本模型 → 后端 read_result/validate_delivery/present_result 离线往返通过，物理页和 C1 映射正确。
- 本阶段 Python 模块与测试的 Ruff lint、format 检查通过；项目根目录 CLI --help 可用。
- Windows/macOS 根目录相对路径操作模板和预期结果已更新；macOS 与 TACC 未实机验证。

没有修改实际 .env、执行数据库迁移、启动服务或调用真实模型/TACC；本阶段代码保留在工作区，没有自动提交或推送。TACC 自动传输、平台作业身份恢复以及包装器失败状态向后端映射，仍属于下一阶段。
