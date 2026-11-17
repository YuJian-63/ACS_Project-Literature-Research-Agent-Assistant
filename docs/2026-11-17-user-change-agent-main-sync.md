# 用户改动：同步 Agent main 与对接前检查

日期：2026-11-17。user-change：用户发起，Codex 协助。
新增记录，不覆盖旧版接口分析或历史验收。

## 分支同步

- backend-dev 合并前：f8b7062。
- 获取 origin 后，origin/main 为 01b1fe9，origin/agent-dev 为 24e8a7e。
- 两分支提交不同，但 git diff origin/agent-dev origin/main 为空，文件内容一致。
- main 已合并 Agent，同时包含前端分包、阅读器和搜索体验更新。
- 合并无文本冲突，保留 backend-dev 的 evidence API 和权限检查。
- 后端回归：179 项，117 通过、62 数据库条件测试跳过。
- 环境为此前临时 pip 虚拟环境，非 uv.lock 锁定环境；没有执行数据库迁移或真实外部服务调用。
- 未运行前端构建；未执行 Agent 测试：本机尚无 Python 3.12 / uv。
- 本次完成本地合并，不自动推送。

## 实际调用入口

agent/baseline.py：

```python
def run_task(task: Task | dict, *, model_factory=make_model,
             search=search_web, reader=read_paper_api, persist=False) -> TaskResult:
    ...
```

输入 dict 可直接传入，返回 Pydantic TaskResult，需 model_dump(mode="json") 序列化。
persist=False 不写 Neon。run_task 自身不写 CLI runs 结果文件。
Agent 为 Python >=3.12,<3.13；内部使用顶层 apis/config/schemas 导入，不是可直接
通过 from agent.baseline import run_task 导入的独立命名空间包。

## v1 与此前 v0 的差异

- task_type、budget 均已删除，传入会被拒绝。
- 输入限制改为 max_steps、timeout_seconds、max_output_tokens。
- 不再执行累计 Token、独立工具次数和本地上下文额度限制；不能向前端承诺这些限制仍有效。
- stop_reason 改用 step_limit/time_limit/context_limit 等，详见 agent/agent-io-interface-v1.md。
- 引用版本可能未知，source_id 可能含摘要；不得仅接受带 vN 的固定格式。
- 仍不支持本地 PDF 路径或任意网站 URL。此范围暂缓，不阻塞 arXiv 对接。

## 后续

按 v1 制定后端适配设计，Agent 负责研究功能，后端负责账户、任务状态、
持久化和结果展示。旧研究流程暂不删除，旧结果和记录保持可读。
