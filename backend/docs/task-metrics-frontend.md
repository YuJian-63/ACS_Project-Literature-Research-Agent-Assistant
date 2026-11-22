# 任务详情指标：前端接入指南

后端在任务详情中统一返回 `metrics`，前端无需解析 Agent 原始 `trace`，也无需直连 TACC、模型服务或 DeepSeek。本指南用于后续前端接入；本次没有修改前端实现。

## 1. 从哪里获取

| 用途 | 方法与路径 | 说明 |
| --- | --- | --- |
| 当前研究详情页 | `GET /api/v1/agent-research/{task_id}` | 在现有详情对象上新增 `metrics` |
| 旧版任务详情 | `GET /api/v1/tasks/{task_id}` | 返回同一指标结构；其他详情字段与当前接口不同 |
| 完整评分报告 | `GET /api/v1/tasks/{task_id}/evaluation` | 可选；详情中的摘要足够绘制五维评分 |
| 指定版本评分报告 | `GET /api/v1/tasks/{task_id}/evaluation?evaluation_id={evaluation_id}` | 使用摘要中的 ID，避免摘要和报告版本不一致 |
| 用户主动申请评分 | `POST /api/v1/tasks/{task_id}/evaluation` | 无请求体，返回 HTTP 202；可能复用已有版本 |

列表接口不返回指标。统一研究接口仅接受对应类型的任务，旧任务继续使用原有任务详情接口。请求检查登录会话和任务归属，无需传 `user_id`。

生产环境沿用同源 `/api` 反向代理；开发环境沿用 Vite 代理或 `VITE_API_BASE_URL`。跨源时需配置带凭据的 Cookie、CORS 及后端 `FRONTEND_PUBLIC_URL`。不要在浏览器配置模型 API Key 或内部模型地址。

复用 `frontend/src/api/client.ts` 的 `request<T>()`：它携带会话 Cookie，为写请求设置 CSRF 头，并处理退出登录和请求取消。调用前等待现有登录会话初始化。该函数直接返回 JSON 响应体，取值为 `record.metrics`，不是 `response.data.metrics`。

目前 `frontend/src/api/agentResearch.ts` 已有 `agentResearch.record(taskId, signal)`，但 `AgentResearchRecord` 尚未声明 `metrics`。后续需扩展类型并实现展示；仅增加类型断言不会展示指标。

## 2. TypeScript 契约与读取示例

以下可作为后续 `frontend/src/api/taskMetrics.ts` 的内容。权威字段以 `/openapi.json` 中 `TaskMetrics` 和 [后端契约](task-metrics.md) 为准；UUID 和时间在 JSON 中都是字符串。

```ts
export type EvaluationStatus =
  | 'not_requested' | 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped';
export type DimensionKey =
  | 'grounded_correctness' | 'citation_support' | 'task_completion'
  | 'analysis_quality' | 'clarity';

export interface EvaluationMetrics {
  status: EvaluationStatus;
  enabled: boolean;
  configured: boolean;
  evaluation_id: string | null;
  provider: string | null;
  model: string | null;
  rubric_version: string | null;
  prompt_version: string | null;
  error_code: string | null;
  assessment: 'scored' | 'insufficient_evidence' | null;
  overall_score: number | null;
  score_max: number;
  overall_score_max: number;
  weights: Record<string, number>;
  dimensions: Record<DimensionKey, { score: number | null; reason: string | null }>;
}

export interface AgentMetrics {
  available: boolean;
  unavailable_reason: string | null;
  agent_steps: number | null;
  model_calls: number | null;
  tool_calls: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  token_usage_complete: boolean | null;
}

export interface MetricAggregate {
  mean: number | null;
  samples: number;
  source: string | null;
  unavailable_reason: 'NO_SAMPLES' | 'MIXED_SOURCES' | null;
}

export interface CacheTokenMetrics {
  cache_hit_tokens: number | null;
  cache_query_tokens: number | null;
  cache_hit_ratio: number | null;
}

export interface GPUReading {
  uuid: string;
  utilization_percent: number | null;
}

export interface ModelRequestMetrics extends CacheTokenMetrics {
  call_index: number;
  available: boolean;
  request_id: string | null;
  ttft_ms: number | null;
  tpot_ms: number | null;
  mean_itl_ms: number | null;
  tokens_per_second: number | null;
  sources: Record<string, string>;
  gpus: GPUReading[];
  gpu_sampled_at: string | null;
  unavailable_reason: string | null;
}

export interface ModelServerMetrics extends CacheTokenMetrics {
  status: 'available' | 'partial' | 'unavailable';
  unavailable_reason: string | null;
  model_calls_total: number | null;
  observed_model_calls: number;
  measured_model_calls: number;
  cache_measured_model_calls: number;
  cache_usage_complete: boolean;
  cache_unavailable_reason: 'CACHE_USAGE_NOT_AVAILABLE' | 'ZERO_CACHE_QUERY_TOKENS' | null;
  aggregation: string;
  ttft_ms: MetricAggregate;
  tpot_ms: MetricAggregate;
  mean_itl_ms: MetricAggregate;
  tokens_per_second: MetricAggregate;
  gpus: (GPUReading & { call_index: number; sampled_at: string | null })[];
  requests: ModelRequestMetrics[];
  gpu_scope: string;
}

export interface TaskMetrics {
  schema_version: 'task-metrics-v1';
  evaluation: EvaluationMetrics;
  agent: AgentMetrics;
  model_server: ModelServerMetrics;
}
```

后续在原 `AgentResearchRecord` 中增加 `metrics: TaskMetrics`，原 `record()` 封装即可读取。兼容后端未升级的发布窗口时可暂用可选字段，缺失则显示“当前服务未提供指标”；新版后端保证详情包含 `metrics`。

以下独立读取示例等价于现有封装，不需要重复发起两次详情请求：

```ts
import { request } from './client';
import type { AgentResearchRecord } from './agentResearch';
import type { TaskMetrics } from './taskMetrics';

export type ResearchDetail = AgentResearchRecord & { metrics: TaskMetrics };

export function getResearchDetail(taskId: string, signal: AbortSignal) {
  return request<ResearchDetail>({
    url: '/api/v1/agent-research/' + encodeURIComponent(taskId),
    signal,
  });
}
```

## 3. 展示字段映射与单位

下表路径均相对于详情响应的 `metrics`。

| 前端项目 | 字段路径 | 展示口径 |
| --- | --- | --- |
| 事实与证据一致性 | `evaluation.dimensions.grounded_correctness.score` | 0–5 分，原因在同级 `reason` |
| 引用支持程度 | `evaluation.dimensions.citation_support.score` | 0–5 分 |
| 任务完成度 | `evaluation.dimensions.task_completion.score` | 0–5 分 |
| 分析质量 | `evaluation.dimensions.analysis_quality.score` | 0–5 分 |
| 表达清晰度 | `evaluation.dimensions.clarity.score` | 0–5 分 |
| 综合评分 | `evaluation.overall_score` | 后端计算的 0–100 分，前端无需重新加权 |
| Agent 步数 | `agent.agent_steps` | 次 |
| 模型调用次数 | `agent.model_calls` | 次 |
| 工具调用次数 | `agent.tool_calls` | 次 |
| 输入 / 输出 / 总 Token | `agent.input_tokens` / `output_tokens` / `total_tokens` | Token，不含独立评分模型的消耗 |
| TTFT | `model_server.ttft_ms.mean` | ms；同时展示 `samples` 和 `source` |
| TPOT | `model_server.tpot_ms.mean` | ms/token |
| mean ITL | `model_server.mean_itl_ms.mean` | ms；与 TPOT 独立，不互相补值 |
| 生成速度 | `model_server.tokens_per_second.mean` | 输出 tokens/sec |
| 每张 GPU 利用率 | `model_server.gpus[].utilization_percent` | 已是 0–100 的百分数，设备用 `uuid` 标识 |
| 缓存命中 Token | `model_server.cache_hit_tokens` | 有效配对请求的命中 Token 合计 |
| 查询 Token | `model_server.cache_query_tokens` | 同一批请求的 prompt Token 合计，包含缓存命中部分 |
| 缓存命中率 | `model_server.cache_hit_ratio` | 0–1，展示时乘 100 加 `%` |

维度满分、综合满分及权重分别由 `score_max`、`overall_score_max`、`weights` 给出；当前权重依次为 30/30/20/15/5。不要将 0–5 的维度直接画在 0–100 的坐标轴上。

Agent 步数可能小于模型调用次数，规划、反思等也会调用模型。`token_usage_complete=false` 表示普通 Token 统计不完整，不应把缺失值填成 0。

## 4. 详情与异步评分的刷新

研究状态和评分状态互相独立。当前 `ResultPage.tsx` 只在研究 `queued/running` 时每 30 秒刷新；接入指标时应在评分 `pending/running` 期间继续刷新，即使研究已经结束。

在已导入 `ResearchDetail` 的详情页中，可使用以下判断替换原来的研究状态判断：

```ts
export function shouldPoll(record: ResearchDetail): boolean {
  const researchPending = record.status === 'queued' || record.status === 'running';
  const evaluationStatus = record.metrics?.evaluation.status;
  return researchPending || evaluationStatus === 'pending' || evaluationStatus === 'running';
}
```

沿用串行 `setTimeout`：请求结束后，若上述判断为真再安排下一次请求，保留 30 秒间隔即可。避免用可能叠加请求的 `setInterval`。切换任务、退出登录和卸载页面时取消请求及计时器。请求失败后保留已显示的正文和指标，提供手动重试；如自动重试则需退避并遵循 `Retry-After`。

| 评分状态或条件 | 展示建议 | 是否继续为评分轮询 |
| --- | --- | --- |
| `not_requested` | 尚未评分 | 否；研究仍在运行则继续为研究轮询 |
| `pending` / `running` | 等待评分 / 正在评分 | 是 |
| `succeeded` 且 `assessment=scored` | 展示非 null 分值和原因 | 否 |
| `succeeded` 且 `assessment=insufficient_evidence` | 证据不足，无法评分 | 否；不展示为零分 |
| `failed` / `skipped` | 显示状态及 `error_code` | 否；不遮挡研究正文 |

摘要选择最新创建的评分版本。新版本正在评分时，旧版本分数不能冒充本次分数。`enabled/configured` 反映当前配置，历史分数仍可展示。

读取详情和报告不触发模型调用。不要在页面渲染、自动轮询或 `not_requested` 时自动 POST 申请付费评分。

## 5. 主动评分与完整报告

用户明确点击“评分”后，通过现有 `request()` 发起无请求体的 POST：

```ts
import { request } from './client';
import type { EvaluationStatus } from './taskMetrics';

interface EvaluationVersion {
  task_id: string;
  id: string | null;
  status: EvaluationStatus;
}

export function requestEvaluation(taskId: string, signal: AbortSignal) {
  return request<EvaluationVersion>({
    url: '/api/v1/tasks/' + encodeURIComponent(taskId) + '/evaluation',
    method: 'POST',
    signal,
  });
}

export function getEvaluationVersion(
  taskId: string, evaluationId: string, signal: AbortSignal,
) {
  return request<EvaluationVersion & { report: Record<string, unknown> | null }>({
    url: '/api/v1/tasks/' + encodeURIComponent(taskId) + '/evaluation',
    params: { evaluation_id: evaluationId },
    signal,
  });
}
```

这里的类型仅列出示例所需字段；完整响应是 OpenAPI `EvaluationResponse`，报告内容见 [评分文档](deepseek-evaluation.md)。完整报告的版本字段叫 `id`，详情摘要中叫 `evaluation_id`。

收到 202 后立即重新读取详情，重新启动上一节轮询；此时研究可能已完成。202 表示受理或复用已有版本，不表示评分成功。提交请求期间禁用按钮，避免重复点击。每用户每天默认允许 50 个新评分版本；复用与重试按后端判断，不在前端自行扣额度。

## 6. 缺失值、部分采集与口径

- `null` 展示为 `—` 或“未采集”，不能用 `value || 0`。真实的 0 Token、0% 缓存命中率和 0% GPU 利用率应正常展示；先判空再格式化。
- `model_server.status=partial/unavailable` 不代表研究失败。按字段展示已有数据，不要按这个总状态隐藏所有指标。
- 性能均值仅针对相同 `source` 的有效请求。`samples=0` 时无均值；`MIXED_SOURCES` 时可查看 `requests[]`，不要跨口径求平均。吞吐量不是整个服务的吞吐量。
- GPU 为模型响应完成时、已分配设备的最近利用率快照，可能包含其他进程。展示 `sampled_at` 和 `call_index`，不要称为任务平均值或实时利用率。空数组代表未报告，不能推断 GPU 数量。
- `cache_usage_complete=false` 时，只覆盖 `cache_measured_model_calls` 个有效配对请求，应标为“部分采集”。`model_calls_total` 可作已知总数；总数未知时不展示覆盖百分比。
- 缓存查询 Token 是有效缓存统计请求的 prompt Token，不是用户问题的字数，也不是缓存未命中 Token。缺失配对请求不加入分母，因此可能小于 `agent.input_tokens`。
- 缓存命中率为 `sum(cache_hit_tokens) / sum(cache_query_tokens)`，直接展示后端结果。两次请求 20/100 和 720/900，任务为 740/1000 = 74%，不是 50%。分母为 0 时比例为 null；缺少统计时三个值都为 null。
- `agent.token_usage_complete` 与 `cache_usage_complete` 含义不同。独立评分模型的消耗不计入 Agent 及模型服务指标。

以下 JSON 仅为展示字段的响应片段，省略其他必返字段，不可作为完整响应类型：

```json
{
  "metrics": {
    "schema_version": "task-metrics-v1",
    "evaluation": { "status": "pending", "overall_score": null },
    "agent": {
      "agent_steps": 4,
      "model_calls": 5,
      "input_tokens": 1200,
      "token_usage_complete": true
    },
    "model_server": {
      "status": "partial",
      "model_calls_total": 5,
      "cache_hit_tokens": 740,
      "cache_query_tokens": 1000,
      "cache_hit_ratio": 0.74,
      "cache_measured_model_calls": 2,
      "cache_usage_complete": false,
      "gpus": []
    }
  }
}
```

此例应显示“评分等待中”“缓存命中 740 / 查询 1000 Token，命中率 74%，部分采集 2/5 次”，GPU 未采集；不能将 74% 解读为完整任务命中率。

## 7. 错误与联调检查

| 情况 | 处理 |
| --- | --- |
| 401 | 交给现有封装处理会话过期；清除当前用户页面数据 |
| 404 `TASK_NOT_FOUND` | 任务不存在、类型不符或无权访问 |
| 404 `EVALUATION_NOT_FOUND` | 指定评分版本不存在；刷新详情核对 ID |
| 409 `EVALUATION_NOT_READY` | 暂无可评分的 Agent 结果 |
| 409 `EVALUATION_ATTEMPTS_EXHAUSTED` | 评分重试次数已耗尽，展示提示 |
| 429 `DAILY_EVALUATION_LIMIT` | 当日新版本额度用完，不循环 POST |
| 503 `EVALUATION_NOT_CONFIGURED` | 评分未启用或未配置，保留研究结果 |
| 超时、网络错误、其他服务端错误 | 保留正文及最近成功指标，提供手动重试 |

评分 POST 失败不等于详情读取失败。调试可记录 `ApiError.requestId`；不要记录 Cookie、CSRF Token、模型密钥，也不要将任务响应跨用户保存在共享 localStorage 缓存中。

联调顺序：

1. 登录后在 Network 查看详情响应，确认 `metrics.schema_version=task-metrics-v1` 及三个指标分组；列表无指标是正常现象。
2. 排队/运行任务允许空值；研究成功后展示正文及可用用量。切换任务、退出登录不串数据。
3. 后端评分配置完成且独立评分 Worker 运行后，通过明确授权的评分操作核对各状态，确认研究结束后仍能刷新评分。
4. 验证无遥测旧任务：允许 Token 或评分存在，但性能与 GPU 缺失。采集包装仅安装到新暂存的 TCloud 作业，历史遥测无法补造。
5. 分别验证真实 0 值、全缺失、部分缓存覆盖及零分母。缓存可能可用而时延/GPU 不可用，取决于上游返回的数据。

详情 GET 只读数据库，不主动轮询 GPU 或 TACC。指标随结果回传后出现，不是执行中的实时监控。刷新不能补齐上游从未返回的字段。部署、采集来源及后端测试见 [完整契约](task-metrics.md#capture-and-deployment)。
