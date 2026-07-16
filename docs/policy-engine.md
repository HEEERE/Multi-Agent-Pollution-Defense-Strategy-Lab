# Policy Engine

## Design Motivation

Detection identifies risks; policy decides what to do about them. The Policy Engine sits between the Monitor Pipeline and event persistence, evaluating each event against a set of rules to determine the appropriate action.

This separation allows:
- Detectors to focus on risk identification without being coupled to response logic
- Security operators to define response policies independently of detection mechanisms
- A/B testing of different policy configurations on the same detection results

## Rule Schema

### PolicyCondition

| Field | Type | Description |
|-------|------|-------------|
| `event_type` | `str \| None` | Match on `AgentEvent.event_type` |
| `source_trust_level` | `str \| None` | Match on `AgentEvent.trust_level` |
| `target_node_type` | `str \| None` | Match on `metadata.target_node_type` |
| `risk_tags_any` | `list[str]` | Match if any tag present in `risk_tags` |
| `min_contamination_score` | `float \| None` | Match if score >= threshold |
| `metadata_match` | `dict` | Exact key-value matches on `metadata` |

All conditions within a rule are AND-ed. Empty/None fields are ignored (always match).

### PolicyRule

| Field | Type | Description |
|-------|------|-------------|
| `policy_id` | `str` | Unique identifier |
| `name` | `str` | Human-readable name |
| `description` | `str` | Explanation of what this rule does |
| `enabled` | `bool` | Whether the rule is active |
| `priority` | `int` | Lower number = higher priority |
| `condition` | `PolicyCondition` | Matching criteria |
| `action` | `str` | `allow`, `alert`, `block`, `quarantine`, `isolate`, `human_review` |
| `severity` | `str` | `info`, `warning`, `critical` |
| `reason` | `str` | Human-readable justification |

### PolicyDecision

| Field | Type | Description |
|-------|------|-------------|
| `policy_id` | `str \| None` | Which policy matched (None if no match) |
| `action` | `str` | Final action decision |
| `severity` | `str` | Severity level |
| `reason` | `str` | Decision rationale |
| `matched` | `bool` | Whether any policy matched |

## Default Policies

### 1. Deny Untrusted Memory Writes (`deny-untrusted-memory-write`)

- **Priority**: 10 (highest)
- **Condition**: `event_type=tool_call` AND `target_node_type=memory` AND `trust_level=untrusted`
- **Action**: `quarantine`
- **Severity**: `critical`

### 2. Quarantine High Contamination (`quarantine-high-contamination`)

- **Priority**: 20
- **Condition**: `contamination_score >= 0.75`
- **Action**: `quarantine`
- **Severity**: `critical`

### 3. Alert RAG Poisoning (`alert-rag-poisoning`)

- **Priority**: 50
- **Condition**: `risk_tags` contains `rag_poisoning` or `context_poisoning`
- **Action**: `alert`
- **Severity**: `warning`

## Decision Priority

When multiple policies match an event, the action with the highest severity wins:

```
allow < alert < quarantine < isolate < block < human_review
```

When multiple policies have the same action level, the one with the lower `priority` number wins.

### Detector Override Protection

If a detector has already assigned a `BLOCK` action to an event, the policy engine **cannot downgrade** it. The detector's action is preserved with the reason annotated to indicate the policy match was overridden.

## How to Extend Policies

### Adding a New Policy (Code)

Add an entry to `backend/app/policy/default_policies.py`:

```python
{
    "policy_id": "my-custom-policy",
    "name": "My Custom Policy",
    "description": "Blocks untrusted tool calls to external APIs.",
    "enabled": True,
    "priority": 15,
    "condition": {
        "event_type": "tool_call",
        "target_node_type": "external_api",
        "source_trust_level": "untrusted",
    },
    "action": "block",
    "severity": "critical",
    "reason": "Untrusted agent accessing external API.",
}
```

### Testing a Policy

Use the `/api/v1/policies/evaluate` endpoint:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/policies/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "test_001",
    "trace_id": "trace_test",
    "event_type": "tool_call",
    "source_node": "untrusted_agent",
    "target_node": "memory_store",
    "payload_snippet": "write to shared memory",
    "trust_level": "untrusted",
    "risk_tags": [],
    "contamination_score": 0.0,
    "metadata": {"target_node_type": "memory"}
  }'
```

Response:
```json
{
  "policy_id": "deny-untrusted-memory-write",
  "action": "quarantine",
  "severity": "critical",
  "reason": "Untrusted context cannot write to shared memory.",
  "matched": true
}
```

### Listing Active Policies

```bash
curl http://127.0.0.1:8000/api/v1/policies
```
