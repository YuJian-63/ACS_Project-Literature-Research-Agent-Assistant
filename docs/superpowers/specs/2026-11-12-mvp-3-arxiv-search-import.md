# MVP-3：arXiv 搜索与受控导入设计

日期：2026-11-12。总体方案已获用户确认；本文为待实施设计，不表示接口、迁移或 Worker 已实现。MVP-2.1 的实际模型及原生 PostgreSQL 验收暂缓，不改写为已通过。

## 1. 目标与边界

关键词搜索 → 查看 arXiv 结果 → 导入指定版本 PDF → 现有 Parser Worker 解析 → 选择 ready 论文创建研究任务。

- arXiv 单源，不接任意网页、任意 URL、OCR、Planner/Reflection 或向量数据库。
- 下载由独立 Import Worker 执行，不依赖 API BackgroundTasks；API 重启不丢 queued 导入。
- 导入成功不等于解析成功；研究任务保留 ready 前置条件。
- 不改变手动上传允许相同内容不同 Paper ID 的行为，不合并已有论文或修改已被引用的文件。
- 搜索/导入不调用模型；假上游测试不能冒充真实 arXiv 验收。

## 2. 标识与搜索

provider 固定 arxiv。external_id 最长 80 字符，必须带正整数版本 vN；支持 `1706.03762v7`、`hep-th/9901001v3` 等新旧标识。拒绝 URL、无版本 ID、编码斜线、路径穿越、查询串。导入身份为规范化的 `(provider, external_id)`，不同版本不合并。

q 去首尾空白、合并内部空白后 1—200 字符/最多 20 词，拒绝 NUL/控制字符。普通关键词，不开放原始高级语法：词逐个转义为 `all:"词"`、以 AND 连接，通过 HTTP 参数编码。相关度降序，limit 默认 10/范围 1—20，offset 默认 0/范围 0—1000。

固定官方 API 请求；Atom XML 解码后上限 2 MiB。拒绝 DTD/实体声明、错误 feed、异常 XML、非法 ID/时间戳、超长字段和异常结果数量，不能把错误当作空结果。字段上限：title 2000 字符，abstract 20000，authors 200 项/每项 300，categories 50 项/每项 64，doi 可空/512。入库文本拒绝 NUL/无效 UTF-8。

SearchPaper 字段：provider、external_id、title、authors、abstract、doi、categories、published_at、source_updated_at、abstract_url、pdf_url；额外包含当前本地可空 import_id/import_status/paper_id/paper_status。URL 从受校验 ID 生成，不使用 feed 或客户端下载链接。搜索结果不写 papers。

成功上游搜索结果按规范化 q/limit/offset 缓存，TTL 600 秒、每进程最多 100 页；每次响应重新查询本地导入/解析状态。失败不缓存；多进程未命中必须经过同一数据库限流。

## 3. 接口与明确重试

API 细节见契约第 10 节：

- GET /api/v1/paper-search：外部搜索，与现有本地 papers?q 分离。
- POST /api/v1/paper-imports：仅 provider/external_id；自然键去重并返回同一记录，不接收客户端元数据或 URL。
- GET /api/v1/paper-imports 及 /{id}：持久化列表/详情，支持刷新恢复。
- POST /api/v1/paper-imports/{id}/retry：接收严格正整数 expected_attempt。

首次 attempt=1。普通 POST 永不重试 failed。仅 failed 且 error.details.retryable=true 可在 expected_attempt 匹配时原子加 1 回 queued。若实际 attempt=expected_attempt+1，直接重放当前记录，即使它已再次失败，也不发起第三次下载；更旧请求 409。重试清空旧执行字段，不改变 ID/来源/created_at。

queued/running 返回 202，终态复用返回 200。无自动网络重试或失败自动入队。下载成功但解析失败仍为 Import succeeded/Paper failed，不能用导入重试覆盖文件。

## 4. 数据与兼容

revision 20261112_0002 在 20261110_0001 后增加 paper_sources、paper_imports、source_request_gates 三表，字段/约束见数据库设计第 9 节。原七表历史、Paper 四态和任务引用约束保持。

Import：queued → running → succeeded/failed，仅显式重试 failed → queued。queued/running 不发布 Paper。完成事务同时创建 Paper(status=uploaded)、PaperSource、Import succeeded；之后 Parser 推进 uploaded → processing → ready/failed。

来源按版本唯一，DOI 不唯一；计算 SHA-256 但不据此合并手动上传或不同版本。Source 保留完整标题；Paper.title 确定性取前 255 字符；文件名从 ID 生成安全 .pdf 名，旧 ID 的斜线不能进入文件路径。PaperResponse 增加可空 source，手动上传为 null。

## 5. 访问节奏与安全

- ARXIV_ENABLED 默认 false；启用时配置 ARXIV_CONTACT_EMAIL，用于可识别 User-Agent。这是本项目配置要求，不宣称 arXiv 强制注册。
- API 固定 `https://export.arxiv.org/api/query`；PDF 固定 `https://arxiv.org/pdf/{external_id}`。不增加生产 base_url 或任意 URL 参数。
- API/Import Worker 共用数据库 arxiv gate：一个在途请求，完成后至少 3 秒才发下一次。申请/释放许可使用短事务与每次 UUID token；不得跨网络持锁，也不能仅用进程内 sleep。
- PDF 同样经过 gate。搜索遇忙返回 429/Retry-After，不占住 API 排队等待；导入在总时限内等待。上游 429/503 的 Retry-After 合并至共享冷却，秒数/HTTP 日期限制 3—86400 秒，无有效值默认 60 秒。
- permit 租约 120 秒；过期许可回收额外留足 3 秒；释放须匹配 token 并先关闭连接。元数据总超时 20 秒、PDF 全链路 90 秒、连接/读取各 5 秒。
- 使用受监督的网络子进程保证完整 wall-clock 超时，支持停止/所有权丢失时终止；仅设置 socket timeout 不够。测试注入 fake transport，不为生产开放本地/任意主机。
- httpx 禁用环境代理继承、自动重试和自动重定向。API 重定向失败；PDF 最多人工跟随 2 次，每跳重新校验并经 gate，仍受同一 90 秒期限限制。
- PDF 每跳仅允许 HTTPS/443、arxiv.org/export.arxiv.org、同版本 `/pdf/{external_id}`（可附 .pdf）；拒绝 userinfo/query/fragment、其他主机、路径或版本。不得跟随 feed 的第三方 URL 或绕过访问限制。
- 流式 PDF 最大 20 MiB，实际字节计数与头部预检查结合，必须以 %PDF- 开头；不能只信 Content-Length。临时/最终路径均由服务器生成。

## 6. Worker、事务与补偿

命令 `python -m app.import_worker`。SKIP LOCKED 领取，Import 租约 30 秒/心跳 10 秒，尝试总时限 180 秒、不含排队；超时/租约过期/停止进入 failed，不自动重试。恢复由 Worker 启动及循环执行，不依赖 API 重启。时间用数据库时钟；写回匹配 owner/attempt/运行态/有效租约。

1. 领取后重新按明确版本取官方元数据；不存在或返回版本不符即失败，不悄悄换最新版本。
2. 受控临时文件包含 import_id/attempt；网络在事务外执行，下载校验、hash、fsync 后才完成。
3. 固定 Paper UUID=Import UUID。短事务重锁并检查 fencing，安全移动到 uploads/{UUID}.pdf，原子创建 Paper+Source+Import 成功。不能直接调用自行 commit 的 save_paper 导致半成品；仅最小化复用安全 staging/path 原语。
4. 文件系统与数据库不能真正原子提交：确定回滚且无引用才清理本尝试；commit 不确定时用新 Session 按 Import/Paper/Source/hash 对账。无法确定时保留，不盲删、不再下载、不覆盖已有引用文件。
5. 旧 Worker 不得发布/清理获胜尝试的文件或写成功；下载失败不留下 Paper/Source，也不产生研究 Artifact/Citation。

仅记录受控错误码/用户消息/安全 details，不回显上游正文、内部路径、请求头或凭据。区分导入失败与导入成功但解析失败。

## 7. 前端

新增 /papers/search，“搜索论文”进入桌面/移动导航，沿用现有布局/Ant Design/Axios，不重做设计系统。手动提交关键词和翻页，不按键联网、不自动导入整页。展示纯文本标题/作者/摘要/版本/日期和原站链接。

单条导入防连点，展示排队/下载/已导入；失败仅 retryable=true 显示显式重试。进入页面读取持久化导入列表；queued/running 每 2 秒轮询，终态停止、离开清理定时器/请求；成功后跟踪 Paper 解析状态，真正 ready 才能加入研究任务。旧搜索响应不能覆盖新关键词；处理空结果、429 倒计时、关闭/离线、版本不存在、超限、解析失败。保留本地论文搜索、上传及现有研究流程。

## 8. 验收与用户操作

覆盖 ID/版本/XML/大小/重定向、缓存本地状态新鲜度、跨实例 gate、并发去重、快速失败后的 retry 重放、重启/恢复、lease/attempt fencing、回滚/commit 不确定补偿。浏览器覆盖搜索→导入→解析→选择论文，以及刷新恢复、移动端和既有上传回归。

沿用 ignored runtime 验证，不顺带完成 MVP-2.1 正式测试体系。fake arXiv/隔离数据库提供确定性集成；另做一次小规模真实搜索/版本下载。PGlite 与原生 PostgreSQL 并发证据分开；无模型只声称 Mock 创建流程，不声称实际模型验收。

需用户操作时逐项指导：申请文档/代码写入和联网授权；原生数据库验收前再启动 Docker；真实上游启用前本地填写联系邮箱，不粘贴密钥。仅用户要求时 commit/push。

## 9. 官方依据

2026-11-12 只读核对 API 参数/Atom/版本：`https://info.arxiv.org/help/api/user-manual.html`；访问节奏与单连接条款：`https://info.arxiv.org/help/api/tou.html`。

字段/大小/缓存/超时/邮箱/重试数值为本项目保守设计，不冒充上游保证。研究使用应遵守内容许可，不声称所有论文可任意再分发。
