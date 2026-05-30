class TestTracesAPI:
    def test_list_traces_returns_array(self, client):
        resp = client.get("/api/v1/traces")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_trace_not_found_returns_empty(self, client):
        resp = client.get("/api/v1/traces/nonexistent-trace")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_trace_summary_not_found_returns_404(self, client):
        resp = client.get("/api/v1/traces/nonexistent-trace/summary")
        assert resp.status_code == 404

    def test_get_trace_graph_not_found_returns_404(self, client):
        resp = client.get("/api/v1/traces/nonexistent-trace/graph")
        assert resp.status_code == 404

    def test_get_trace_contamination_not_found_returns_404(self, client):
        resp = client.get("/api/v1/traces/nonexistent-trace/contamination")
        assert resp.status_code == 404

    def test_delete_trace_returns_result(self, client):
        resp = client.delete("/api/v1/traces/nonexistent-trace")
        assert resp.status_code == 200
        data = resp.json()
        assert "deleted" in data
        assert "trace_id" in data
