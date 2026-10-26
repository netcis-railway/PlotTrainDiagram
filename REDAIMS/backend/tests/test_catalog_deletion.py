from pathlib import Path

import pytest
from app.core.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


def branch(client, suffix):
    parent = None
    ids = []
    for kind in ["user", "network", "scenario", "case", "algorithm", "batch"]:
        response = client.post(
            "/api/v1/catalog", json={"kind": kind, "name": kind + suffix, "parent_id": parent}
        )
        assert response.status_code == 201
        parent = response.json()["id"]
        ids.append(parent)
    return ids


def seed(app, batch_id, run_id="run1", name="方案"):
    with app.state.database.transaction() as connection:
        connection.execute(
            "INSERT INTO runs (id, batch_id, name) VALUES (?, ?, ?)", [run_id, batch_id, name]
        )


def execute(client, node_id, preview, action, target=None):
    return client.request(
        "DELETE",
        f"/api/v1/catalog/{node_id}",
        json={
            "action": action,
            "target_batch_id": target,
            "preview_token": preview["preview_token"],
            "confirmed": True,
        },
    )


@pytest.mark.parametrize("action", ["delete", "ungroup", "move"])
def test_delete_subtree_and_runs(tmp_path: Path, action):
    settings = Settings(database=tmp_path / "delete.duckdb")
    app = create_app(settings)
    with TestClient(app) as client:
        source = branch(client, "1")
        target = branch(client, "2")
        seed(app, source[-1])
        seed(app, target[-1], "untouched", "其他")
        preview = client.get(f"/api/v1/catalog/{source[0]}/deletion-preview").json()
        assert preview["node_count"] == 6
        assert preview["run_count"] == 1
        assert [node["id"] for node in preview["eligible_batches"]] == [target[-1]]
        response = execute(
            client, source[0], preview, action, target[-1] if action == "move" else None
        )
        assert response.status_code == 200, response.text
        assert len(client.get("/api/v1/catalog").json()) == 6
        with app.state.database.transaction() as connection:
            assert connection.execute("SELECT batch_id FROM runs WHERE id='untouched'").fetchone()
            row = connection.execute("SELECT batch_id FROM runs WHERE id='run1'").fetchone()
            if action == "delete":
                assert row is None
            else:
                assert row == (target[-1] if action == "move" else None,)
        ungrouped = client.get("/api/v1/runs/ungrouped").json()
        assert len(ungrouped) == (1 if action == "ungroup" else 0)
        if ungrouped:
            assert len(ungrouped[0]["origin_path"]) == 6
    with TestClient(create_app(settings)) as client:
        assert len(client.get("/api/v1/catalog").json()) == 6


def test_stale_preview_confirmation_and_target_validation(tmp_path: Path):
    app = create_app(Settings(database=tmp_path / "test.duckdb"))
    with TestClient(app) as client:
        ids = branch(client, "")
        preview = client.get(f"/api/v1/catalog/{ids[0]}/deletion-preview").json()
        assert execute(client, ids[0], preview, "move", ids[-1]).status_code == 422
        assert (
            client.request(
                "DELETE",
                f"/api/v1/catalog/{ids[0]}",
                json={
                    "action": "delete",
                    "preview_token": preview["preview_token"],
                    "confirmed": False,
                },
            ).status_code
            == 422
        )
        seed(app, ids[-1])
        assert execute(client, ids[0], preview, "delete").status_code == 409
        assert len(client.get("/api/v1/catalog").json()) == 6
        assert client.get("/api/v1/catalog/missing/deletion-preview").status_code == 404


def test_move_conflict_rolls_back_and_empty_branch_delete(tmp_path: Path):
    app = create_app(Settings(database=tmp_path / "test.duckdb"))
    with TestClient(app) as client:
        source = branch(client, "1")
        target = branch(client, "2")
        seed(app, source[-1])
        seed(app, target[-1], "run2")
        preview = client.get(f"/api/v1/catalog/{source[0]}/deletion-preview").json()
        assert execute(client, source[0], preview, "move", target[-1]).status_code == 409
        assert len(client.get("/api/v1/catalog").json()) == 12
        with app.state.database.transaction() as connection:
            assert connection.execute("SELECT batch_id FROM runs WHERE id='run1'").fetchone() == (
                source[-1],
            )
        empty = branch(client, "empty")
        preview = client.get(f"/api/v1/catalog/{empty[-1]}/deletion-preview").json()
        assert preview["node_count"] == 1 and preview["run_count"] == 0
        assert execute(client, empty[-1], preview, "ungroup").status_code == 200
