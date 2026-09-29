from fastapi.testclient import TestClient

from backend.app import app

client = TestClient(app)


def test_health_is_always_ok() -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["ollama"] in {"reachable", "unreachable"}
    assert isinstance(body["models_present"], list)
    assert isinstance(body["kb_entries"], int)
