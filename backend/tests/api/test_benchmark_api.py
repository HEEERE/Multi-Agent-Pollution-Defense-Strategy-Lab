class TestBenchmarkAPI:
    def test_list_reports_returns_array(self, client):
        resp = client.get("/api/v1/benchmark/reports")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_report_not_found_returns_404(self, client):
        resp = client.get("/api/v1/benchmark/reports/nonexistent-report")
        assert resp.status_code == 404
