# 课程 Model Server

在本机完成数据库迁移后，启动现有网页和 TCloud Worker。在侧栏「模型管理」启动课程 Qwen。Worker 在后台提交和检查 GPU 作业，每 30 秒轮询启动进度，就绪后每分钟检查一次。页面每 10 秒刷新，可关闭。就绪后，在「新建研究 → 模型来源」选择「课程模型服务」。作业使用该轮服务地址，检索扩展的 embedding 继续使用百炼。所有登录用户可以使用就绪服务，本轮启动者可以停止它。百炼保留为默认聊天模型。

选择「指定服务地址」可以直接输入同组的 OpenAI 兼容服务 URL，如 `http://10.0.3.10:8000/v1`，也可在模型管理页按账号保存常用地址。每个研究任务保存创建时选定的地址。CPU 作业从该地址的 `/models` 读取模型名；多个模型中优先使用课程 Qwen。服务需支持非流式回答与工具调用。页面只监控和停止本应用提交的作业。手填地址的连通性由 TACC CPU 研究作业实际调用时确认。

## 服务版本

| 目录 | 用途 | 关键配置 |
| --- | --- | --- |
| [`server/`](server/AGENT_DEPLOYMENT_GUIDE.txt) | 网页模型管理和独立验收默认提交的原版服务。 | `max_num_batched_tokens=4096`。 |
| [`server-opt/`](server-opt/README.md) | 手动部署的优化版，附带串行/并发实验、工作负载、结果摘要和[实验报告](server-opt/reports/Server_report.md)。 | `max_num_batched_tokens=8192`，面向 C=4 长输入并发负载。 |

两者均使用课程公共 vLLM、两张 GPU、TP=2、`max_model_len=36864`、`max_num_seqs=4` 和前缀缓存。8192 是每轮调度预算，不是输出 Token 上限；实验中吞吐量略有改善，但 TTFT 增加，不能据此保证所有任务更快。

## 使用优化版

在已配置课程 SDK 的 WSL/Linux 终端运行：

```sh
cd /path/to/project/model-server/server-opt
bash setup-sdk-account.sh
tcloud submit
```

记录返回的 GPU 作业号，按下方命令查询队列和服务日志。须等日志出现 `Application startup complete.` 后，使用本轮 `SERVICE_BASE_URL`，不能复用历史节点地址。在网页「新建研究 → 模型来源」选择「指定服务地址」并填写该 URL，或按 [Agent 文档](../agent/README.md)配置独立客户端。GPU 服务需在研究完成前保持运行。

后端和 `scripts/verify-model-server` 仍使用 `server/`，不会因新增目录自动切换。本应用不会监控或停止手动提交的优化版作业；结束后用 `tcloud cancel -j GPU作业号` 释放。完整启动、验证和复现实验步骤见 [优化版 README](server-opt/README.md)。

## 响应与指标

两版均支持非流式 JSON 和流式 SSE；研究 Agent 使用非流式请求。原生性能字段保留在 `response["metrics"]`，附加统计在 `metrics.telemetry`，流式响应则放在最后的 usage 事件。客户端需保留 OpenAI 标准字段以外的 `metrics`。

TTFT、TPOT/mean ITL 和吞吐量优先使用服务原生字段；缓存命中/查询 Token 来自单请求统计。GPU 利用率及显存是响应完成时已分配 GPU 的共享采样快照，不是任务平均值或峰值。缺失指标不补零。任务级整理规则见[后端指标说明](../backend/README.md#任务指标与前端接入)。服务日志副本位于 TACC 的 `model-server-results/agent-service-<GPU_ID>/requests.jsonl`，正常接入无需读取该文件。

## 独立验收

在已配置课程 TCloud SDK 和公有 proxy 环境的终端，从仓库根目录运行：

```sh
./scripts/verify-model-server
```

脚本提交 [GPU 服务](server/AGENT_DEPLOYMENT_GUIDE.txt)，等待模型就绪，然后向 TACC 提交 [CPU 验收客户端](client/main.py)。客户端验证非流式回答、执行一次工具调用并检查模型能否返回本轮工具生成的随机回执。终端显示队列和作业号，每轮的提交输出、作业日志及时间记录保存在 `runtime/model-server/run-*/`。排队耗时从发起提交到作业脚本启动，包含上传时间；加载耗时截至本机首次观察到就绪。轮询间隔为 20 秒。保持终端运行直至验收结束。

默认在结束时释放作业。要在验收通过后继续使用服务，启动时加 `--keep-server`。从终端或 `run.json` 取本轮地址，在 TACC 内网客户端使用 [交接参数](server/BASE_URL_HANDOFF.txt)。结束后运行 `tcloud cancel -j GPU作业号`。GPU 运行时限为一小时，服务重新提交后需重新获取地址。

只部署 GPU 可在 `model-server/server/` 运行 `tcloud submit`。按作业号查询队列和服务日志：

```sh
tcloud ps -j "$GPU_ID"
tcloud cat "slurm_log/qwen-public-serve-agent-${GPU_ID}.log"
```

独立 Agent 的聊天配置为 `MODEL_PROVIDER=tacc`、`MODEL_BASE_URL=<本轮地址>`、`MODEL_NAME=qwen3.8-27b`、`MODEL_API_KEY=EMPTY`。研究 Agent 使用非流式请求，从完整响应读取工具调用和 token 用量。
