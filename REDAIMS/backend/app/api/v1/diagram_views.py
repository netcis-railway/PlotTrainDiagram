"""Named run diagram snapshots: display state is independent of timetable edits."""

import json
from typing import Literal
from uuid import uuid4

import duckdb
from app.api.v1.run_metadata import SectionNotes, SectionNoteUpdate
from fastapi import APIRouter, HTTPException
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    JsonValue,
    field_validator,
    model_validator,
)

MAX_VIEW_BYTES = 32 * 1024 * 1024


class Viewport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x0: FiniteFloat
    x1: FiniteFloat
    y0: FiniteFloat
    y1: FiniteFloat

    @model_validator(mode="after")
    def ordered(self):
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError("视图的时间及车站范围必须递增")
        return self


class TrainSourceDisplay(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    mode: Literal["all", "selected"] = "selected"


class DiagramDisplay(BaseModel):
    model_config = ConfigDict(extra="forbid")
    station_search: str = Field(default="", max_length=1000)
    train_search: str = Field(default="", max_length=1000)
    only_highlighted: bool = False
    train_sources: dict[str, TrainSourceDisplay] = Field(default_factory=dict, max_length=1000)
    open_panels: list[
        Literal["stations", "trains", "time", "tracks", "details-trains", "styles", "issues"]
    ] = Field(default_factory=list, max_length=7)


class ViewState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    line_ind: int = Field(ge=1)
    overlay_base: bool
    reverse: bool
    station_ids: list[str] = Field(min_length=1, max_length=10000)
    train_keys: list[str] = Field(max_length=20000)
    highlighted_keys: list[str] = Field(max_length=20000)
    expanded_station_ids: list[str] = Field(max_length=10000)
    track_station: str = ""
    viewport: Viewport
    from_time: str = Field(default="", max_length=40)
    to_time: str = Field(default="", max_length=40)
    detail_open: bool = False
    chart_height: int = Field(default=600, ge=340, le=4000)
    display: DiagramDisplay = Field(default_factory=DiagramDisplay)


class PlotSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    context: dict[str, JsonValue]
    data: dict[str, JsonValue]


class DiagramViewMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    notes: str = Field(default="", max_length=20000)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("请输入视图名称")
        return value


class CreateDiagramView(DiagramViewMetadata):
    state: ViewState
    snapshot: PlotSnapshot
    section_notes: SectionNotes = Field(default_factory=dict)


class DiagramViewSummary(BaseModel):
    id: str
    run_id: str
    name: str
    created_at: str
    line_ind: int
    station_count: int
    train_count: int
    highlight_count: int
    notes: str = ""
    section_notes: SectionNotes = Field(default_factory=dict)


class SavedDiagramView(DiagramViewSummary):
    state: ViewState
    snapshot: PlotSnapshot


def validate_snapshot(run_id, payload):
    context, data = payload.snapshot.context, payload.snapshot.data
    try:
        if (
            data["object"]["id"] != run_id
            or data["object"]["object_type"] != "run"
            or context["object"]["id"] != run_id
            or data["line_ind"] != payload.state.line_ind
            or not data["can_plot"]
        ):
            raise ValueError("视图与当前run或绘图线路不一致")
        stations = {station["node_id"] for station in data["axis"]["stations"]}
        keys = {series["key"] for series in data["series"]}
        if (
            not set(payload.state.station_ids) <= stations
            or not set(payload.state.expanded_station_ids) <= set(data["expanded_stations"])
            or not set(payload.state.train_keys) <= keys
            or not set(payload.state.highlighted_keys) <= keys
        ):
            raise ValueError("视图包含不属于当前绘图的车站或列车")
        base_id = data["base"]["id"] if data["base"] else None
        for series in data["series"]:
            if series["object_type"] == "run":
                if series["object_id"] != run_id:
                    raise ValueError("视图不能混入其他run的列车")
            elif series["object_type"] != "base" or series["object_id"] != base_id:
                raise ValueError("基本图列车须属于本次绘图绑定的基本图")
        # Required display collections must remain readable even after a server upgrade.
        for field in ("track_stations", "issues", "expanded_stations", "series"):
            if not isinstance(data[field], list):
                raise ValueError("绘图快照格式不完整")
        if not isinstance(data["styles"], dict) or not isinstance(context["lines"], list):
            raise ValueError("绘图快照格式不完整")
        if payload.state.overlay_base and not data["overlay_base"]:
            raise ValueError("当前快照没有叠加基本图数据")
    except (KeyError, TypeError) as error:
        raise ValueError("绘图快照格式不完整") from error


def router(database):
    api = APIRouter(prefix="/api/v1", tags=["diagram-views"])

    def check_run(connection, run_id):
        if not connection.execute(
            "SELECT 1 FROM runs WHERE id=? AND id NOT IN "
            "(SELECT run_id FROM base_run_data WHERE role='base')",
            [run_id],
        ).fetchone():
            raise HTTPException(404, "run 不存在")

    def summary(row):
        state = json.loads(row[4])
        return {
            "id": row[0],
            "run_id": row[1],
            "name": row[2],
            "created_at": row[3].isoformat(),
            "notes": row[5] or "",
            "section_notes": json.loads(row[6] or "{}"),
            "line_ind": state["line_ind"],
            "station_count": len(state["station_ids"]),
            "train_count": len(state["train_keys"]),
            "highlight_count": len(state["highlighted_keys"]),
        }

    @api.get("/diagram/views", response_model=list[DiagramViewSummary])
    def all_views():
        with database.transaction() as connection:
            return [
                summary(row)
                for row in connection.execute(
                    "SELECT v.id,v.run_id,v.name,v.created_at,v.state,v.notes,v.section_notes "
                    "FROM run_diagram_views v "
                    "JOIN runs r ON r.id=v.run_id WHERE r.id NOT IN "
                    "(SELECT run_id FROM base_run_data WHERE role='base') "
                    "ORDER BY v.created_at,v.id"
                ).fetchall()
            ]

    @api.get("/runs/{run_id}/diagram-views", response_model=list[DiagramViewSummary])
    def list_views(run_id: str):
        with database.transaction() as connection:
            check_run(connection, run_id)
            return [
                summary(row)
                for row in connection.execute(
                    "SELECT id,run_id,name,created_at,state,notes,section_notes FROM "
                    "run_diagram_views "
                    "WHERE run_id=? ORDER BY created_at,id",
                    [run_id],
                ).fetchall()
            ]

    @api.post("/runs/{run_id}/diagram-views", status_code=201, response_model=DiagramViewSummary)
    def save_view(run_id: str, payload: CreateDiagramView):
        try:
            validate_snapshot(run_id, payload)
            state = json.dumps(payload.state.model_dump(), ensure_ascii=False, allow_nan=False)
            snapshot = json.dumps(
                payload.snapshot.model_dump(), ensure_ascii=False, allow_nan=False
            )
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        if len(state.encode("utf-8")) + len(snapshot.encode("utf-8")) > MAX_VIEW_BYTES:
            raise HTTPException(413, "视图快照超过32 MB限制，请减少列车或车站后重试")
        try:
            with database.transaction() as connection:
                check_run(connection, run_id)
                row = connection.execute(
                    "INSERT INTO run_diagram_views "
                    "(id,run_id,name,state,snapshot,notes,section_notes) "
                    "VALUES (?,?,?,?,?,?,?) RETURNING "
                    "id,run_id,name,created_at,state,notes,section_notes",
                    [
                        str(uuid4()),
                        run_id,
                        payload.name,
                        state,
                        snapshot,
                        payload.notes,
                        json.dumps(payload.section_notes, ensure_ascii=False),
                    ],
                ).fetchone()
                return summary(row)
        except duckdb.ConstraintException as error:
            raise HTTPException(409, "此run下已有同名视图，请使用其他名称") from error

    @api.get("/runs/{run_id}/diagram-views/{view_id}", response_model=SavedDiagramView)
    def read_view(run_id: str, view_id: str):
        with database.transaction() as connection:
            check_run(connection, run_id)
            row = connection.execute(
                "SELECT id,run_id,name,created_at,state,notes,section_notes,snapshot FROM "
                "run_diagram_views "
                "WHERE run_id=? AND id=?",
                [run_id, view_id],
            ).fetchone()
            if not row:
                raise HTTPException(404, "保存的运行图视图不存在")
            return summary(row) | {"state": json.loads(row[4]), "snapshot": json.loads(row[7])}

    @api.patch("/runs/{run_id}/diagram-views/{view_id}", response_model=DiagramViewSummary)
    def update_view(run_id: str, view_id: str, payload: DiagramViewMetadata):
        try:
            with database.transaction() as connection:
                check_run(connection, run_id)
                row = connection.execute(
                    "UPDATE run_diagram_views SET name=?,notes=? WHERE run_id=? AND id=? "
                    "RETURNING id,run_id,name,created_at,state,notes,section_notes",
                    [payload.name, payload.notes, run_id, view_id],
                ).fetchone()
                if not row:
                    raise HTTPException(404, "保存的运行图视图不存在")
                return summary(row)
        except duckdb.ConstraintException as error:
            raise HTTPException(409, "此run下已有同名视图，请使用其他名称") from error

    @api.patch(
        "/runs/{run_id}/diagram-views/{view_id}/section-notes", response_model=DiagramViewSummary
    )
    def update_section_notes(run_id: str, view_id: str, payload: SectionNoteUpdate):
        with database.transaction() as c:
            check_run(c, run_id)
            current = c.execute(
                "SELECT section_notes FROM run_diagram_views WHERE run_id=? AND id=?",
                [run_id, view_id],
            ).fetchone()
            if not current:
                raise HTTPException(404, "保存的运行图视图不存在")
            notes = json.loads(current[0] or "{}") | {payload.section: payload.notes}
            row = c.execute(
                "UPDATE run_diagram_views SET section_notes=? WHERE run_id=? AND id=? "
                "RETURNING id,run_id,name,created_at,state,notes,section_notes",
                [json.dumps(notes, ensure_ascii=False), run_id, view_id],
            ).fetchone()
            return summary(row)

    @api.delete("/runs/{run_id}/diagram-views/{view_id}")
    def delete_view(run_id: str, view_id: str):
        with database.transaction() as connection:
            check_run(connection, run_id)
            row = connection.execute(
                "DELETE FROM run_diagram_views WHERE run_id=? AND id=? RETURNING id",
                [run_id, view_id],
            ).fetchone()
            if not row:
                raise HTTPException(404, "保存的运行图视图不存在")
            return {"deleted_view_id": row[0]}

    return api
