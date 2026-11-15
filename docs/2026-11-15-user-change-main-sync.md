# 用户改动：main 同步到 backend-dev

日期：2026-11-15。归属：user-change，用户发起、Codex 协助。
本记录为新增文件，既有设计、实施和审查记录保持原样。

## 同步范围

将 origin/main 的 fd7fae396d69a496702398e4b1389382654cc111 合并到
backend-dev（合并前 f028e81）。引入研究工作台、账号及用户隔离、
单篇自动预算、跨语言检索与证据覆盖改进，保留 backend-dev 的 evidence API。
Git 自动合并未发生文本冲突。

## 权限兼容处理

旧 evidence API 为单用户环境设计。main 增加登录和论文所有权后，自动合并
仍会留下无鉴权 evidence 路由，因此追加 CurrentUser 依赖，并在读取证据前
复用 get_paper(session, paper_id, user.id) 检查所有权。
未登录返回 401，跨用户论文与不存在论文一致返回 404，不暴露解析状态。
内部 read_evidence 接口保持不变，其他论文接口及账号流程沿用 main。

## 验证

- 新增未登录和跨用户测试，修复前观察到 200/409 而非预期 401/404；修复后通过。
- 原 evidence 测试增加用户身份夹具；登录身份采用依赖覆盖，匿名用真实认证依赖。
- 临时测试环境补齐 main 新增的 argon2-cffi 和 cryptography 依赖。
- 命令：`/private/tmp/evidence-api-venv/bin/python -m unittest discover -s backend/tests`。
- 175 项：113 通过、62 因缺隔离数据库配置跳过；diff 空白检查通过。
- 使用临时 pip 环境，未按 uv.lock 锁定；未迁移本机数据库，未做真实 PostgreSQL、
  模型或浏览器联调，未重新构建前端。

## 运行提示

main 新增数据库迁移至 20261115_0005；实际启动前按 backend/README.md
安装锁定依赖、配置账号服务并执行迁移。此次合并不自动执行数据库迁移。
Agent 函数集成仍等待组员代码，本次未新增 Agent 调用。
本次仅完成本地 backend-dev 合并，不推送远端。

独立审查追加：权限兼容修复未发现重要问题，审查者复跑 7 项 evidence HTTP
测试全部通过；审查不覆盖 main 其他改动，也不替代真实数据库及会话联调。
