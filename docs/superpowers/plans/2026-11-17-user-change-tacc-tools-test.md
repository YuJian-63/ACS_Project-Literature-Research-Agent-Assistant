# 用户改动：TACC→Mac 后端工具测试计划

用户已确认Mac部署及临时HTTPS隧道+认证；确认使用其指定联系邮箱向arXiv标识请求。
本次为工具HTTP测试，不启动模型、不申请GPU、不发送邮件、不修改Agent。

- [ ] 编写标准库CPU测试客户端：健康检查、未认证401、已认证检索、导入轮询、下载PDF头/hash核对。
- [ ] 建立只允许指定工具路径的临时ASGI入口，保留真实会话与CSRF；测试路径隔离。
- [ ] 建立独立PostgreSQL和测试会话；个人.env除授权的ARXIV_CONTACT_EMAIL外不改。
- [ ] 从官方获取临时隧道工具，开启HTTPS入口，核对匿名请求无法读取工具数据。
- [ ] 提交一个1CPU/0GPU/10分钟TACC作业；凭据不写日志或提交Git。
- [ ] 保存脱敏证据，停止本次作业/隧道/服务，撤销测试会话，清理云端凭据。

接口复用：GET /api/v1/paper-search，POST/GET /api/v1/paper-imports，GET /api/v1/papers/{uuid}/file。
下载是先导入再读取本地文件，不假装已有按arXiv ID同步下载的独立接口。
使用Cloudflare临时HTTPS转发，仅作本次测试，不修改路由器或建立永久公网服务。

## 执行结果追加

2026-11-17：全部步骤执行。TACC作业29438成功，检索与PDF下载200、匿名检索401。
PDF1121039字节，SHA-256与Mac下载一致。首次29435失败经29436定位为默认CA缺失，
用现有certifi后重试成功，全程保持TLS校验。CPU作业均不申请GPU。
隧道及本地测试进程已停止，会话撤销，隔离数据库与本地凭据已清理，脱敏证据保留。
详情：docs/2026-11-17-user-change-tacc-backend-tools-test.md。
