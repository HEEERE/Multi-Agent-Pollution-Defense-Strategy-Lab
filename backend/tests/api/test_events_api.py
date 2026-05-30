class TestEventsAPI:
    def test_list_events_returns_array(self, client):
        resp = client.get("/api/v1/events")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_event_not_found_returns_404(self, client):
        resp = client.get("/api/v1/events/nonexistent-id")
        assert resp.status_code == 404

    def test_sample_event_returns_valid_structure(self, client):
        resp = client.get("/api/v1/events/sample")
        assert resp.status_code == 200
        data = resp.json()
        assert "event_id" in data
        assert data["status"] == "safe"

    def test_latest_events_returns_array(self, client):
        resp = client.get("/api/v1/events/latest")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
