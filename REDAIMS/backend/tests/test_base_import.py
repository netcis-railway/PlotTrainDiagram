from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from app.core.config import Settings
from app.ingest.base_parser import event_time, parse_base
from app.main import create_app
from fastapi.testclient import TestClient
from sample_workbook import SAMPLE_WORKBOOK
from test_catalog_deletion import branch, execute

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def sample():
    return SAMPLE_WORKBOOK.read_bytes()


def preview(client, owner, content, name="基本图", date_mode="rebase"):
    return client.post(
        "/api/v1/base-timetables/import/preview",
        params={
            "owner_category_id": owner,
            "name": name,
            "filename": "基本图.xlsx",
            "date_base": "2025-05-25",
            "date_mode": date_mode,
        },
        content=content,
    )


def confirmation(job, **extra):
    return {
        "confirmed": True,
        "preview_token": job["report"]["preview_token"],
        "date_confirmed": True,
        "train_dates_confirmed": True,
        "warnings_confirmed": True,
        **extra,
    }


def commit(client, job, **extra):
    return client.post(
        f"/api/v1/base-timetables/import/{job['job_id']}/commit", json=confirmation(job, **extra)
    )


def create_base(client, owner, sample, name="基本图"):
    response = preview(client, owner, sample, name)
    assert response.status_code == 201, response.text
    job = response.json()
    assert job["report"]["can_commit"], job["report"]["issues"]
    response = commit(client, job)
    assert response.status_code == 200, response.text
    return job, response.json()


def test_independent_import_resolution_and_restart(tmp_path, sample):
    settings = Settings(database=tmp_path / "test.duckdb")
    app = create_app(settings)
    with TestClient(app) as client:
        ids = branch(client, "source")
        job, base = create_base(client, ids[0], sample)
        assert base["baseTT_no"].startswith("BTT-")
        assert base["owner_category_id"] == ids[0]
        assert base["summary"]["events"] == 148
        assert client.get("/api/v1/runs").json() == []
        with app.state.database.transaction() as c:
            assert c.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
        physical = client.get(f"/api/v1/catalog/{ids[0]}/base-timetable").json()
        inherited = client.get(f"/api/v1/catalog/{ids[-1]}/base-timetable").json()
        assert physical["local_base"]["base_tt_id"] == base["id"]
        assert inherited["local_base"] is None and inherited["effective"]["mode"] == "inherited"
        assert inherited["effective"]["base_tt_id"] == base["id"]
        assert commit(client, job).json()["id"] == base["id"]
        file = base["source_files"][0]
        assert client.get(f"/api/v1/source-files/{file['id']}").content == sample
        assert Path(file["managed_path"]).read_bytes() == sample
    with TestClient(create_app(settings)) as client:
        assert (
            client.get(f"/api/v1/base-timetables/{base['id']}").json()["baseTT_no"]
            == base["baseTT_no"]
        )
        assert (
            len(client.get(f"/api/v1/base-timetables/{base['id']}/tables").json()["events"]) == 148
        )


def test_local_import_shields_children_and_cover_ignores_name(tmp_path, sample):
    with TestClient(create_app(Settings(database=tmp_path / "db"))) as client:
        ids = branch(client, "x")
        _, ancestor = create_base(client, ids[0], sample)
        _, child = create_base(client, ids[-1], sample, "子图")
        middle = preview(client, ids[3], sample, "案例图").json()
        assert middle["report"]["replacement"] is None
        assert all(i["id"] != ids[-1] for i in middle["report"]["impact"])
        base = commit(client, middle).json()
        replacement = preview(client, ids[3], sample, "不同名字").json()
        assert replacement["report"]["replacement"]["id"] == base["id"]
        assert commit(client, replacement).status_code == 422
        replaced = commit(client, replacement, replace_confirmed=True).json()
        assert replaced["id"] == base["id"] and replaced["baseTT_no"] == base["baseTT_no"]
        assert replaced["name"] == "不同名字"
        assert (
            client.get(f"/api/v1/catalog/{ids[-1]}/base-timetable").json()["effective"][
                "base_tt_id"
            ]
            == child["id"]
        )
        assert (
            client.get(f"/api/v1/catalog/{ids[0]}/base-timetable").json()["effective"]["base_tt_id"]
            == ancestor["id"]
        )
        assert len(client.get("/api/v1/base-timetables").json()) == 3
        assert not Path(base["source_files"][0]["managed_path"]).exists()
        assert commit(client, middle).status_code == 409


def test_stale_create_replace_and_invalid_data(tmp_path, sample):
    app = create_app(Settings(database=tmp_path / "db"))
    with TestClient(app) as client:
        ids = branch(client, "x")
        pending = preview(client, ids[2], sample).json()
        _, base = create_base(client, ids[2], sample)
        assert commit(client, pending).status_code == 409
        assert not preview(client, ids[2], sample, date_mode="preserve").json()["report"][
            "can_commit"
        ]
        replacement = preview(client, ids[2], sample).json()
        client.post("/api/v1/catalog", json={"kind": "batch", "parent_id": ids[4], "name": "new"})
        assert commit(client, replacement, replace_confirmed=True).status_code == 409
        assert client.get(f"/api/v1/base-timetables/{base['id']}").json()["revision"] == 1
        assert preview(client, ids[2], b"bad").status_code == 422
        assert preview(client, "missing", sample).status_code == 422
        assert preview(client, ids[2], sample, name="").status_code == 422
        assert preview(client, ids[2], sample, name="x" * 201).status_code == 422


def test_global_identity_and_copy_failure_recovery(tmp_path, sample, monkeypatch):
    import app.base_timetables.service as module

    app = create_app(Settings(database=tmp_path / "db"))
    with TestClient(app) as client:
        ids = branch(client, "x")
        job = preview(client, ids[3], sample).json()
        original = module.shutil.copyfile

        def fail(source, target):
            Path(target).write_bytes(b"partial")
            raise OSError("test disk failure")

        monkeypatch.setattr(module.shutil, "copyfile", fail)
        assert commit(client, job).status_code == 503
        assert client.get("/api/v1/base-timetables").json() == []
        assert not list((tmp_path / "source_files").glob("*"))
        monkeypatch.setattr(module.shutil, "copyfile", original)
        assert commit(client, job).status_code == 200
        with app.state.database.transaction() as c:
            c.execute(
                "INSERT INTO nodes VALUES (?,?,?,?)",
                [str(uuid4()), "conflict", "错误节点", "bad-code"],
            )
        # A conflicting known identity must be found at commit, even after preview.
        another = preview(client, ids[-1], sample).json()
        with app.state.database.transaction() as c:
            c.execute("UPDATE nodes SET node_name_chn='changed' WHERE node_name='BeijingNan'")
        assert commit(client, another).status_code == 409


def test_move_and_category_delete_protection(tmp_path, sample):
    app = create_app(Settings(database=tmp_path / "db"))
    with TestClient(app) as client:
        ids = branch(client, "x")
        _, base = create_base(client, ids[3], sample)
        preview_delete = client.get(f"/api/v1/catalog/{ids[3]}/deletion-preview").json()
        assert (
            len(preview_delete["physical_base_timetables"]) == 1
            and not preview_delete["can_delete"]
        )
        assert execute(client, ids[3], preview_delete, "ungroup").status_code == 422
        route = f"/api/v1/base-timetables/{base['id']}"
        plan = client.post(route + "/move-preview", json={"target_category_id": ids[-1]}).json()
        assert plan["can_move"] and plan["impact"]
        moved = client.post(
            route + "/move",
            json={
                "target_category_id": ids[-1],
                "preview_token": plan["preview_token"],
                "confirmed": True,
            },
        )
        assert moved.status_code == 200, moved.text
        assert (
            client.get(f"/api/v1/catalog/{ids[3]}/base-timetable").json()["effective"]["mode"]
            == "missing"
        )
        assert moved.json()["id"] == base["id"]
        deletion = client.get(route + "/deletion-preview").json()
        assert deletion["can_delete"]
        assert (
            client.request(
                "DELETE",
                route,
                json={"confirmed": True, "preview_token": deletion["preview_token"]},
            ).status_code
            == 200
        )
        assert client.get("/api/v1/base-timetables").json() == []


def test_move_occupied_and_stale_dependency_preview(tmp_path, sample):
    with TestClient(create_app(Settings(database=tmp_path / "db"))) as client:
        ids = branch(client, "x")
        _, base = create_base(client, ids[3], sample)
        _, child = create_base(client, ids[-1], sample)
        route = f"/api/v1/base-timetables/{base['id']}"
        plan = client.post(route + "/move-preview", json={"target_category_id": ids[-1]}).json()
        assert not plan["can_move"] and plan["occupied_base_id"] == child["id"]
        assert (
            client.post(
                route + "/move",
                json={
                    "target_category_id": ids[-1],
                    "preview_token": plan["preview_token"],
                    "confirmed": True,
                },
            ).status_code
            == 422
        )
        deletion = client.get(route + "/deletion-preview").json()
        assert not deletion["can_delete"]  # Algorithm still inherits the case basic timetable.
        assert (
            client.request(
                "DELETE",
                route,
                json={"confirmed": True, "preview_token": deletion["preview_token"]},
            ).status_code
            == 422
        )
        plan = client.post(route + "/move-preview", json={"target_category_id": ids[0]}).json()
        replacement = preview(client, ids[-1], sample).json()
        assert commit(client, replacement, replace_confirmed=True).status_code == 200
        assert (
            client.post(
                route + "/move",
                json={
                    "target_category_id": ids[0],
                    "preview_token": plan["preview_token"],
                    "confirmed": True,
                },
            ).status_code
            == 409
        )


def test_legacy_write_routes_are_retired(tmp_path):
    with TestClient(create_app(Settings(database=tmp_path / "db"))) as client:
        assert client.post("/api/v1/ingest/base/preview").status_code == 410
        assert client.put("/api/v1/bindings/anything", json={}).status_code == 410
        assert client.post("/api/v1/ingest/jobs/anything/commit", json={}).status_code == 410


def test_time_rounding_and_no_guessed_rollover(sample):
    assert event_time("25:10:00", date(2025, 5, 25), date(2025, 5, 25), "rebase") == {
        "hms": "01:10:00",
        "seconds": 90600,
        "day_offset": 1,
    }
    assert (
        event_time("23:59:59.500", date(2025, 5, 25), date(2025, 5, 25), "rebase")["seconds"]
        == 86400
    )
    with pytest.raises(ValueError):
        event_time("-01:00:00", date.today(), date.today(), "rebase")
    result = parse_base(sample, date(2025, 5, 25), "rebase")
    assert not [i for i in result["issues"] if i["severity"] == "error"]


def test_cell_level_validation_and_cross_day_dates(sample):
    from datetime import datetime
    from io import BytesIO

    from openpyxl import load_workbook

    workbook = load_workbook(BytesIO(sample))
    table = workbook["TTT1base"]
    table["M2"] = 0  # G173_SEQ must be positive.
    table["L2"] = "III"  # Numeric tracks only.
    target = BytesIO()
    workbook.save(target)
    report = parse_base(target.getvalue(), date(2025, 5, 25), "rebase")
    assert any(i["cell"] == "M2" and i["severity"] == "error" for i in report["issues"])
    table["M2"] = 1
    target = BytesIO()
    workbook.save(target)
    report = parse_base(target.getvalue(), date(2025, 5, 25), "rebase")
    assert any(i["cell"] == "L2" and i["severity"] == "error" for i in report["issues"])
    table["L2"] = None
    table["K2"] = datetime(2025, 5, 25, 7, 4)
    target = BytesIO()
    workbook.save(target)
    workbook.close()
    report = parse_base(target.getvalue(), date(2025, 5, 25), "rebase")
    assert any("混合" in i["message"] and i["severity"] == "error" for i in report["issues"])
    from app.ingest.base_parser import event_time

    value = event_time(
        datetime(2025, 5, 26, 1, 0), date(2025, 5, 25), date(2025, 5, 25), "preserve"
    )
    assert value == {"hms": "01:00:00", "seconds": 90000, "day_offset": 1}
