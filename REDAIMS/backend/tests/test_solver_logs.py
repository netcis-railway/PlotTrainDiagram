from hashlib import sha256
from urllib.parse import quote

import pytest
from app.api.v1 import solver_logs
from app.core.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient
from test_catalog_deletion import branch, execute, seed


def upload(client, run="run1", filename="求解日志.log", content=b"objective=12\n"):
    return client.post(
        f"/api/v1/runs/{run}/solver-logs", params={"filename": filename}, content=content
    )


def test_log_import_is_scoped_idempotent_and_survives_restart(tmp_path):
    settings = Settings(database=tmp_path / "logs.duckdb")
    app = create_app(settings)
    content = "求解完成\n目标值=12\n".encode("gb18030")
    with TestClient(app) as client:
        ids = branch(client, "logs")
        seed(app, ids[-1])
        seed(app, ids[-1], "other")
        response = upload(client, filename="C:\\tmp\\求解日志.log", content=content)
        assert response.status_code == 201, response.text
        log = response.json()
        assert log["run_id"] == "run1"
        assert log["filename"] == "求解日志.log"
        assert log["size_bytes"] == len(content)
        assert log["digest"] == sha256(content).hexdigest()
        assert upload(client, content=content).json()["id"] == log["id"]
        assert client.get("/api/v1/runs/other/solver-logs").json() == []
        assert client.get(f"/api/v1/runs/other/solver-logs/{log['id']}/download").status_code == 404
        assert upload(client, content=b"new result").json()["id"] != log["id"]
        with app.state.database.transaction() as connection:
            assert connection.execute("SELECT count(*) FROM timetable_events").fetchone()[0] == 0
    with TestClient(create_app(settings)) as client:
        logs = client.get("/api/v1/runs/run1/solver-logs").json()
        assert len(logs) == 2
        response = client.get(f"/api/v1/runs/run1/solver-logs/{log['id']}/download")
        assert response.content == content
        assert quote(log["filename"]) in response.headers["content-disposition"]
        assert response.headers["x-content-type-options"] == "nosniff"


def test_invalid_logs_and_wrong_object_are_rejected(tmp_path, monkeypatch):
    app = create_app(Settings(database=tmp_path / "logs.duckdb"))
    with TestClient(app) as client:
        ids = branch(client, "invalid")
        seed(app, ids[-1])
        seed(app, ids[-1], "base")
        with app.state.database.transaction() as connection:
            connection.execute(
                "INSERT INTO base_run_data (run_id,role,user_id,network_id,date_base,metadata) "
                "VALUES ('base','base',?,?,'2025-01-01','{}')",
                [ids[0], ids[1]],
            )
        assert upload(client, run="missing").status_code == 404
        assert upload(client, run="base").status_code == 404
        assert client.get("/api/v1/runs/base/solver-logs").status_code == 404
        assert upload(client, content=b"").status_code == 422
        assert upload(client, filename="..").status_code == 422
        assert upload(client, filename="bad\nname").status_code == 422
        monkeypatch.setattr(solver_logs, "MAX_LOG_BYTES", 8)
        assert upload(client, content=b"123456789").status_code == 413
        assert client.get("/api/v1/runs/run1/solver-logs").json() == []


@pytest.mark.parametrize("action", ["delete", "ungroup", "move"])
def test_logs_follow_run_lifecycle(tmp_path, action):
    app = create_app(Settings(database=tmp_path / "logs.duckdb"))
    with TestClient(app) as client:
        source = branch(client, "source")
        target = branch(client, "target")
        seed(app, source[-1])
        log = upload(client).json()
        preview = client.get(f"/api/v1/catalog/{source[0]}/deletion-preview").json()
        response = execute(
            client, source[0], preview, action, target[-1] if action == "move" else None
        )
        assert response.status_code == 200, response.text
        with app.state.database.transaction() as connection:
            count = connection.execute(
                "SELECT count(*) FROM run_solver_logs WHERE run_id='run1'"
            ).fetchone()[0]
        assert count == (0 if action == "delete" else 1)
        response = client.get(f"/api/v1/runs/run1/solver-logs/{log['id']}/download")
        assert response.status_code == (404 if action == "delete" else 200)
