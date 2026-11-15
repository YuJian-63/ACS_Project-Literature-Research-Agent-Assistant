# 用户改动：原文片段 API 开发与对接记录

归属：user-change，用户发起，Codex 协助实现。日期：2026-11-14。
本文件为新增记录，不替换此前 API 契约和历史实施记录。

## 设计依据

- [已确认设计](superpowers/specs/2026-11-14-user-change-evidence-api-design.md)
- [实施计划](superpowers/plans/2026-11-14-user-change-evidence-api.md)
- 背景：外部 Agent 无法通过 HTTP 分页读取已解析原文。
- 实施范围：papers 路由、显式响应模型及 HTTP 测试；复用内部 read_evidence。

## Agent 对接

API 启动后，先使用论文列表/详情取得 ready 状态的 paper_id，再调用：

```bash
curl 'http://127.0.0.1:8000/api/v1/papers/<paper_id>/evidence?after_index=-1&limit=100'
```

响应结构如下（UUID、哈希和内容为示意）：

```json
{
  "paper_id": "<paper UUID>",
  "paper_sha256": "<64 hex characters>",
  "page_count": 12,
  "parser_version": "<parser version>",
  "items": [{
    "chunk_id": "<chunk UUID>",
    "paper_id": "<paper UUID>",
    "chunk_index": 0,
    "page_number": 1,
    "content": "论文原文",
    "content_sha256": "<64 hex characters>",
    "parser_version": "<parser version>"
  }],
  "has_more": true,
  "next_after_index": 0
}
```

has_more=true 时，将 next_after_index 原样作为下一次 after_index；false 时停止。
chunk_index 从 0 开始，page_number 是从 1 开始的 PDF 物理页码。
游标超出末尾返回空 items、has_more=false，并保持输入游标。
每页 limit 默认 100，允许 1—100；after_index 默认 -1，最小 -1。

错误沿用统一 error 对象：不存在为 404 PAPER_NOT_FOUND；非 ready 为
409 PAPER_NOT_READY；非法 UUID 或查询参数为 422 INVALID_REQUEST。
此接口沿用本机单用户无鉴权边界；不表示完成独立 Agent 服务的结果回传对接。

## 开发过程与验证

- 用户确认设计后新增测试，采用 unittest 和 TestClient，直接运行真实读取函数。
- 临时 SQLite 夹具只用于查询及 HTTP 行为验证，不验证 PostgreSQL 约束和并发。
- 本机无 uv 和后端依赖；临时虚拟环境位于 /private/tmp/evidence-api-venv。
- 使用 pip install -e ./backend 安装 pyproject 允许范围内的依赖，未改变 uv.lock；
  此环境不等价于 uv sync --locked 的锁定环境。
- 验证结果：待执行完成后追加。

### 验证结果追加（2026-11-14）

1. RED：新增接口尚未实现时运行 test_evidence_api.py，观察到路径返回 404，
   OpenAPI 中无对应路径（5 项测试，10 个断言失败、2 个因缺失响应字段导致的错误）。
2. GREEN：增加 EvidenceChunkResponse、EvidencePage 和 papers 路由后，
   新增 5 项测试全部通过，覆盖 104 片段跨页读取、limit=1、末尾/越界空页、
   原文和 hash、物理页码、三种非 ready 状态、404、422 和 OpenAPI。
3. 回归命令：

   ```bash
   /private/tmp/evidence-api-venv/bin/python -m unittest discover -s backend/tests -v
   ```

   结果：39 项中 31 项通过，8 项 PostgreSQL 测试因未配置隔离测试库而跳过。
   未执行真实 PostgreSQL HTTP 验收，未调用模型或 arXiv。
4. 新增代码 diff 空白检查通过。全仓库 diff 检查发现用户已有 README.md
   第 4 行尾随空格，本次遵照要求保留。

无需迁移。启动/重启 API 后可在 /docs 或 /openapi.json 查看新接口。
测试在进程内 ASGI 执行，并非已启动本机监听端口完成实际网络联调。

### 独立审查追加（2026-11-14）

独立审查未发现 Critical/Important 问题；审查者另行运行新增 5 项 HTTP
测试并确认通过。审查确认路由复用、分页、错误处理与响应模型符合设计。
审查同样保留 SQLite 和非锁定依赖环境的验证边界，不将其视为 PostgreSQL 验收。
