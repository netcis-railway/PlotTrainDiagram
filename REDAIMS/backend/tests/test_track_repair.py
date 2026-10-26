from copy import deepcopy
from datetime import date, datetime
from io import BytesIO

import pytest
from app.base_timetables.track_repair import (
    TrainChoice,
    allocate,
    default_direction,
    interval,
    overlaps,
)
from app.core.config import Settings
from app.ingest.base_parser import parse_base
from app.ingest.inspection import inspect_workbook
from app.main import create_app
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from test_base_import import commit, create_base, preview
from test_catalog_deletion import branch
from test_run_import import commit as run_commit
from test_run_import import preview as run_preview


def workbook(missing=False, result=False):
    book = Workbook()
    table = book.active
    table.title = "TTT1"
    names = ["G1", "G2/G3"]
    table.append(
        ["NODE_NAME_CHN", "NODE_IND", "NODE_CODE", "LINE_IND", "NODE_NAME"]
        + [f"{name}_{suffix}" for name in names for suffix in ("A", "D", "G", "SEQ")]
    )
    table.append(
        [
            "甲",
            1,
            "P",
            1,
            "P",
            None,
            datetime(2025, 5, 25, 7),
            None,
            41,
            None,
            datetime(2025, 5, 25, 7, 0, 30),
            None,
            41,
        ]
    )
    table.append(
        [
            "乙",
            2,
            "Q",
            1,
            "Q",
            datetime(2025, 5, 25, 7, 2),
            datetime(2025, 5, 25, 7, 3),
            None,
            42,
            datetime(2025, 5, 25, 7, 2, 30),
            datetime(2025, 5, 25, 7, 3, 30),
            None,
            42,
        ]
    )
    if missing:
        table.delete_cols(12)
        table.delete_cols(8)
    if not result:
        line = book.create_sheet("LINE_INFO")
        line.append(["LINE_IND", "LINE_CODE", "LINE_NAME_CHN", "NUM_NODE"])
        line.append([1, "L", "测试线路", 2])
        nodes = book.create_sheet("NODE_INFO")
        nodes.append(
            [
                "LINE_IND",
                "LINE_CODE",
                "LINE_NAME_CHN",
                "NODE_SEQ_OF_LINE",
                "NODE_NAME_CHN",
                "NODE_IND",
                "NODE_CODE",
                "NODE_NAME",
                "DB_TRACKS",
                "UB_TRACKS",
            ]
        )
        nodes.append([1, "L", "测试线路", 1, "甲", 1, "P", "P", "[9,10]/11", "[6,7]/8"])
        nodes.append([1, "L", "测试线路", 2, "乙", 2, "Q", "Q", "[9,10]/11", "[6,7]/8"])
        minimum = book.create_sheet("MINIMUM_RUN_TIME")
        minimum.append(
            [
                "LINK_START_NODE_CODE",
                "LINK_END_NODE_CODE",
                "START_ACTIVITY",
                "END_ACTIVITY",
                "MINIMUM_RUN_TIME",
                "MINIMUM_RUN_TIME_SEC",
            ]
        )
        minimum.append(["P", "Q", "PASS", "PASS", "00:02:00", 120])
    output = BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def choice(tid, directions=("UB",), line=1):
    return TrainChoice(train_id=tid, lines=[{"line_ind": line, "directions": list(directions)}])


def small_doc():
    def event(tid, start=10, end=20, track=None):
        return {
            "id": tid,
            "train_id": tid,
            "node_name": "P",
            "train_course_id": tid,
            "arrival": {"seconds": start},
            "departure": {"seconds": end},
            "track_code": track,
        }

    doc = {
        "trains": [{"id": "G1", "train_course_id": "G1"}, {"id": "G3", "train_course_id": "G3"}],
        "nodes": [{"node_name": "P", "node_name_chn": "甲"}],
        "events": [event("G1"), event("G3")],
    }
    infra = {
        "lines": [{"LINE_IND": 1}],
        "members": [
            {"node_name": "P", "line_ind": 1, "UB_TRACKS": "[6,7]/8", "DB_TRACKS": "[9]/10"}
        ],
    }
    return doc, infra


@pytest.mark.parametrize(
    "course,direction",
    [("G109", "DB"), ("G108", "UB"), ("G1914/G1911", "UB"), ("D0001", "DB"), ("NoNumber", None)],
)
def test_default_direction_obeys_user_parity_and_first_course(course, direction):
    assert default_direction(course) == direction


def test_allocator_uses_selected_resources_and_nonoverlap_without_mutating_document():
    doc, infra = small_doc()
    before = deepcopy(doc)
    result = allocate(doc, infra, [choice("G1"), choice("G3")])
    assert result["can_apply"] and {c["value"] for c in result["changes"]} == {6, 7}
    assert doc == before
    assert overlaps((10, 20), (19, 30)) and not overlaps((10, 20), (20, 30))
    doc["events"][1]["arrival"]["seconds"] = 20
    doc["events"][1]["departure"]["seconds"] = 30
    result = allocate(doc, infra, [choice("G1"), choice("G3")])
    assert result["can_apply"] and {c["value"] for c in result["changes"]} == {6}


def test_allocator_keeps_unselected_trains_fixed_across_lines_and_prioritizes_roles():
    doc, infra = small_doc()
    doc["events"][1]["track_code"] = 6
    # Reservation follows the selected event in source order.
    result = allocate(doc, infra, [choice("G1")])
    assert result["can_apply"] and result["changes"][0]["value"] == 7
    infra["members"].append(
        {"node_name": "P", "line_ind": 2, "UB_TRACKS": "[6]/6", "DB_TRACKS": "[]"}
    )
    infra["lines"].append({"LINE_IND": 2})
    result = allocate(doc, infra, [choice("G1", line=2)])
    assert not result["can_apply"] and result["changes"] == []
    doc["events"][0]["departure"]["seconds"] = 10
    result = allocate(doc, infra, [choice("G1")])
    assert result["changes"][0]["value"] == 8  # passage prefers main line
    assert interval(doc["events"][0]) == (10, 11)


def test_allocator_backtracks_and_reports_capacity_time_unknown_and_bad_selection():
    doc, infra = small_doc()
    infra["members"][0].update(UB_TRACKS="[6]", DB_TRACKS="[7]")
    # Flexible train must yield track 6 to the restricted train.
    result = allocate(doc, infra, [choice("G1", ("UB", "DB")), choice("G3")])
    assert result["can_apply"]
    assert {c["event_id"]: c["value"] for c in result["changes"]} == {"G1": 7, "G3": 6}
    result = allocate(doc, infra, [choice("G1"), choice("G3")])
    assert not result["can_apply"] and "容量不足" in result["issues"][0]["message"]
    infra["members"][0]["UB_TRACKS"] = None
    assert not allocate(doc, infra, [choice("G1")])["can_apply"]
    doc["events"][0]["departure"]["seconds"] = 9
    assert "出发早于" in allocate(doc, infra, [choice("G1")])["issues"][0]["message"]
    with pytest.raises(ValueError, match="不存在或重复"):
        allocate(doc, infra, [choice("unknown")])
    with pytest.raises(ValueError, match="线路不存在"):
        allocate(doc, infra, [choice("G1", line=99)])


def test_missing_g_preflight_reports_each_train_and_correct_header_without_sequence_noise():
    source = workbook(missing=True)
    structure = inspect_workbook(source)
    assert structure["sheets"][0]["trains"] == ["G1", "G2/G3"]
    report = parse_base(source, date(2025, 5, 25), "rebase", track_lists=True)
    problems = [i for i in report["issues"] if i["field"].endswith("_G")]
    assert [(i["field"], i["cell"]) for i in problems] == [("G1_G", "H1"), ("G2/G3_G", "K1")]
    assert not any(i["field"].endswith("_SEQ") for i in report["issues"])


@pytest.mark.parametrize("kind", ["base", "run"])
def test_import_repair_repreflight_editor_save_export_and_stale_rejection(tmp_path, kind):
    source = workbook(missing=True, result=kind == "run")
    app = create_app(Settings(database=tmp_path / "repair.duckdb"))
    with TestClient(app) as client:
        ids = branch(client, "repair")
        if kind == "run":
            create_base(client, ids[2], workbook())
            response = run_preview(client, ids[-1], source)
        else:
            response = preview(client, ids[2], source)
        assert response.status_code == 201, response.text
        job = response.json()
        assert not job["report"]["can_commit"]
        url = f"/api/v1/ingest/jobs/{job['job_id']}/track-repair"
        response = client.get(url + "/context")
        assert response.status_code == 200, response.text
        ctx = response.json()
        assert [t["direction"] for t in ctx["trains"]] == ["DB", "UB"]
        assert all(t["missing_g"] and t["related_lines"] == [1] for t in ctx["trains"])
        body = {
            "repair_token": ctx["repair_token"],
            "selections": [choice(t["id"], (t["direction"],)).model_dump() for t in ctx["trains"]],
        }
        assert client.post(url + "/apply", json=body | {"repair_token": "stale"}).status_code == 409
        partial = client.post(url + "/apply", json=body | {"selections": body["selections"][:1]})
        assert partial.status_code == 200, partial.text
        assert any(
            i.get("field") == "G2/G3_G"
            for i in parse_base(
                partial.content,
                date(2025, 5, 25),
                "rebase",
                track_lists=True,
                result_context={} if kind == "run" else None,
            )["issues"]
        )
        fixed = client.post(url + "/apply", json=body)
        assert fixed.status_code == 200 and "spreadsheetml" in fixed.headers["content-type"], (
            fixed.text
        )
        book = load_workbook(BytesIO(fixed.content))
        table = book["TTT1"]
        assert [c.value for c in table[1]][5:] == [
            f"{c}_{f}" for c in ("G1", "G2/G3") for f in ("A", "D", "G", "SEQ")
        ]
        assert table["H2"].value == 9 and table["L2"].value == 6
        assert table["I2"].value == table["M2"].value == 41
        book.close()
        # Original staged source and failed preflight are untouched.
        assert client.get(url + "/context").json()["repair_token"] == ctx["repair_token"]
        second = (
            run_preview(client, ids[-1], fixed.content).json()
            if kind == "run"
            else preview(client, ids[2], fixed.content).json()
        )
        assert second["report"]["can_commit"], second["report"]["issues"]
        saved = (run_commit if kind == "run" else commit)(client, second)
        assert saved.status_code == 200, saved.text
        object_id = saved.json()["id"]
        object_url = f"/api/v1/{'runs' if kind == 'run' else 'base-timetables'}/{object_id}"
        data = client.get(object_url + "/tables").json()
        before = deepcopy(data["events"])
        edit_url = f"/api/v1/track-repair/{kind}/{object_id}"
        pending = {
            "revision": data["revision"],
            "changes": [{"event_id": data["events"][0]["id"], "field": "track_code", "value": 999}],
        }
        ctx = client.post(edit_url + "/context", json=pending).json()
        assert "repair_token" in ctx, ctx
        choices = [choice(t["id"], (t["direction"],)).model_dump() for t in ctx["trains"]]
        applied = client.post(
            edit_url + "/apply",
            json=pending | {"repair_token": ctx["repair_token"], "selections": choices},
        )
        assert applied.status_code == 200 and applied.json()["can_apply"], applied.text
        assert client.get(object_url + "/tables").json()["events"] == before
        changes = applied.json()["changes"]
        assert len(changes) == 4
        edit = {"revision": data["revision"], "changes": changes}
        validation = client.post(object_url + "/events/validate", json=edit).json()
        assert validation["can_save"], validation
        saved = client.post(
            object_url + "/events/edit",
            json=edit
            | {
                "validation_token": validation["validation_token"],
                "warnings_confirmed": True,
                "train_dates_confirmed": True,
            },
        )
        assert saved.status_code == 200, saved.text
        assert (
            client.post(
                edit_url + "/apply",
                json=pending | {"repair_token": ctx["repair_token"], "selections": choices},
            ).status_code
            == 409
        )
        latest = saved.json()
        exported = client.post(
            object_url + "/export", params={"revision": latest["revision"], "sheets": "TTT"}
        )
        assert exported.status_code == 200, exported.text
        out = load_workbook(BytesIO(exported.content))
        assert any(cell.value == "G1_G" for cell in out.active[1])
        out.close()
