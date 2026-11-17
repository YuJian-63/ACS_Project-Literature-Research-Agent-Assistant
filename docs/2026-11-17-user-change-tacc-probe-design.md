# 用户改动：TACC 最小连通测试方案

日期：2026-11-17；user-change。状态：方案草案，未实现HTTP接口或提交平台作业。
依据用户提供的TACC_Toturial.pdf、原始SDK0.4.1和本机课程qwen27b-student-release。
文档中的课堂作业号不是当前可用服务的保证。

## 本次只读检查

- 原始tcloud0.4.1可执行，已有SDK配置可成功执行tcloud ps。
- 本机存在课程qwen-public-serve和qwen-public-client示例。
- server-url.txt仍是http://NODE:8000/v1占位值。
- 项目agent/apis/model.py已有MODEL_PROVIDER=tacc适配。
- 未读取私钥内容、未索取登录密码、未提交或取消作业、未发起模型生成。

## 测试顺序

1. 取得属于本人或组员授权使用的正在运行服务Job ID。
2. 检查状态和服务日志，确认Application startup complete及本次SERVICE_BASE_URL。
3. 在平台CPU SDK作业中发送一条短请求，验证回答、usage和elapsed_seconds。
4. 在计划部署后端/Agent的运行环境中验证同一地址可达，再接入HTTP测试接口。
5. 用现有agent/apis/model.py的probe验证原生工具调用；普通文本成功不代表Agent工具可用。

## 拟新增后端接口（待确认）

POST /api/v1/diagnostics/tacc，沿用登录和CSRF保护。
目标地址、模型名与可选服务密钥由服务端配置；不接收客户端URL，避免成为任意地址请求代理。
固定短问题“37加58等于多少？只输出数字”，低输出上限（如64 Token），关闭thinking，
有限请求超时；返回实际answer、usage、elapsed_seconds和明确的成功/错误状态。
使用OpenAI-compatible /v1/chat/completions，模型标识先核对课程默认qwen3.8-27b。
API不保存账号密码或SSH私钥，不使用TACC网页密码作为模型API key，不创建研究任务。

## 网络边界与约束

指南中的HTTP服务位于计算节点内网，示例由平台CPU作业访问。
不能仅将NODE地址写到Mac的.env就断言本机可访问；需实际验证网络路径。
如果本地不可达，先在平台完成调用；后续选择把后端/Agent部署到平台可达环境，
或在平台明确支持的前提下建立安全转发，不推断SDK私钥可用于任意计算节点SSH。
公共环境由课程维护，不修改公共依赖或模型。
新GPU作业会占用配额，取得明确操作范围后才提交；不取消他人或共享服务作业。
