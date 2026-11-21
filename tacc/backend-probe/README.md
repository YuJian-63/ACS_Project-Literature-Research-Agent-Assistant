# 外部后端连通性测试

一个最小 Cloudflare Worker，供 TACC CPU 作业验证 HTTPS、JSON POST 和 PDF 下载。搜索结果与单页 PDF 都是固定测试数据，不调用外部 API，不需要业务 API key。

| 接口 | 返回 |
|---|---|
| `GET /health` | 服务标识与 `ok: true` |
| `POST /search`，JSON `{"query":"attention 注意力"}` | 原查询及固定搜索结果，`mock: true` |
| `GET /paper.pdf` | 正文含 `TACC backend probe` 的单页 PDF |

## 本地与部署

使用 Node.js 22.12+。

```sh
cd tacc/backend-probe
npm ci
npm run dev
```

`npm run check` 只检查打包，不发布。

首次部署在本机完成浏览器授权，再发布到 `workers.dev`：

```sh
npx wrangler login
npm run deploy
```

使用部署输出中的 HTTPS 地址配置 `BACKEND_BASE_URL`，按 [probe 说明](../probe/README.md) 运行 `--only backend`。本地也可以使用 `http://127.0.0.1:8787` 联调。

`src/index.js` 集中放置三个路由，`src/paper.pdf` 是随代码打包的测试文件。这里只验证 TACC → 外部 HTTP 服务；正式后端和运行 `tcloud` 的作业提交器另行设计。

## 验证结果

2026-11-17，后端已部署到 [workers.dev](https://acs-tacc-backend-probe.acs-tacc-backend-probe.workers.dev/health)。TACC CPU 作业 `29413` 主动请求三个接口，检查通过；PDF 为 1151 字节、1 页，正文解析正常。报告见 `../runs/backend-probe-29413.json`，日志同名 `.log`。

首轮 `29412` 遇到连接失败，同期本机为 TLS 握手失败；新域名启用几分钟后未改代码即恢复，复测通过。本机仅用于部署、提交作业和取回结果，测试服务实际运行在 Cloudflare。
