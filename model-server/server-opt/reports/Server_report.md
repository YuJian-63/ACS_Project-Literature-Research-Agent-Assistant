# Qwen vLLM Model-Server Experiment Report

## 1. Scope and final conclusion

This project studies the single-request and concurrent inference performance of Qwen3.8-27B-AWQ-INT4 deployed as a vLLM model server on TACC. We keep the model, GPU type, request data, and quality checks consistent while evaluating the effects of service configuration, the attention backend, GDN state access, GPU N-gram speculative decoding, and the chunked-prefill scheduling budget on inference.

The final submission setting is **C=4 concurrency with `max_num_batched_tokens=8192`**. It is a throughput-oriented tradeoff for concurrent workloads, not a guarantee of lower latency in every scenario. In this study, 8192 slightly improved TPOT and request throughput over 4096, while TTFT increased noticeably and end-to-end latency improved only slightly. This setting fits our workload, which generally uses relatively large contexts.

The conclusions are:

1. vLLM concurrency approximately doubles request throughput, but increases TTFT, TPOT, and queue time. It performs well for multi-request workloads.
2. In chunked prefill, choosing a relatively large `max_num_batched_tokens` allows vLLM to process more tokens in one scheduling iteration and improve prefill processing. With sufficient GPU resources, this can improve throughput, but it also increases TTFT. `max_num_batched_tokens=8192` is the throughput-oriented configuration selected from our comparison.
3. GDN indexed-state directly locates and reads/writes each request's GDN state to reduce state movement. In our experiment, the method was ineffective, likely because its additional end-to-end overhead exceeded the saved data-movement time.
4. GPU N-gram speculative decoding predicts candidate tokens and validates multiple tokens at once, reducing serial decode iterations in principle. In our workload, the overall run became slower, so the extra overhead exceeded the speculative-decoding benefit.
## 2. System, Service, and Dataset

### 2.1 Service environment

- Model: Qwen3.8-27B-AWQ-INT4
- vLLM: 0.26.0
- PyTorch: 2.11.0+cu128
- Transformers: 5.10.4
- Triton: 3.6.0
- Hardware: two NVIDIA RTX 3090 GPUs, tensor parallel size 2
- dtype: bfloat16
- `max_model_len=36864` (combined input/output context; benchmark request bounds: 32767 input tokens and 4096 output tokens, not independent server limits)
- `max_num_seqs=4`
- `gpu_memory_utilization=0.9`
- `enable_prefix_caching=true`
- default attention backend: `auto`, which selected FlashAttention v2
- Service interface: OpenAI-compatible `/v1/chat/completions`
### 2.2 Test Data

The long-input data uses the serial `serial-long-copy-boundary-v2` protocol and its concurrent quick-screen version. The tasks are long-document quotation, field extraction, and complete-record copying; the old arithmetic-question protocol is no longer used. The complete serial protocol has four rounds of six questions, for 24 formal requests. The concurrent protocol has two rounds of four requests, for 8 requests. Single-request serial and concurrent workloads are measured separately.
### 2.3 Metrics

The recorded or calculated metrics include TTFT, TPOT, end-to-end latency, output tokens/s, requests/s, input/output/total tokens, prefix-cache queries and hits, prefix-cache hit rate, computed prefill tokens, prefill time, queue time, and preemption count.

## 3. Experimental results

### 3.1 Serial Single-Request and Prefill-Budget Screening

The E00 quick control at 4096 passed 8/8 requests with 32.158 s mean E2E, 5.748 s TTFT, and 16.282 ms TPOT. The same quick workload was then tested with 2048, 4096, and 8192:

| `max_num_batched_tokens` | CPU job | E2E (s) | TTFT (s) | TPOT (ms) | Interpretation |
|---:|---:|---:|---:|---:|---|
| 2048 | 30456 | 32.175 | 5.758 | 16.284 | Close to 4096; no TPOT gain |
| 4096 | 30451 | 32.158 | 5.748 | 16.282 | Serial baseline |
| 8192 | 30463 | 32.422 | 5.852 | 16.380 | Slightly slower in serial mode |

The serial single-request experiment shows that increasing the budget does not automatically reduce single-request latency. With only one request, there is little competition for GPU scheduling resources, so the available optimization space is limited.

### 3.2 Concurrent Baseline

| Concurrency | Job | E2E (s) | TTFT (s) | TPOT (ms) | requests/s | output tok/s | Prefix hit |
|---:|---:|---:|---:|---:|---:|---:|---:|
| C=1 | 30909 | 32.429 | 5.970 | 16.312 | 0.03079 | 49.94 | 0.4833 |
| C=4 | 30912 | 57.120 | 17.030 | 25.026 | 0.06442 | 104.49 | 0.5356 |

C=4 achieves approximately 2.09 times the C=1 request throughput, but first-token and per-token latency increase for individual requests. vLLM provides continuous batching, which can improve request completion throughput substantially and process multiple requests at the same time when GPU resources are sufficient.

### 3.3 C=4 Chunked-Prefill Experiment

| Budget | Job | E2E (s) | TTFT (s) | TPOT (ms) | requests/s | output tok/s | Prefill (s) | Queue (s) | Prefix hit |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2048 | 30919 | 63.803 | 16.512 | 29.343 | 0.05772 | 93.62 | 61.863 | 7.753 | 0.5065 |
| 4096 | 30912 | 57.120 | 17.030 | 25.026 | 0.06442 | 104.49 | 70.000 | 6.159 | 0.5356 |
| 8192 | 30928 | 56.661 | 22.012 | 21.432 | 0.06510 | 105.60 | 102.249 | 4.993 | 0.5781 |

Relative to C=4/4096:

- 2048: E2E +11.70%, TPOT +17.25%, requests/s -10.41%.
- 8192: E2E -0.80%, TPOT -14.36%, requests/s +1.06%, but TTFT +29.25%.

The effect of 8192 should be understood as a scheduling tradeoff. A larger per-iteration token budget allows the scheduler to process more prefill work at once, reducing interruptions during decode and thereby slightly improving TPOT and overall throughput. The cost is that some requests wait longer before receiving their first token. Selecting an appropriate prefill size can reduce end-to-end time and improve throughput.

### 3.4 GDN Indexed-State Experiment

GDN (Gated DeltaNet) does not store complete K/V data for every token like standard attention. Instead, it maintains a fixed-size recurrent state for each request. The indexed-state method directly locates and reads/writes each request's GDN state to reduce state movement. In the serial experiment, the GDN candidate increased six-question workflow time by approximately 5.18%, first-question TTFT by approximately 5.39%, and TPOT by approximately 1.37%. The concurrent C4 experiment (baseline 30935, candidate 30940) was also slower:

| Metric | Baseline | GDN candidate | Change |
|---|---:|---:|---:|
| E2E (s) | 56.077 | 57.735 | +2.96% |
| TTFT (s) | 17.996 | 18.434 | +2.43% |
| TPOT (ms) | 23.584 | 24.349 | +3.24% |
| requests/s | 0.06569 | 0.06393 | -2.68% |
| output tok/s | 106.56 | 103.70 | -2.68% |

The candidate passed the real GPU kernel check and 8/8 quality checks. The likely cause is that index construction, gather, or additional state-management overhead was not amortized by this input length and concurrency. It is a correctness-valid change, but not an effective performance optimization for this project.

### 3.5 GPU N-gram Speculative Decoding

GPU N-gram is a speculative-decoding method. Its core idea is to use token sequences that have already appeared to predict likely future tokens, and then let the large model validate them. If validation succeeds, multiple tokens can be accepted at once instead of being generated one by one. This reduces the number of serial decode iterations in principle, which can lower TPOT and end-to-end latency. The experiment used `ngram_gpu`, three speculative tokens, and prompt lookup 2–5. It observed 240 draft tokens and 76 accepted tokens, an acceptance rate of approximately 31.7%, but the overall workflow was approximately 10.7% slower and TPOT approximately 45% slower. The low acceptance rate and the extra kernel/scheduling overhead of the draft path outweighed the benefit.
## 4. Discussion

Based on the comparison of the methods and the observed results, the selected model-server optimization is to tune the size of `max_num_batched_tokens`. This value is the scheduler's token budget per iteration: the upper bound on the number of tokens that can be scheduled in one iteration. A larger value gives the scheduler a larger budget to schedule more prefill work in one iteration, improving prefill processing efficiency, reducing the number of chunks for long inputs, and increasing the amount of GPU work when sufficient GPU resources are available. If it is too large, decode latency may increase, memory pressure may increase, and long requests may interfere with short requests.

- A small budget such as 2048 fragments prefill too aggressively; frequent switching between decode and prefill increases queueing and TPOT.
- 4096 is a more balanced default.
- 8192 allows the scheduler to process more prefill tokens in a batch. For this workload, it reduces decode interruption and gives lower TPOT and slightly higher throughput, but increases TTFT.

Chunked prefill is therefore a **feasible service-scheduling optimization direction**, but its benefit depends on input length, concurrency, output length, and the target metric. It does not guarantee lower single-request latency. For this project's concurrency objective, 8192 is a reasonable final submission setting; for interactive first-token latency, 4096 may be safer.

## 5. File Organization

The `server` directory contains the baseline model-server files. The `server-opt` directory contains the optimized model-server files. The `model-server` directory contains model deployment files. The `evaluation` directory contains the datasets and configuration files required for evaluation. The `result` directory stores experiment results.

After the model server is deployed on TACC, it provides a `base_url`. The Agent can connect through `/v1/chat/completions`; the Agent sends requests and tool calls, while the server returns the OpenAI-compatible response. Performance metrics can be calculated from the server's `/metrics` response.
## 6. Reproduction Materials and Limitations

Main result files:

- `/results/long-output-public-baseline-30291-analysis.json`
- `/results/private-vanilla-control-30371-vs-public-30291.json`
- `/results/prefill-screen-analysis-30454-30459.json`
- `/results/e01-flash-attn-analysis-30468.json`
- `/results/gdn-analysis-30056-30085.json`
- `/results/speculative-comparison-30056-30196.json`
- `/results/concurrency-level-summary.json`
- `/results/chunked-prefill-analysis-30912-30919-30928.json`
- `/results/e02-profile-analysis-30935.json`
- `/results/gdn-concurrency-comparison-30935-30940.json`
Because of the available time, the workload data volume was limited and may not fully expose some optimization effects. Small workloads can also produce incidental variation. The experimental configuration may still contain gaps, and more experiments may be needed to establish whether an optimization generalizes.
