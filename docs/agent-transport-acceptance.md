# Agent 第 3.1–3.3 阶段统一验收

本清单面向 local/TACC 传输、恢复与清理的统一验收。启动命令见 [终端操作手册](terminal-operations.md) 末尾；架构与错误码见 [对接说明](agent-backend-integration.md)。2026-11-20 合并 main 后要求唯一 head `20261120_0007`，兼容两支历史 `20261118_0006` 的数据库结构。真实集群、数据库和模型项目应分别记录结果，不以离线模拟代替。

## 1. 验收前记录

- 当前分支、Git 提交/工作区状态，以及是否已部署本轮未提交代码。
- 数据库 revision、后端传输类型、SSH 别名、共享目录、分区/账户和 Agent 模型 ID；不记录密钥或含凭据的连接串。
- 检查本机和远程的系统时间；登录/计算节点均可读写工作根目录并访问独立 Agent 环境。
- 停止旧研究 Worker，API 与新 Worker 读取同一 backend/.env；不要让未完成任务跨传输类型切换。

## 2. 离线自动验证

按终端操作手册运行两侧完整离线测试。检查实际输出：

| 检查 | 预期 |
|---|---|
| 原后端/Agent 回归 | 通过；数据库实测默认跳过，平台不能创建符号链接时对应测试允许跳过 |
| 状态解析 | 外来 dispatch/摘要/作业 ID、重复 JSON key、超大状态与矛盾状态被拒绝 |
| 本地派发 | 同一 dispatch 只启动一次，重建适配器恢复同一作业，启动/进程失败明确结束 |
| 跨独立环境 | 后端导出真实合成 PDF → Agent 读取物理第 3 页 → 完整结果返回 → 后端 C1 映射有效 |
| SSH/Slurm 模拟 | 真实 stdlib 远程 RPC 与脚本模型往返通过；外部 SSH/Slurm 由夹具替代 |
| 提交不明 | 唯一匹配恢复，无匹配不重提，多匹配明确失败 |
| 取消 | 只取消已核实的本人任务 ID，已终态不重复 scancel |
| 清理 | 默认 dry run、最少一天保留、只清理自身 dispatch、重入安全且旧 dispatch 不再执行 |
| 部署白名单 | 不含 .env、私钥、api-keys.txt、数据库配置、用户 PDF、虚拟环境与运行产物 |

跨环境用例如果因未安装 Agent 环境而跳过，应先安装再重跑。所有测试使用合成论文和脚本模型；不发真实 arXiv/模型请求。

## 3. 隔离 PostgreSQL 验证

仅使用本机事先创建的专用空库，名称必须为 agent_bridge_tests 或 agent_bridge_tests_<32位小写十六进制>。测试会迁移并 TRUNCATE 其中业务表，严禁指向开发、演示、旧验收或生产数据库；未准备专用库时本项标记“未执行”。

Windows（从项目根目录）：

~~~powershell
$env:AGENT_TEST_DATABASE_URL = "<本机专用agent_bridge_tests库的PostgreSQL连接串>"
uv run --project .\backend --locked python -B -m unittest discover -s backend/tests -p test_agent_postgres.py -v
Remove-Item Env:AGENT_TEST_DATABASE_URL
~~~

macOS：

~~~bash
AGENT_TEST_DATABASE_URL='<本机专用agent_bridge_tests库的PostgreSQL连接串>' uv run --project ./backend --locked python -B -m unittest discover -s backend/tests -p test_agent_postgres.py -v
~~~

预期该文件的测试不被跳过，覆盖冻结传输、所有者/租约 fencing、作业 ID 防覆盖、原生结果/引用入库、包装器失败映射与终态取消确认。该连接串只用于隔离测试，不写入 backend/.env。

## 4. 本地真实模型验证

先使用 AGENT_TRANSPORT=local。从页面上传一篇英文 PDF，再新建任务，不使用旧结果代替。

| 操作 | 预期与记录 |
|---|---|
| 单篇摘要 | queued → running → succeeded，结果及引用可读；记录 task/dispatch/job ID |
| 中文问答 | Agent 读取原始 PDF，回答有对应原文；证据不足时保留真实 stop_reason，不回退旧后端 |
| 两篇综述 | 两篇来源均受授权，比较与未解决项正确展示 |
| 引用跳转 | 返回原始上传论文的正确物理页，保持现有页内阅读与返回任务体验 |
| 刷新页面 | 作业 ID、结果与当前任务保持一致，不产生新执行 |
| Worker 中途重启 | 原任务仍使用同一 dispatch 和作业 ID；租约过期后恢复，原执行截止时间不重置 |

重启研究 Worker 后，为此前 13 页本地 PDF 新建摘要任务。检查 stop_reason、usage.agent_steps 和最终引用。main 当前只在上下文压力达到阈值时进行一次无工具最终作答；若 trace 出现 action=finalize / reason=context_pressure / purpose=finalize，记录该路径。不再预期 archived_readings 或 restore_limit。核对主要结论与引用页后记录真实结果。TACC 复测前重新部署 Agent 运行包。

如果失败，记录 task ID、dispatch ID、安全错误码及原生 stop_reason。不要删除锁、修改输入或手工覆盖 result.json 来继续原任务；确需重做则新建任务。

## 5. TACC 统一验证

完成 SSH、共享路径、Agent 环境、模型与 Slurm 权限配置后切换 tacc 模式。先运行一篇小论文，再运行两篇综述。

| 场景 | 预期 |
|---|---|
| 自动提交 | 本机上传的 PDF 出现在专属远程输入包中，Agent 在计算节点执行，页面收到完整结果 |
| 身份对应 | 后端 remote_job_id 与 Slurm ID 相同，作业完整名为 acs-<dispatch无连字符> |
| 平台排队 | 仍受原任务总时限约束，running 不被误解为模型已开始生成；已过期作业启动时不调用模型 |
| Worker 重启 | 恢复同一作业，不再执行 sbatch，不增加模型调用 |
| 暂时断网 | 恢复网络后继续查询/下载；不会因下载失败再次启动研究 |
| 提交响应丢失 | 按完整作业名和提交时间核对 squeue/sacct；零/多匹配不盲目重提 |
| 计算作业失败 | 包装器/Slurm 失败及时反映到后端；有完整失败研究结果时仍保存原生内容 |
| 超时 | 后端任务失败，维护循环补偿 scancel；远程无法确认时不声称已取消 |
| 取消后重启 | 维护循环继续核实尚未确认的取消，未交付目录仍保留 |
| 产物校验 | 不接受跨任务、跨输入、跨作业 ID 的结果，也不跳过大小/页码/来源检查 |

提交响应丢失、矛盾状态和恶意产物首先由离线夹具验证；不需要破坏真实任务来制造这些故障。真实网络/调度测试应在专用测试账号或小型测试任务上进行。

## 6. 保留与收尾

先运行维护命令的 --cleanup 预览，再决定是否 --apply。默认本地/远程保留七天，最低一天；较长的一侧保留要求生效。不要修改真实任务文件时间来缩短等待，保留期边界已由隔离夹具验证。

核对清理后：原始上传论文、业务数据库结果、其他用户/dispatch 文件仍存在；当前运行与未确认取消的任务不被清理；重复清理不报错、不重新执行研究。小型已清理身份凭据继续保留。

统一验收记录：日期、部署版本、每项通过/失败/未执行、任务与作业 ID、失败安全代码，以及真实模型/平台与离线测试的边界。只有本地、TACC 和恢复检查均完成后，才标记真实部署验收通过。
