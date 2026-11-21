# TACC 参考入口

本目录保留老师 2026-11-05 提供的两份发布包及独立 API 探测脚本。两个包从 Git `alpha` 快照原样取出，当前不修改或部署。

| 入口 | 用途 |
|---|---|
| [Public 发布包](qwen27b-student-release/README.md) | 默认路线，复用平台环境和模型，开发调用客户端 |
| [Private vLLM 发布包](qwen27b-private-vllm-student-release/README.md) | 修改 vLLM Python 源码时使用，先构建再启动服务 |
| [探测工具](probe/README.md) | CPU 作业内访问百炼、Tavily、arXiv/PDF、Neon 与 embedding |
| [测试后端](backend-probe/README.md) | Cloudflare Worker；供 TACC 作业测试 JSON 请求和 PDF 下载 |
| [Tunnel 探测](tunnel-probe/README.md) | CPU 作业通过 Cloudflare Quick Tunnel 从本机后端下载并解析 PDF |

## 常用 tcloud 命令

以下按本机 `tcloud 0.4.1` 整理，路径相对远端 `TACC_USERDIR`，`JOBID` 替换为提交返回的编号。

```sh
tcloud config -u YOUR_USERNAME                 # 首次配置账号
tcloud config -f /absolute/path/to/private.key # 首次配置私钥路径
tcloud init                                   # 首次初始化
tcloud env ls                                 # 查看已有环境
tcloud submit                                 # 使用当前目录 tuxiv.conf 提交
tcloud ps                                     # 查看队列
tcloud ps -j JOBID                             # 查看指定作业
tcloud ls slurm_log                            # 列出日志
tcloud cat slurm_log/api-probe-JOBID.log        # 查看 probe 日志
tcloud download api-probe/runs/JOBID.json ./result-JOBID.json
tcloud upload LOCAL_PATH REMOTE_DIRECTORY     # 上传到持久目录
tcloud cancel -j JOBID                         # 取消指定作业
```

提交会同步当前目录，包括隐藏文件；Git 忽略规则不影响上传。`TACC_WORKDIR` 是可被再次提交覆盖的运行目录，`TACC_USERDIR` 用于保存结果。作业从队列消失不等于成功，应查看最终日志和结果文件。

当前按外部后端提交、查询与取回结果，TACC worker 在作业内出站调用 API 的方式设计，不依赖 SSH 或外部连接 worker 端口。CPU 作业 `29413` 已验证 TACC → Cloudflare Worker 的 HTTPS/JSON/PDF 连通性；正式后端与 `tcloud` 作业提交器仍待实现。本次由本机提交作业，Cloudflare Worker 只提供测试接口。

## 发布包约定

先启动 GPU service job，等服务就绪并取得本次地址，再提交独立 CPU client job。客户端在平台内部访问服务；服务重启后需更新地址。教程里的 `PROJECT_DIR` 指具体发布包的根目录。

| 配置 | 发布包中的值 |
|---|---|
| API 模型标识 | `qwen3.8-27b` |
| 接口与限制 | `/v1/chat/completions`；32K context、并发 4、text-only |
| Service job | 2 GPU、8 CPU、1 小时 |
| Client job | 1 CPU、10 分钟；HTTP 请求超时 300 秒 |
| Private 源码 | vLLM v0.26.0，使用匹配的预编译扩展 |
| 文件位置 | `TACC_WORKDIR` 用于作业同步与执行；`TACC_USERDIR` 保存持久结果 |

以上是发布包配置。实际 checkpoint、精度、并行方式和运行效果在接入时核实。

## 与项目的关系

拟由 client job 运行 `agent/` 的 worker；源码同步、依赖和 backend 作业桥接尚待实现。现有 `qwen_client.chat()` 仅封装非流式文本应答，后续需要适配工具调用；示例的 `elapsed_seconds` 是完整请求耗时，TTFT/TPOT 需另行采集。

整体连接方式见 [TACC 联调说明](TACC.md)，研究循环见 [Agent workflow](../agent/workflow.md)。
