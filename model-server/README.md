# 课程 Model Server

在本机完成数据库迁移后，启动现有网页和 TCloud Worker。在侧栏「模型管理」启动课程 Qwen。Worker 在后台提交和检查 GPU 作业，每 30 秒轮询启动进度，就绪后每分钟检查一次。页面每 10 秒刷新，可关闭。就绪后，在「新建研究 → 模型来源」选择「课程模型服务」。作业使用该轮服务地址，检索扩展的 embedding 继续使用百炼。所有登录用户可以使用就绪服务，本轮启动者可以停止它。百炼保留为默认聊天模型。

选择「指定服务地址」可以直接输入同组的 OpenAI 兼容服务 URL，如 `http://10.0.3.10:8000/v1`，也可在模型管理页按账号保存常用地址。每个研究任务保存创建时选定的地址。CPU 作业从该地址的 `/models` 读取模型名；多个模型中优先使用课程 Qwen。服务需支持非流式回答与工具调用。页面只监控和停止本应用提交的作业。手填地址的连通性由 TACC CPU 研究作业实际调用时确认。

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
