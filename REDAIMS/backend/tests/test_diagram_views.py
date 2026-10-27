from copy import deepcopy

import pytest
from app.api.v1 import diagram_views
from app.core.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient
from sample_workbook import SAMPLE_WORKBOOK
from test_base_import import create_base
from test_base_replace import seed_result
from test_catalog_deletion import branch, execute, seed


def payload(run_id="run1"):
    data = {
        "object": {"id": run_id, "object_type": "run", "date_base": "2025-04-08"},
        "revision": "revision",
        "line_ind": 1,
        "base": {"id": "base1"},
        "can_plot": True,
        "overlay_base": True,
        "axis": {"stations": [{"node_id": "s1", "y": 0}], "total": 10},
        "series": [
            {"key": "run:G1", "object_type": "run", "object_id": run_id},
            {"key": "base:G1", "object_type": "base", "object_id": "base1"},
        ],
        "track_stations": [],
        "expanded_stations": [],
        "issues": [],
        "styles": {},
    }
    return {
        "name": "对比视图",
        "state": {
            "version": 1,
            "line_ind": 1,
            "overlay_base": True,
            "reverse": True,
            "station_ids": ["s1"],
            "train_keys": ["run:G1", "base:G1"],
            "highlighted_keys": ["base:G1", "run:G1"],
            "expanded_station_ids": [],
            "viewport": {"x0": 85800, "x1": 90000, "y0": -2, "y1": 12},
            "from_time": "2025-04-08T23:50:00",
            "to_time": "2025-04-09T01:00:00",
            "detail_open": True,
            "chart_height": 980,
        },
        "snapshot": {
            "context": {"object": data["object"], "lines": [{"line_ind": 1}]},
            "data": data,
        },
    }


def post(client, body, run_id="run1"):
    return client.post(f"/api/v1/runs/{run_id}/diagram-views", json=body)


def test_real_plot_roundtrip_preserves_overlay_selections_drafts_and_later_source_changes(tmp_path):
    settings = Settings(database=tmp_path / "views.duckdb")
    app = create_app(settings)
    with TestClient(app) as client:
        ids = branch(client, "roundtrip")
        _, base = create_base(client, ids[2], SAMPLE_WORKBOOK.read_bytes())
        seed_result(app, client, ids[-1], base)
        url = "/api/v1/runs/result/tables"
        before = client.get(url).json()
        context = client.get(
            "/api/v1/diagram/lines", params={"object_type": "run", "object_id": "result"}
        ).json()
        edited = next(event for event in before["events"] if event["departure"])
        seconds = edited["departure"]["seconds"] + 1
        edited_time = f"{seconds // 3600:02}:{seconds % 3600 // 60:02}:{seconds % 60:02}"
        data = client.post(
            "/api/v1/diagram/data",
            json={
                "object_type": "run",
                "object_id": "result",
                "revision": context["revision"],
                "line_ind": 1,
                "overlay_base": True,
                "changes": [
                    {
                        "event_id": edited["id"],
                        "field": "departure",
                        "value": edited_time,
                    }
                ],
            },
        ).json()
        assert data["can_plot"], data["issues"]
        assert data["preview"] and data["preview_changes"] == 1
        run = next(s for s in data["series"] if s["object_type"] == "run")
        base_train = next(s for s in data["series"] if s["object_type"] == "base")
        body = payload("result")
        body["snapshot"] = {"context": context, "data": data}
        body["state"]["station_ids"] = [s["node_id"] for s in data["axis"]["stations"][:3]]
        body["state"]["train_keys"] = [base_train["key"], run["key"]]
        body["state"]["highlighted_keys"] = [run["key"], base_train["key"]]
        response = post(client, body, "result")
        assert response.status_code == 201, response.text
        summary = response.json()
        assert summary["station_count"] == 3 and summary["highlight_count"] == 2
        assert "snapshot" not in summary
        saved = client.get(f"/api/v1/runs/result/diagram-views/{summary['id']}").json()
        assert saved["state"]["train_keys"] == [base_train["key"], run["key"]]
        assert saved["snapshot"] == body["snapshot"]
        assert client.get(url).json() == before
        assert client.get("/api/v1/diagram/views").json() == [summary]
        with app.state.database.transaction() as c:
            c.execute("UPDATE runs SET name='后来修改的run' WHERE id='result'")
            c.execute("UPDATE base_timetables SET name='后来修改的基本图' WHERE id=?", [base["id"]])
    with TestClient(create_app(settings)) as client:
        again = client.get(f"/api/v1/runs/result/diagram-views/{summary['id']}").json()
        assert again == saved
        assert again["snapshot"]["data"]["base"]["name"] == base["name"]


def test_view_names_scoping_and_invalid_state_are_checked(tmp_path, monkeypatch):
    app = create_app(Settings(database=tmp_path / "views.duckdb"))
    with TestClient(app) as client:
        ids = branch(client, "validation")
        seed(app, ids[-1])
        seed(app, ids[-1], "other")
        body = payload()
        response = post(client, body)
        assert response.status_code == 201, response.text
        view = response.json()
        assert client.get(f"/api/v1/runs/other/diagram-views/{view['id']}").status_code == 404
        assert client.get("/api/v1/runs/missing/diagram-views").status_code == 404
        assert post(client, body).status_code == 409
        for change in [
            lambda b: b.update(name="   "),
            lambda b: b["state"]["viewport"].update(x1=1),
            lambda b: b["state"].update(version=2),
            lambda b: b["state"].update(station_ids=["foreign"]),
            lambda b: b["state"].update(highlighted_keys=["foreign"]),
            lambda b: b["snapshot"]["data"]["object"].update(id="other"),
            lambda b: b["snapshot"]["data"]["series"][1].update(object_id="foreign-base"),
        ]:
            bad = deepcopy(body)
            change(bad)
            assert post(client, bad).status_code == 422
        monkeypatch.setattr(diagram_views, "MAX_VIEW_BYTES", 10)
        large = deepcopy(body)
        large["name"] = "超限"
        assert post(client, large).status_code == 413
        assert len(client.get("/api/v1/runs/run1/diagram-views").json()) == 1


@pytest.mark.parametrize("action", ["delete", "ungroup", "move"])
def test_views_follow_run_lifecycle(tmp_path, action):
    app = create_app(Settings(database=tmp_path / "views.duckdb"))
    with TestClient(app) as client:
        source = branch(client, "source")
        target = branch(client, "target")
        seed(app, source[-1])
        view = post(client, payload()).json()
        preview = client.get(f"/api/v1/catalog/{source[0]}/deletion-preview").json()
        response = execute(
            client, source[0], preview, action, target[-1] if action == "move" else None
        )
        assert response.status_code == 200, response.text
        with app.state.database.transaction() as connection:
            count = connection.execute("SELECT count(*) FROM run_diagram_views").fetchone()[0]
        assert count == (0 if action == "delete" else 1)
        response = client.get(f"/api/v1/runs/run1/diagram-views/{view['id']}")
        assert response.status_code == (404 if action == "delete" else 200)
