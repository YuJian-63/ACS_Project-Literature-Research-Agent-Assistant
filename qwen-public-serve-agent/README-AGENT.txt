# 公有 Agent 服务包

这是一个可复制到部署者自己电脑上的独立服务包，不要求使用本项目的本地路径。

部署者把 ZIP 解压到自己的目录，并执行：

```bash
export SERVICE_DIR=/部署者自己电脑上的/qwen-public-serve-agent
cd "$SERVICE_DIR"
tcloud submit
```

完整流程见 `AGENT_DEPLOYMENT_GUIDE.txt`。
模型名固定为 `qwen3.8-27b`，服务成功后只把日志中的 `AGENT_BASE_URL` 发给 Agent 同学：

```text
http://10.0.x.x:8000/v1
```

原始公有模板保持只读，私有优化目录不参与本服务。
