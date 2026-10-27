from copy import deepcopy

import pytest
from app.analysis.delays import calculate_delays
from app.api.v1 import run_analysis
from app.core.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient
from sample_workbook import SAMPLE_WORKBOOK
from test_base_import import create_base
from test_base_replace import seed_result
from test_catalog_deletion import branch, execute, seed
from test_diagram_views import payload as diagram_payload


def delay_section(run="run1"):
    return {
        "state": {
            "station_ids": ["s"],
            "train_ids": ["t"],
            "highlighted_ids": ["t"],
            "station_search": "济南",
            "train_search": "G",
            "open_panels": ["stations"],
            "unit": "minutes",
            "chart_height": 480,
            "scroll_top": 100,
            "scroll_left": 250,
            "viewport": {"x0": -0.2, "x1": 2, "y0": -10, "y1": 180},
        },
        "snapshot": {
            "version": 1,
            "object": {"id": run},
            "base": {"id": "base"},
            "stations": [{"id": "s"}],
            "trains": [{"id": "t"}],
            "rows": [],
            "cells": [],
        },
    }


def state(log_id=""):
    return {
        "version": 1,
        "expanded_sections": ["diagram", "log", "delay"],
        "diagram": diagram_payload(),
        "log": {
            "log_id": log_id,
            "encoding": "gb18030",
            "search": "目标",
            "wrap": False,
            "scroll_top": 240,
            "scroll_left": 35,
            "visualization_state": {"train_ids": ["G1"], "x_range": [1, 20]},
        },
        "delay": delay_section(),
    }


def test_all_three_node_types_roundtrip_with_full_workspace_and_immutable_log(tmp_path):
    settings = Settings(database=tmp_path / "analysis.duckdb")
    app = create_app(settings)
    with TestClient(app) as client:
        ids = branch(client, "analysis")
        seed(app, ids[-1])
        seed(app, ids[-1], "other")
        content = "目标值=12\n求解完成\n".encode("gb18030")
        log = client.post(
            "/api/v1/runs/run1/solver-logs", params={"filename": "solver.txt"}, content=content
        ).json()
        assert client.get("/api/v1/analysis/logs").json() == [
            {"id": log["id"], "run_id": "run1", "filename": "solver.txt"}
        ]
        text_url = f"/api/v1/runs/run1/solver-logs/{log['id']}/text"
        assert client.get(text_url).status_code == 422
        text = client.get(text_url, params={"encoding": "gb18030"}).json()
        assert text["text"] == content.decode("gb18030")
        assert text["digest"] == log["digest"]
        assert client.get(text_url, params={"encoding": "unsafe"}).status_code == 422
        assert client.get(f"/api/v1/runs/other/solver-logs/{log['id']}/text").status_code == 404
        saved = []
        for kind in ["view", "solver-log", "delay"]:
            body = {"node_type": kind, "name": "同一个对比", "state": state(log["id"])}
            response = client.post("/api/v1/runs/run1/analysis-nodes", json=body)
            assert response.status_code == 201, response.text
            summary = response.json()
            assert "state" not in summary
            url = f"/api/v1/runs/run1/analysis-nodes/{summary['id']}"
            result = client.get(url).json()
            # Model defaults are public so clients can restore older optional settings.
            assert result["state"]["log"] == body["state"]["log"]
            assert result["state"]["delay"] == body["state"]["delay"]
            assert result["state"]["expanded_sections"] == ["diagram", "log", "delay"]
            assert result["state"]["diagram"]["snapshot"] == body["state"]["diagram"]["snapshot"]
            saved.append((url, result))
            assert client.post("/api/v1/runs/run1/analysis-nodes", json=body).status_code == 409
            assert (
                client.get(f"/api/v1/runs/other/analysis-nodes/{summary['id']}").status_code == 404
            )
        assert len(client.get("/api/v1/analysis/nodes").json()) == 3
        assert client.get("/api/v1/diagram/views").json() == []
        with app.state.database.transaction() as c:
            assert c.execute("SELECT count(*) FROM timetable_events").fetchone()[0] == 0
    with TestClient(create_app(settings)) as client:
        for url, result in saved:
            assert client.get(url).json() == result


def test_invalid_foreign_and_oversized_analysis_states_do_not_write(tmp_path, monkeypatch):
    app = create_app(Settings(database=tmp_path / "invalid.duckdb"))
    with TestClient(app) as client:
        ids = branch(client, "invalid")
        seed(app, ids[-1])
        body = {"node_type": "view", "name": "比较", "state": state()}
        changes = [
            lambda b: b.update(name="  "),
            lambda b: b.update(node_type="unknown"),
            lambda b: b["state"].update(expanded_sections=["unknown"]),
            lambda b: b["state"].update(diagram=None),
            lambda b: b["state"]["log"].update(log_id="other-run-log"),
            lambda b: b["state"]["delay"]["state"].update(train_ids=["foreign"]),
            lambda b: b["state"]["delay"]["state"]["viewport"].update(x1=-1),
            lambda b: b["state"]["delay"]["snapshot"]["object"].update(id="other"),
            lambda b: b["state"]["diagram"]["snapshot"]["data"]["object"].update(id="other"),
        ]
        for change in changes:
            bad = deepcopy(body)
            change(bad)
            response = client.post("/api/v1/runs/run1/analysis-nodes", json=bad)
            assert response.status_code == 422, response.text
        absent = deepcopy(body)
        absent["state"]["diagram"]["snapshot"]["context"]["object"]["id"] = "missing"
        absent["state"]["diagram"]["snapshot"]["data"]["object"]["id"] = "missing"
        absent["state"]["diagram"]["snapshot"]["data"]["series"][0]["object_id"] = "missing"
        absent["state"]["delay"]["snapshot"]["object"]["id"] = "missing"
        assert client.post("/api/v1/runs/missing/analysis-nodes", json=absent).status_code == 404
        monkeypatch.setattr(run_analysis, "MAX_ANALYSIS_BYTES", 10)
        assert client.post("/api/v1/runs/run1/analysis-nodes", json=body).status_code == 413
        assert client.get("/api/v1/analysis/nodes").json() == []


@pytest.mark.parametrize("action", ["delete", "ungroup", "move"])
def test_analysis_node_lifecycle(tmp_path, action):
    app = create_app(Settings(database=tmp_path / "life.duckdb"))
    with TestClient(app) as client:
        source, target = branch(client, "source"), branch(client, "target")
        seed(app, source[-1])
        saved = client.post(
            "/api/v1/runs/run1/analysis-nodes",
            json={"node_type": "view", "name": "视图", "state": state()},
        )
        assert saved.status_code == 201, saved.text
        preview = client.get(f"/api/v1/catalog/{source[0]}/deletion-preview").json()
        assert (
            execute(
                client, source[0], preview, action, target[-1] if action == "move" else None
            ).status_code
            == 200
        )
        with app.state.database.transaction() as c:
            assert c.execute("SELECT count(*) FROM run_analysis_nodes").fetchone()[0] == (
                0 if action == "delete" else 1
            )


def test_real_delay_api_compares_current_saved_run_and_effective_base(tmp_path):
    app = create_app(Settings(database=tmp_path / "delay.duckdb"))
    with TestClient(app) as client:
        ids = branch(client, "delay")
        _, base = create_base(client, ids[2], SAMPLE_WORKBOOK.read_bytes())
        seed_result(app, client, ids[-1], base)
        before = client.get("/api/v1/runs/result/tables").json()
        response = client.get("/api/v1/runs/result/delay-analysis")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["base"]["id"] == base["id"]
        assert data["object"]["id"] == "result"
        assert data["rows"] and data["cells"]
        assert all(c["arrival"] in (0, None) and c["departure"] in (0, None) for c in data["cells"])
        edited = next(e for e in before["events"] if e["arrival"] is not None)
        with app.state.database.transaction() as c:
            c.execute(
                "UPDATE timetable_events SET arrival_seconds=arrival_seconds+125 WHERE id=?",
                [edited["id"]],
            )
        changed = client.get("/api/v1/runs/result/delay-analysis").json()
        assert any(c["arrival"] == 125 for c in changed["cells"])
        assert client.get("/api/v1/runs/missing/delay-analysis").status_code == 404
        seed(app, ids[-1], "no-base")
        with app.state.database.transaction() as c:
            c.execute("UPDATE runs SET batch_id=NULL WHERE id='no-base'")
        assert client.get("/api/v1/runs/no-base/delay-analysis").status_code == 422


def test_delay_math_cross_day_repeated_stations_missing_and_ambiguous():
    def event(id, seq, a, d, name="S"):
        return {
            "id": id,
            "train_id": "t",
            "visit_seq": seq,
            "node_id": name,
            "node_name": name,
            "arrival": None if a is None else {"seconds": a},
            "departure": None if d is None else {"seconds": d},
        }

    train = {"id": "t", "train_course_id": "G1", "train_base_date": "2025-04-09"}
    actual = {
        "trains": [train],
        "events": [event("a1", 1, 86370, 86440), event("a2", 2, 90100, None)],
    }
    planned = {
        "trains": [train],
        "events": [event("p1", 1, 86400, 86400), event("p2", 2, 90000, 90100)],
    }
    meta = {"id": "r", "date_base": "2025-04-08"}
    stations = [{"id": "S", "node_name_chn": "重复站"}]
    result = calculate_delays(meta, actual, meta, planned, stations, "rev")
    assert [(c["arrival"], c["departure"]) for c in result["cells"]] == [(-30, 40), (100, None)]
    assert [r["occurrence"] for r in result["rows"]] == [1, 2]
    assert result["cells"][1]["departure_reason"] == "run缺少时刻"
    # Different runtime baselines still compare absolute datetimes, not clock modulo 24h.
    shifted = deepcopy(actual)
    for e in shifted["events"]:
        for field in ("arrival", "departure"):
            if e[field]:
                e[field]["seconds"] -= 86400
    adjusted = calculate_delays(
        {"id": "r", "date_base": "2025-04-09"}, shifted, meta, planned, stations, "rev"
    )
    assert adjusted["cells"] == result["cells"]
    ambiguous = deepcopy(planned)
    ambiguous["trains"].append(deepcopy(train))
    missing = calculate_delays(meta, actual, meta, ambiguous, stations, "rev")
    assert all(c["arrival"] is None for c in missing["cells"])
    assert missing["issues"]
    duplicate = deepcopy(actual)
    duplicate["events"][1]["visit_seq"] = 1
    uncertain = calculate_delays(meta, duplicate, meta, planned, stations, "rev")
    assert all(c["arrival"] is None and "SEQ" in c["arrival_reason"] for c in uncertain["cells"])
