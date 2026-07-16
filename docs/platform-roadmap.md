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
   - Model: `mimo-v2.5-pro`.
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
MIMO_MODEL=mimo-v2.5-pro
LLM_ENABLED=true
```

When `LLM_ENABLED=false`, the platform returns deterministic disabled-provider responses so demos and tests still run without network access.

## Completed milestones

### v0.3.0 — Agentic AI Runtime Security Upgrade
- **TraceGraph** reconstruction from event streams with node/edge models
- **Contamination Analyzer** with propagation depth, blast radius, time-to-detection, recovery success, persistence
- **Policy Engine** with rule-based action decisions (3 default policies, detector override protection)
- **Event Schema v2** with 8 new fields (event_category, risk_tags, trust_level, contamination_score, policy_decision, policy_id, edge_kind, artifact_refs)
- **Idempotent SQLite Migration** using PRAGMA table_info for backward-compatible schema evolution
- **Benchmark v2** corpus with 7 categories (19 samples) and v2 metrics model
- **Frontend Contamination UI** with summary panel, node badges, and enhanced detail panel
- **API**: `/api/v1/traces/{id}/graph`, `/api/v1/traces/{id}/contamination`, `/api/v1/policies`, `/api/v1/policies/evaluate`
- Documentation: `docs/trace-graph.md`, `docs/policy-engine.md`

## Next recommended milestone

Expand the held-out corpus with externally reviewed labels and provenance,
add project-level RBAC/tenant isolation, and move the SQLite worker protocol to
a distributed queue only when multi-host scale is required.

## Completed hardening — v0.4

- Environment-only LLM secrets with legacy SQLite secret removal
- Optional `MAJD_API_KEY` protection for REST and WebSocket, with signed HttpOnly browser sessions
- Strategy execution for directed edges, monitor nodes, custom policies and repeated `num_runs`
- SQLite-backed persistent run queue with atomic claims and restart recovery
- Versioned `majd-heldout-v1` multilingual benchmark separated from vector-store seed samples
- Frontend Vitest and Testing Library regression suite
