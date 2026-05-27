DEFAULT_POLICIES: list[dict] = [
    {
        "policy_id": "deny-untrusted-memory-write",
        "name": "Deny untrusted memory writes",
        "description": "Untrusted context cannot write to shared memory.",
        "enabled": True,
        "priority": 10,
        "condition": {
            "event_type": "tool_call",
            "target_node_type": "memory",
            "source_trust_level": "untrusted",
        },
        "action": "quarantine",
        "severity": "critical",
        "reason": "Untrusted context cannot write to shared memory.",
    },
    {
        "policy_id": "quarantine-high-contamination",
        "name": "Quarantine high contamination events",
        "description": "High contamination score detected.",
        "enabled": True,
        "priority": 20,
        "condition": {
            "min_contamination_score": 0.75,
        },
        "action": "quarantine",
        "severity": "critical",
        "reason": "High contamination score detected.",
    },
    {
        "policy_id": "alert-rag-poisoning",
        "name": "Alert RAG poisoning indicators",
        "description": "Possible RAG/context poisoning indicator.",
        "enabled": True,
        "priority": 50,
        "condition": {
            "risk_tags_any": ["rag_poisoning", "context_poisoning"],
        },
        "action": "alert",
        "severity": "warning",
        "reason": "Possible RAG/context poisoning indicator.",
    },
]
