from copy import deepcopy

import pytest
from app.core.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient
from test_base_import import create_base
from test_catalog_deletion import branch
from test_run_import import commit as run_commit
from test_run_import import preview as run_preview
from test_track_repair import workbook


@pytest.mark.parametrize("kind", ["base", "run"])
def test_complete_train_shift_uses_pending_edits_preserves_other_fields_and_saves_cross_day(
    tmp_path, kind
):
    app = create_app(Settings(database=tmp_path / "shift.duckdb"))
    with TestClient(app) as client:
        ids = branch(client, "shift")
        _, base = create_base(client, ids[2], workbook())
        object_id = base["id"]
        if kind == "run":
            job = run_preview(client, ids[-1], workbook(result=True)).json()
            result = run_commit(client, job)
            assert result.status_code == 200, result.text
            object_id = result.json()["id"]
        url = f"/api/v1/{'runs' if kind == 'run' else 'base-timetables'}/{object_id}"
        endpoint = f"/api/v1/time-shift/{kind}/{object_id}/preview"
        data = client.get(url + "/tables").json()
        tid = next(t["id"] for t in data["trains"] if t["train_course_id"] == "G1")
        first = next(e for e in data["events"] if e["train_id"] == tid and e["node_name"] == "P")
        initial = deepcopy(data)
        pending = [
            {"event_id": first["id"], "field": "departure", "value": "07:00:10"},
            {"event_id": first["id"], "field": "track_code", "value": 6},
        ]
        request = {
            "revision": data["revision"],
            "changes": pending,
            "train_ids": [tid],
            "offset_seconds": 86461,
        }
        response = client.post(endpoint, json=request)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["can_apply"], result["issues"]
        assert result["trains"] == [{"id": tid, "train_course_id": "G1", "visits": 2, "cells": 3}]
        assert (
            len(result["changes"]) == 3
        )  # P departure + Q arrival/departure, even if Q is hidden in UI.
        assert all(change["field"] in ("arrival", "departure") for change in result["changes"])
        first_change = next(c for c in result["changes"] if c["event_id"] == first["id"])
        assert first_change["value"] == "31:01:11"
        assert result["train_date_changes"][0]["after"] == "2025-05-26"
        assert client.get(url + "/tables").json() == initial  # preview is read-only
        assert client.post(endpoint, json=request | {"revision": "stale"}).status_code == 409
        for invalid in (
            {"offset_seconds": 0},
            {"train_ids": [tid, tid]},
            {"train_ids": ["foreign"]},
            {"offset_seconds": 1.5},
        ):
            assert client.post(endpoint, json=request | invalid).status_code == 422
        assert client.post(endpoint, json=request | {"offset_seconds": -100000}).status_code == 422
        assert client.get(url + "/tables").json() == initial
        merged = {(c["event_id"], c["field"]): c for c in pending}
        merged.update({(c["event_id"], c["field"]): c for c in result["changes"]})
        edits = {"revision": data["revision"], "changes": list(merged.values())}
        validation = client.post(url + "/events/validate", json=edits).json()
        assert validation["can_save"], validation["issues"]
        saved = client.post(
            url + "/events/edit",
            json=edits
            | {
                "validation_token": validation["validation_token"],
                "train_dates_confirmed": True,
                "warnings_confirmed": True,
            },
        )
        assert saved.status_code == 200, saved.text
        latest = saved.json()
        for event in latest["events"]:
            old = next(e for e in initial["events"] if e["id"] == event["id"])
            assert event["visit_seq"] == old["visit_seq"]
            if event["train_id"] != tid:
                assert event == old
            else:
                assert event["track_code"] == (
                    6 if event["id"] == first["id"] else old["track_code"]
                )
                assert (
                    event["arrival"] is None
                    if old["arrival"] is None
                    else event["arrival"]["seconds"] == old["arrival"]["seconds"] + 86461
                )
        assert client.post(endpoint, json=request).status_code == 409
        # An explicit negative shift is supported; it cannot silently wrap before date_base.
        restored = client.post(
            endpoint,
            json={
                "revision": latest["revision"],
                "changes": [],
                "train_ids": [tid],
                "offset_seconds": -86461,
            },
        )
        assert restored.status_code == 200 and restored.json()["can_apply"], restored.text
        assert (
            next(c for c in restored.json()["changes"] if c["event_id"] == first["id"])["value"]
            == "07:00:10"
        )
        if kind == "run":
            assert (
                client.get(f"/api/v1/base-timetables/{base['id']}/tables").json()["events"]
                != latest["events"]
            )


def test_shift_rejects_invalid_pending_time_and_date_overflow_without_writes(tmp_path):
    app = create_app(Settings(database=tmp_path / "invalid.duckdb"))
    with TestClient(app) as client:
        ids = branch(client, "shift-negative")
        _, base = create_base(client, ids[2], workbook())
        url = f"/api/v1/base-timetables/{base['id']}/tables"
        endpoint = f"/api/v1/time-shift/base/{base['id']}/preview"
        data = client.get(url).json()
        train = data["trains"][0]
        event = next(e for e in data["events"] if e["train_id"] == train["id"])
        body = {
            "revision": data["revision"],
            "changes": [{"event_id": event["id"], "field": "departure", "value": "bad-time"}],
            "train_ids": [train["id"]],
            "offset_seconds": 60,
        }
        response = client.post(endpoint, json=body)
        assert response.status_code == 200 and not response.json()["can_apply"]
        assert response.json()["changes"] == []
        response = client.post(
            endpoint,
            json=body | {"changes": [], "date_base": "9999-12-31", "offset_seconds": 86400},
        )
        assert response.status_code == 200 and not response.json()["can_apply"], response.text
        assert client.get(url).json() == data
