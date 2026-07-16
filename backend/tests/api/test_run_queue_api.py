import time


def test_strategy_run_is_processed_by_persistent_worker(client):
    content = {
        "name": "queue-integration",
        "num_runs": 1,
        "topology": {
            "nodes": [
                {"node_id": "gateway", "node_type": "gateway"},
                {"node_id": "agent_a", "node_type": "agent"},
                {"node_id": "auditor", "node_type": "monitor"},
            ],
            "edges": [{"source": "gateway", "target": "agent_a"}],
            "monitors": ["auditor"],
            "injections": [
                {
                    "injection_type": "prompt_injection",
                    "source_node": "gateway",
                    "target_node": "agent_a",
                    "payload": "ordinary payload governed by user policy",
                    "turn": 0,
                }
            ],
            "max_turns": 1,
        },
        "policies": [
            {
                "policy_id": "block-inputs",
                "action": "block",
                "condition": {"event_type": "input"},
            }
        ],
        "detector_settings": {
            "regex": {"enabled": True},
            "semantic": {"enabled": False},
            "llm_intent": {"enabled": False},
        },
    }
    created = client.post(
        "/api/v1/strategies",
        json={
            "name": "queue-integration",
            "description": "",
            "format": "json",
            "content": content,
            "tags": ["queue"],
        },
    )
    assert created.status_code == 201
    strategy_id = created.json()["strategy_id"]

    started = client.post(f"/api/v1/strategies/{strategy_id}/run")
    assert started.status_code == 200
    assert started.json()["status"] == "queued"
    run_id = started.json()["run_id"]

    deadline = time.time() + 5
    run = None
    while time.time() < deadline:
        run = client.get(f"/api/v1/runs/{run_id}").json()
        if run["status"] in {"completed", "failed"}:
            break
        time.sleep(0.05)

    assert run["status"] == "completed"
    assert run["trace_id"]
    events = client.get(f"/api/v1/runs/{run_id}/events").json()
    input_event = next(event for event in events if event["event_type"] == "input")
    assert input_event["policy_id"] == "block-inputs"
    assert input_event["action_taken"] == "block"
    assert input_event["metadata"]["topology_monitors"] == ["auditor"]
