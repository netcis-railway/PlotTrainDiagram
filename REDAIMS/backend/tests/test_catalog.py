from pathlib import Path

from app.core.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


def test_catalog_validation_and_restart(tmp_path: Path):
    settings = Settings(database=tmp_path / "test.duckdb")
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/health").json()["status"] == "ok"
        assert client.get("/openapi.json").json()["openapi"] == "3.1.0"
        assert (
            client.post("/api/v1/catalog", json={"kind": "user", "name": "  "}).status_code == 422
        )
        assert (
            client.post("/api/v1/catalog", json={"kind": "batch", "name": "x"}).status_code == 422
        )
        parent = None
        for kind in ["user", "network", "scenario", "case", "algorithm", "batch"]:
            data = {"kind": kind, "name": kind, "parent_id": parent, "notes": "原备注"}
            response = client.post("/api/v1/catalog", json=data)
            assert response.status_code == 201, response.text
            assert client.post("/api/v1/catalog", json=data).status_code == 409
            parent = response.json()["id"]
        assert (
            client.patch(f"/api/v1/catalog/{parent}", json={"notes": "新备注"}).status_code == 200
        )
        assert client.patch("/api/v1/catalog/missing", json={"notes": "x"}).status_code == 404
    with TestClient(create_app(settings)) as client:
        nodes = client.get("/api/v1/catalog").json()
        assert len(nodes) == 6
        assert next(node for node in nodes if node["id"] == parent)["notes"] == "新备注"


def test_parent_scope_and_transaction_rollback(tmp_path: Path):
    with TestClient(create_app(Settings(database=tmp_path / "test.duckdb"))) as client:
        users = [
            client.post("/api/v1/catalog", json={"kind": "user", "name": name}).json()
            for name in ["甲", "乙"]
        ]
        for user in users:
            result = client.post(
                "/api/v1/catalog",
                json={"kind": "network", "parent_id": user["id"], "name": "同名路网"},
            )
            assert result.status_code == 201
        invalid = client.post(
            "/api/v1/catalog",
            json={"kind": "case", "parent_id": users[0]["id"], "name": "错误层级"},
        )
        assert invalid.status_code == 422
        assert len(client.get("/api/v1/catalog").json()) == 4
