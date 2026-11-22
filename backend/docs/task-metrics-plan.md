# Task detail metrics

Expose an additive `metrics` object on both task detail APIs without changing the
frontend, Agent source, model server, database schema, or evaluation behavior.

1. Test safe normalization of server response metrics and missing historical data.
2. Capture response telemetry in a backend-owned TCloud launcher, after bootstrap.
3. Assemble latest evaluation, Agent usage, request metrics and GPU snapshots.
4. Test both authorized detail routes against isolated PostgreSQL and test capture
   against the installed Agent model SDK with a mocked HTTP response.
5. Document units, aggregation, availability and deployment requirements.

Only measured values are reported. Missing values remain null. GPU readings are
allocated-device snapshots at response completion, including other processes;
they are never represented as task averages. Server timing is not client timing.
Reads neither enqueue evaluations nor contact external services.

Cache usage extends the same capture and detail APIs. Sum paired per-request
cache-hit and prompt-token counts, then divide summed hits by summed query tokens.
Expose observed-call coverage so partial cache readings cannot imply complete
task totals. Accept explicit standard usage or request telemetry, recover saved
Agent SDK cache usage when available, and never use global server cache counters.
