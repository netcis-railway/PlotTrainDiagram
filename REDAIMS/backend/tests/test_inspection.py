from io import BytesIO

import pytest
from app.ingest.inspection import HEADERS, inspect_workbook
from openpyxl import Workbook


def workbook_bytes(headers, title="TTT1base"):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title
    sheet.append(headers)
    sheet.append(["北京南", 1, "BJN", 1, "BeijingNan", None, "07:04:00", None, 1])
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def test_structure_and_manual_selection():
    content = workbook_bytes(HEADERS + ["G1_A", "G1_D", "G1_G", "G1_SEQ"], "自选")
    assert inspect_workbook(content)["requires_sheet_selection"]
    result = inspect_workbook(content, "自选")
    assert result["stage"] == "structure_only"
    assert result["sheets"][0]["trains"] == ["G1"]
    assert not result["sheets"][0]["issues"]
    with pytest.raises(ValueError, match="不存在"):
        inspect_workbook(content, "missing")


def test_invalid_groups_and_corrupt_file():
    content = workbook_bytes(HEADERS + ["G1_A", "G2_D", "G1_G", "G1_SEQ"])
    assert inspect_workbook(content)["sheets"][0]["issues"]
    with pytest.raises(ValueError, match="XLSX"):
        inspect_workbook(b"not an excel file")


def test_inspection_api(tmp_path):
    from app.core.config import Settings
    from app.main import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app(Settings(database=tmp_path / "test.duckdb"))) as client:
        assert client.post("/api/v1/ingest/inspect", content=b"invalid").status_code == 422
        content = workbook_bytes(HEADERS + ["G1_A", "G1_D", "G1_G", "G1_SEQ"])
        response = client.post("/api/v1/ingest/inspect", content=content)
        assert response.status_code == 200
        assert response.json()["sheets"][0]["trains"] == ["G1"]
        assert client.get("/api/v1/catalog").json() == []
