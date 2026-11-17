# 用户改动：TACC 调用 Mac 后端工具验收

日期：2026-11-17；归属 user-change；新增记录，不覆盖之前的模型测试设计。

## 测试目标与结论

本次实际验证 TACC CPU 作业 → Cloudflare 临时 HTTPS 隧道 → Mac 后端的
检索、论文导入和 PDF 下载流程。不是模型推理或 Agent 端到端研究验收。
用户明确同意 Cloudflare 处理15分钟测试会话、检索请求及公开PDF内容。
arXiv联系字段采用用户本次明确指定的邮箱，仅保存在私有.env及临时配置中，不写入本记录。

成功作业：29438。申请1CPU、0GPU、最长10分钟，实际工具流程1.89秒。

| 操作 | 结果 |
| --- | --- |
| GET /health | 200 |
| 未认证 GET /api/v1/paper-search | 401 |
| 带测试会话检索 | 200 |
| POST /api/v1/paper-imports | 200（复用本机预验证时已完成的导入） |
| GET /api/v1/paper-imports/{id} | 200 |
| GET /api/v1/papers/{paper_id}/file | 200，PDF文件头验证通过 |

下载论文：2512.19700v1。文件1121039字节。
SHA-256：`e547d220338713fedba09803daccb05a7f023a198d172f585611a3c82f71d89f`。
从TACC下载的结果JSON与本机HTTPS预验证文件大小、哈希相同。
本机预验证首次从arXiv导入时返回202；TACC完整测试走已导入文件，不声称TACC触发了第二次上游下载。

## 实际接口与认证

- 检索：GET /api/v1/paper-search?q=...&limit=3，响应items包含版本化external_id。
- 导入：POST /api/v1/paper-imports，JSON为provider=arxiv及external_id。
- 轮询：GET /api/v1/paper-imports/{id}，succeeded后取paper_id。
- PDF：GET /api/v1/papers/{paper_id}/file，下载实际PDF字节。
- 使用普通测试用户的会话Cookie；POST附带Origin和X-CSRF-Token。
- 复用正式接口的登录和用户归属检查，没有添加匿名工具访问或管理员权限。
- 下载并非一个直接接受arXiv ID的同步接口，Agent接入时需处理导入/轮询/下载步骤。

## 测试代码

- backend/src/app/tools_probe.py：临时工具路径白名单，create_app从私有TACC_PROBE_CONFIG读取隔离配置。
- backend/checks/tacc_tools_client.py：标准库客户端、HTTPS校验、拒绝重定向、响应大小限制和脱敏结果。
- backend/checks/tacc_tools_job.sh：平台CPU作业入口，设置CA包并退出清理会话文件。
- backend/tests/test_tacc_tools_gate.py、test_tacc_tools_client.py：15项定向测试通过。

正式业务API未修改；白名单入口不开放登录、注册、任务、用户列表或API文档。
测试数据和凭据使用Git忽略目录backend/runtime，密码/Cookie/CSRF不写入日志或文档。

## 遇到的问题与修复

1. tcloud原先已认证，但本账户没有proxy环境。执行课程原始setup-sdk-account.sh注册共享环境。
   脚本没有安装公共模型依赖；提交时SDK仍会例行检查任务environment。
2. 客户端初稿CSRF字段名与真实接口不符。增加正确X-CSRF-Token断言后观察失败，再修复并通过。
3. 作业29435在首次HTTPS健康请求失败，未进入认证。无凭据诊断作业29436确定：
   课程Python找不到默认CA文件，SSLCertVerificationError，verify_code=20。
4. 重试脚本设置SSL_CERT_FILE为课程环境现有certifi.where()，作业29438成功。
   没有禁用TLS验证，没有改公共环境，也没有将原因误判成后端认证错误。
5. 自动审批最初拒绝隧道：尚未明确授权Cloudflare具体第三方处理测试认证数据。
   用户补充明确授权后才重试建立，未绕过审批。

## 资源与后续

测试完成后撤销全部测试会话、删除本地会话文件，关闭临时隧道、工具API、Import Worker和隔离数据库。
平台作业脚本通过EXIT trap清理private.json；独立检查远端相对目录未成功，
因此不将其描述为独立验证过的远端文件删除；会话已在数据库端撤销，不再有效。
测试没有启动GPU/模型服务，没有发送邮件，没有改动个人数据库连接或TACC私钥。
课程账号的proxy注册保持可复用，不擅自删除账号环境。
隧道地址是临时的，关闭后不能继续使用，不应写成正式后端地址。

完整后端回归：162 passed、64 skipped、62 subtests passed。跳过项未被当作已验收。
独立只读审查未发现测试入口/客户端的重要问题。
下一步是将Agent检索/读取工具适配这些接口并管理短期凭据；本次未修改Agent代码。
