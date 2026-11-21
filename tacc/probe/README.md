# TACC API 探测

在 CPU 作业内验证 baseline 依赖能否访问；代码独立，不导入 `agent/apis/`。

| 测试 | 输出与判断 |
|---|---|
| `model` | 百炼普通回答、原生工具调用及回填后的回答 |
| `search` | Tavily 的 arXiv 搜索结果、URL 和摘要 |
| `paper` | arXiv PDF 下载大小、页数及解析正文片段 |
| `database` | Neon TLS 连接与临时表 JSONB 写读，事务结束自动清理 |
| `embedding` | 百炼 `text-embedding-v4`，两条文本的 1024 维向量数量与范数 |

## 配置与提交

```sh
cd tacc/probe
cp .env.example .env
chmod 600 .env
# 填入现有百炼、Tavily、Neon 配置；MODEL_BASE_URL 使用当前可用的工作空间地址。
tcloud submit
tcloud ps -j JOBID
tcloud cat slurm_log/api-probe-JOBID.log
mkdir -p ../runs
tcloud download api-probe/runs/JOBID.json ../runs/api-probe-JOBID.json
```

`.env` 已被 Git 忽略，但 **tcloud 会同步当前目录，包括隐藏文件**；本方案有意将密钥随作业传入，不在日志或报告中输出。不要在这个目录放其他凭据或本地虚拟环境。

当前账号复用已存在的 `acs-network-probe` Python 3.10 环境；`job.sh` 在节点 `/tmp` 中安装独立依赖，退出时清理，不修改原环境。其他账号需先配置可用的 Python 3.10+ 环境。

计算节点实测为 glibc 2.27，probe 使用有兼容预编译包的 [PyMuPDF 1.24.14](https://pypi.org/project/pymupdf/1.24.14/)，并禁止回退到源码编译。本地 agent 的 PyMuPDF 1.28.2 安装在首轮作业中失败，完整 agent 的部署环境需另行对齐。

每项完成后打印结果并更新 `${TACC_USERDIR}/api-probe/runs/JOBID.json`。五项全部通过时最终为 `PASS: 5/5`；某项失败不阻止其他项执行，最终退出码为 1。报告仍为 `running` 或没有最终汇总，表示未完整跑完；只有依赖安装日志时，先检查环境准备。

这是基本连通和功能探测，回答内容可直接人工查看；Neon 临时表不验证业务 schema 权限，embedding 不评价检索质量。

## 代码与复跑

`main.py` 按共用 HTTP 请求、检查函数、结果记录组织。配置通过环境变量或 `--env-file` 传入，作业只负责运行和写文件；外部后端可据同样方式提交作业、查询状态和取回结果。

只重测某项时，在 `tuxiv.conf` 的 entrypoint 后添加 `--only search embedding`。也可本地运行：

```sh
../../agent/.venv/bin/python main.py --only search embedding
```

本地输出默认在 `tacc/runs/probe-local.json`，本地成功不代表 TACC 计算节点成功。避免在同一目录的上一个作业还运行时再次提交，SDK 会覆盖同名远端工作目录。常用平台命令见 [TACC README](../README.md)。

## 外部后端探测（可选）

部署 [最小测试后端](../backend-probe/) 后，在 `.env` 设置 `BACKEND_BASE_URL=https://YOUR_WORKER.workers.dev`。`backend` 检查依次请求 `GET /health`、带中英文 query 的 `POST /search`，再下载并解析结果中的单页 PDF；报告保留 JSON 回显、PDF 页数和正文片段。这是静态测试内容，用于验证 TACC 作业能否访问外部后端。

本地可运行 `../../agent/.venv/bin/python main.py --only backend`。TACC 测试时临时将 `tuxiv.conf` 的 entrypoint 改为 `bash ${TACC_WORKDIR}/job.sh --only backend`，然后按上文提交、查看日志并下载报告；测试完成后恢复默认 entrypoint。默认仍只运行原五项，未配置 `BACKEND_BASE_URL` 不影响它们。

## 最近验证

2026-11-17，CPU 作业 `29397`：`PASS: 5/5`。百炼工具回填后回答 18；Tavily 返回 3 条结果；PDF 共 15 页、解析出非空正文；Neon TLS/JSONB 写读正常；embedding 返回两条 1024 维向量。报告保存在远端 `api-probe/runs/29397.json`，已取回本地 `tacc/runs/api-probe-29397.json`。

同日 CPU 作业 `29413`：`backend` 通过，验证 TACC → Cloudflare Worker 的 HTTPS 健康检查、JSON POST 与 PDF 下载解析。报告为 `tacc/runs/backend-probe-29413.json`；部署地址与说明见 [测试后端 README](../backend-probe/README.md)。
