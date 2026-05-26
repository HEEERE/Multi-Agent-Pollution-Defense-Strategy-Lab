# Research/Product Platform Roadmap

## Platform direction

The project is evolving from a hackathon visualization into a research and product platform for multi-agent infection detection, prompt-injection propagation analysis, and defensive intervention.

## Immediate productization layers

1. Event contract hardening
   - Add `event_id`, `trace_id`, `severity`, `monitor_level`, and `metadata`.
   - Persist events for replay and audit.

2. LLM provider abstraction
   - Current provider: MiMo OpenAI-compatible API.
   - Base URL: `https://token-plan-cn.xiaomimimo.com/v1`.
   - Model: `MiMo-V2.5-Pro`.
   - API keys are loaded from environment variables only.

3. Research workflow
   - Playbooks become reproducible experiments.
   - Each run should store inputs, event traces, detector outputs, and final labels.
   - Metrics should include propagation depth, time-to-detection, false positive rate, and intervention effectiveness.

4. Product workflow
   - Tenant/project isolation.
   - API authentication.
   - Event store and replay.
   - Monitor policy versions.
   - Human review queue for high-severity events.

## MiMo configuration

Create `backend/.env` from `backend/.env.example`:

```text
MIMO_API_KEY=replace-with-your-mimo-api-key
MIMO_BASE_URL=https://token-plan-cn.xiaomimimo.com/v1
MIMO_MODEL=MiMo-V2.5-Pro
LLM_ENABLED=true
```

When `LLM_ENABLED=false`, the platform returns deterministic disabled-provider responses so demos and tests still run without network access.

## Next recommended milestone

Upgrade `AgentEvent` into a research-grade trace schema and add an event store. This will make every visualization reproducible and measurable.
