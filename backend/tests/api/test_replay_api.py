class TestReplayAPI:
    def test_start_replay_trace_not_found_returns_404(self, client):
        resp = client.post("/api/v1/replay/nonexistent-trace/start")
        assert resp.status_code == 404

    def test_get_replay_state_session_not_found_returns_404(self, client):
        resp = client.get("/api/v1/replay/nonexistent-session/state")
        assert resp.status_code == 404

    def test_pause_replay_session_not_found_returns_404(self, client):
        resp = client.post("/api/v1/replay/nonexistent-session/pause")
        assert resp.status_code == 404
