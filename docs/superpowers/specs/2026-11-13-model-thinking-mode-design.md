# Optional Model Thinking Mode

## Intent and scope

Continue the user-authorized DeepSeek integration and real-model acceptance. The current Chat Completions adapter always sends a JSON response request, with the Runner limiting output to 2048 tokens. Support explicitly disabling provider thinking before the first live task, without raising budgets or changing unrelated providers.

## Approach

Use `LLM_THINKING_MODE=provider_default|disabled|enabled`, defaulting to `provider_default`. The default omits the provider-specific `thinking` field; explicit modes send `thinking.type`. A configurable value is preferable to hard-coding DeepSeek host detection or increasing all output budgets. Provider-specific support remains the operator's responsibility; DeepSeek acceptance uses `disabled`.

Freeze the value in each real task's existing `run_config` JSONB and read it from the job when constructing the model client. Existing tasks without this field use `provider_default`; changing Worker configuration must not alter a submitted task. API keys remain runtime-only. No migration, new dependency, browser setting, retry or model request is needed to implement and test this change.

## Evidence and acceptance

Official reference checked: `https://api-docs.deepseek.com/guides/thinking_mode` documents `thinking: {type: disabled}`. Use mocked HTTP to verify exact payloads and local unit fixtures to verify submission/Worker propagation and old-task compatibility. Keep temporary checks ignored under runtime, following current project practice. Actual model credentials, availability, generation quality and citations remain user-guided live acceptance gates.
