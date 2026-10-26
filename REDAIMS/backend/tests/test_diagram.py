from copy import deepcopy

from app.base_timetables.editing import EditorService
from app.base_timetables.service import TimetableService
from app.core.config import Settings
from app.diagram.axis import build_axis
from app.diagram.series import build_series
from app.diagram.service import PlotService
from app.diagram.styles import StyleLoader
from app.main import create_app
from app.storage.database import Database
from fastapi.testclient import TestClient
from sample_workbook import SAMPLE_WORKBOOK
from test_base_import import create_base
from test_base_replace import seed_result
from test_catalog_deletion import branch


def infrastructure():
    return {
        "nodes": [
            {
                "id": name,
                "node_name": name,
                "node_name_chn": name.upper(),
                "node_code": name.upper(),
                "node_ind": index,
            }
            for name, index in [("c", 1), ("a", 99), ("b", 5)]
        ],
        "lines": [{"LINE_IND": 1, "LINE_CODE": "L", "LINE_NAME_CHN": "测试线"}],
        "members": [
            {
                "node_name": name,
                "line_ind": 1,
                "NODE_SEQ_OF_LINE": seq,
                "NODE_CODE": name.upper(),
                "NODE_NAME_CHN": name.upper(),
            }
            for name, seq in [("c", 3), ("a", 1), ("b", 2)]
        ],
        "minimum_run_times": [
            {
                "LINK_START_NODE_CODE": "A",
                "LINK_END_NODE_CODE": "B",
                "START_ACTIVITY": "PASS",
                "END_ACTIVITY": "PASS",
                "MINIMUM_RUN_TIME": "00:00:10",
                "MINIMUM_RUN_TIME_SEC": 10,
                "seconds": 10,
            },
            {
                "LINK_START_NODE_CODE": "B",
                "LINK_END_NODE_CODE": "C",
                "START_ACTIVITY": "PASS",
                "END_ACTIVITY": "PASS",
                "MINIMUM_RUN_TIME": "00:00:20",
                "MINIMUM_RUN_TIME_SEC": 20,
                "seconds": 20,
            },
        ],
    }


def event(node, seq, arrival, departure):
    def time(value):
        return (
            None
            if value is None
            else {"seconds": value, "hms": "00:00:00", "day_offset": value // 86400}
        )

    return {
        "id": f"e{node}",
        "train_id": "t",
        "node_id": node,
        "node_name": node,
        "visit_seq": seq,
        "track_code": None,
        "arrival": time(arrival),
        "departure": time(departure),
        "source": {"sheet": "TTT", "row": seq + 1},
    }


def series(events):
    axis, errors = build_axis(infrastructure(), 1)
    assert not errors
    doc = {
        "events": events,
        "trains": [{"id": "t", "train_course_id": "G1", "train_base_date": "2025-06-01"}],
    }
    return build_series({"id": "r", "object_type": "run", "name": "结果"}, doc, axis)


def test_axis_uses_station_sequence_and_directed_pass_times_not_source_rows_or_node_index():
    source = infrastructure()
    before = deepcopy(source)
    axis, errors = build_axis(source, 1)
    assert not errors
    assert [(s["node_id"], s["node_seq_of_line"], s["y"]) for s in axis["stations"]] == [
        ("a", 1, 0),
        ("b", 2, 10),
        ("c", 3, 30),
    ]
    assert axis["total"] == 30 and source == before
    source["nodes"].reverse()
    source["members"].reverse()
    source["minimum_run_times"].reverse()
    assert build_axis(source, 1)[0] == axis


def test_axis_rejects_missing_ambiguous_or_inconsistent_intervals_and_missing_station_order():
    for mode in ("reverse", "duplicate", "mismatch", "missing_seq"):
        source = infrastructure()
        if mode == "reverse":
            source["minimum_run_times"][0]["LINK_START_NODE_CODE"] = "B"
            source["minimum_run_times"][0]["LINK_END_NODE_CODE"] = "A"
        elif mode == "duplicate":
            source["minimum_run_times"].append(deepcopy(source["minimum_run_times"][0]))
        elif mode == "mismatch":
            source["minimum_run_times"][0]["MINIMUM_RUN_TIME_SEC"] = 12
        else:
            source["members"][1]["NODE_SEQ_OF_LINE"] = None
        axis, errors = build_axis(source, 1)
        assert errors and not axis["stations"]


def test_missing_times_and_non_line_visits_do_not_create_a_shortcut_and_midnight_is_a_real_point():
    items, warnings = series(
        [event("a", 1, None, 0), event("b", 2, None, 60), event("c", 3, 100, None)]
    )
    item = items[0]
    assert item["points"][0]["seconds"] == 0
    assert [
        (item["points"][s["from"]]["event_id"], item["points"][s["to"]]["event_id"])
        for s in item["segments"]
    ] == [("eb", "ec")]
    assert any(i["code"] == "missing_time" for i in warnings)
    items, _ = series(
        [event("a", 1, None, 0), event("outside", 2, 50, 60), event("c", 3, 100, None)]
    )
    assert not items[0]["segments"] and len(items[0]["points"]) == 2


def test_direction_and_segments_follow_seq_with_cross_day_and_time_inversion_kept_for_review():
    items, _ = series(
        [event("a", 3, 91000, None), event("c", 1, None, 86000), event("b", 2, 90000, 90030)]
    )
    assert items[0]["direction"] == "up"
    assert [p["seconds"] for p in items[0]["points"]] == [86000, 90000, 90030, 91000]
    items, warnings = series([event("a", 1, None, 100), event("b", 2, 50, None)])
    assert items[0]["segments"][0]["anomaly"]
    assert any(i["code"] == "time_order" for i in warnings)


def test_plot_api_resolves_real_base_shared_axis_overlay_and_keeps_saved_data_unchanged(tmp_path):
    settings = Settings(database=tmp_path / "db")
    app = create_app(settings)
    with TestClient(app) as client:
        ids = branch(client, "plot")
        _, base = create_base(client, ids[2], SAMPLE_WORKBOOK.read_bytes())
        base_url = f"/api/v1/base-timetables/{base['id']}/tables"
        before = client.get(base_url).json()
        context = client.get(
            "/api/v1/diagram/lines", params={"object_type": "base", "object_id": base["id"]}
        ).json()
        assert next(line for line in context["lines"] if line["line_ind"] == 1)["available"]
        body = {
            "object_type": "base",
            "object_id": base["id"],
            "revision": context["revision"],
            "line_ind": 1,
        }
        response = client.post("/api/v1/diagram/data", json=body)
        assert response.status_code == 200, response.text
        plotted = response.json()
        assert plotted["can_plot"], plotted["issues"]
        assert len(plotted["axis"]["stations"]) == 23
        seed_result(app, client, ids[-1], base)
        run_context = client.get(
            "/api/v1/diagram/lines", params={"object_type": "run", "object_id": "result"}
        ).json()
        run = client.post(
            "/api/v1/diagram/data",
            json={
                "object_type": "run",
                "object_id": "result",
                "revision": run_context["revision"],
                "line_ind": 1,
                "overlay_base": True,
            },
        ).json()
        assert run["can_plot"] and run["base"]["id"] == base["id"]
        assert run["axis"] == plotted["axis"]
        assert {s["object_type"] for s in run["series"]} == {"base", "run"}
        assert len(run["series"]) == 20
        assert client.get(base_url).json()["events"] == before["events"]
        stale = client.post("/api/v1/diagram/data", json=body)
        assert stale.status_code == 409
        invalid = client.post(
            "/api/v1/diagram/data",
            json={
                "object_type": "run",
                "object_id": "result",
                "revision": run_context["revision"],
                "line_ind": 999,
            },
        ).json()
        assert not invalid["can_plot"] and invalid["log_written"]
        assert invalid["operation_id"] in client.get("/api/v1/diagram/warnings").json()["text"]
        style_response = client.get("/api/v1/diagram/styles")
        assert style_response.status_code == 200
        assert style_response.json()["styles"]["down"] == plotted["styles"]["down"]
        assert style_response.json()["log_written"]


def test_plot_draft_is_read_only_and_different_dates_block_overlay(tmp_path):
    app = create_app(Settings(database=tmp_path / "db"))
    with TestClient(app) as client:
        ids = branch(client, "draft")
        _, base = create_base(client, ids[2], SAMPLE_WORKBOOK.read_bytes())
        seed_result(app, client, ids[-1], base)
        url = "/api/v1/runs/result/tables"
        before = client.get(url).json()
        event_id = next(e["id"] for e in before["events"] if e["departure"])
        body = {
            "object_type": "run",
            "object_id": "result",
            "revision": before["revision"],
            "line_ind": 1,
            "changes": [{"event_id": event_id, "field": "departure", "value": "25:10:00"}],
        }
        response = client.post("/api/v1/diagram/data", json=body).json()
        assert response["can_plot"] and response["preview"]
        assert any(
            p["event_id"] == event_id and p["seconds"] == 90600
            for s in response["series"]
            for p in s["points"]
        )
        assert client.get(url).json() == before
        body["changes"] = []
        body["date_base"] = "2025-06-01"
        body["overlay_base"] = True
        blocked = client.post("/api/v1/diagram/data", json=body).json()
        assert not blocked["can_plot"] and any(
            i["code"] == "comparison_date" for i in blocked["issues"]
        )
        body["overlay_base"] = False
        assert client.post("/api/v1/diagram/data", json=body).json()["can_plot"]
        body["changes"] = [{"event_id": event_id, "field": "departure", "value": "bad"}]
        assert not client.post("/api/v1/diagram/data", json=body).json()["can_plot"]
        assert client.get(url).json() == before


def test_styles_keep_last_valid_json_and_log_failure_is_reported(tmp_path):
    path = tmp_path / "styles.json"
    loader = StyleLoader(path)
    path.write_text('{"down":"#112233"}', encoding="utf-8")
    assert loader.read()[0]["down"] == "#112233"
    path.write_text('{"down":"invalid"}', encoding="utf-8")
    styles, errors = loader.read()
    assert styles["down"] == "#112233" and errors
    log_file = tmp_path / "not-a-directory"
    log_file.write_text("x", encoding="utf-8")
    database = Database(tmp_path / "db")
    service = PlotService(
        EditorService(TimetableService(database, Settings(database=database.path, logs=log_file)))
    )
    issues = [{"code": "test", "severity": "warning", "message": "test"}]
    _, written = service.log(issues, {})
    assert not written and issues[-1]["code"] == "log_failure"
    service.styles.path = path
    assert not service.style_config()["log_written"]
    assert not service.style_config()["log_written"]
