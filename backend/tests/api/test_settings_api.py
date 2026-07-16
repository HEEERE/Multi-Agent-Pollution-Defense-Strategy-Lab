class TestSettingsAPI:
    def test_get_all_settings(self, client):
        resp = client.get("/api/v1/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "categories" in data
        assert "updated_at" in data

    def test_get_existing_category(self, client):
        resp = client.get("/api/v1/settings/detectors")
        assert resp.status_code == 200
        data = resp.json()
        assert data["category"] == "detectors"
        assert "values" in data

    def test_llm_api_key_is_never_exposed_or_mutable(self, client):
        resp = client.get("/api/v1/settings/llm")
        assert resp.status_code == 200
        assert "llm.api_key" not in resp.json()["values"]

        resp = client.get("/api/v1/settings")
        assert "llm.api_key" not in resp.json()["categories"]["llm"]

        resp = client.put(
            "/api/v1/settings/llm",
            json={"llm.api_key": "must-not-be-persisted"},
        )
        assert resp.status_code == 400

    def test_get_invalid_category_returns_404(self, client):
        resp = client.get("/api/v1/settings/invalid-category")
        assert resp.status_code == 404

    def test_update_invalid_category_returns_404(self, client):
        resp = client.put("/api/v1/settings/invalid-category", json={"key": "val"})
        assert resp.status_code == 404

    def test_reset_invalid_category_returns_404(self, client):
        resp = client.post("/api/v1/settings/invalid-category/reset")
        assert resp.status_code == 404

    def test_update_and_reset_detectors(self, client):
        resp = client.put("/api/v1/settings/detectors", json={"regex.enabled": False})
        assert resp.status_code == 200
        assert resp.json()["status"] == "saved"

        resp = client.get("/api/v1/settings/detectors")
        assert resp.json()["values"]["regex.enabled"] is False

        resp = client.post("/api/v1/settings/detectors/reset")
        assert resp.status_code == 200

        resp = client.get("/api/v1/settings/detectors")
        assert resp.json()["values"]["regex.enabled"] is True
