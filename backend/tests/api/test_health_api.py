class TestHealthAPI:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


class TestPlatformConfigAPI:
    def test_platform_config_returns_settings(self, client):
        resp = client.get("/api/platform/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "llm_provider" in data
        assert "llm_enabled" in data
