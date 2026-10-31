"""Persist the three-section run analysis workspace independently of source edits."""

import json
from typing import Literal
from uuid import uuid4

import duckdb
from app.api.v1.diagram_views import CreateDiagramView, Viewport, validate_snapshot
from app.api.v1.run_metadata import SectionNotes, SectionNoteUpdate
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

MAX_ANALYSIS_BYTES = 32 * 1024 * 1024
Section = Literal["diagram", "log", "delay"]
NodeType = Literal["view", "solver-log", "delay", "metrics"]


class LogDisplay(BaseModel):
    model_config = ConfigDict(extra="forbid")
    log_id: str = ""
    encoding: Literal["utf-8", "gb18030"] = "utf-8"
    search: str = Field(default="", max_length=1000)
    wrap: bool = True
    scroll_top: float = Field(default=0, ge=0, allow_inf_nan=False)
    scroll_left: float = Field(default=0, ge=0, allow_inf_nan=False)
    visualization_state: dict[str, JsonValue] = Field(default_factory=dict)


class DelayDisplay(BaseModel):
    model_config = ConfigDict(extra="forbid")
    station_ids: list[str] = Field(max_length=10000)
    train_ids: list[str] = Field(max_length=20000)
    highlighted_ids: list[str] = Field(max_length=20000)
    unit: Literal["seconds", "minutes"]
    chart_height: int = Field(ge=200, le=1000)
    scroll_top: float = Field(ge=0, allow_inf_nan=False)
    scroll_left: float = Field(ge=0, allow_inf_nan=False)
    viewport: Viewport
    station_search: str = Field(default="", max_length=1000)
    train_search: str = Field(default="", max_length=1000)
    open_panels: list[Literal["stations", "trains", "issues"]] = Field(
        default_factory=list, max_length=3
    )


class DelaySection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: DelayDisplay
    snapshot: dict[str, JsonValue]


Metric = Literal[
    "total",
    "mean",
    "max",
    "p95",
    "late_rate",
    "affected",
    "terminal_total",
    "terminal_mean",
    "terminal_rate",
    "terminal_affected",
]


class MetricCamera(BaseModel):
    model_config = ConfigDict(extra="forbid")
    azimuth: float = Field(default=-40, ge=-180, le=180, allow_inf_nan=False)
    elevation: float = Field(default=28, ge=10, le=80, allow_inf_nan=False)
    zoom: float = Field(default=1, ge=0.6, le=2.5, allow_inf_nan=False)


class MetricTimeHeatmap(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interval_minutes: Literal[1, 10, 60] = 10
    fields: list[Literal["arrival", "departure"]] = Field(
        default_factory=lambda: ["arrival", "departure"], max_length=2
    )

    @field_validator("fields")
    @classmethod
    def unique_fields(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("时空热力图事件不能重复")
        return value


class MetricDisplay(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selected: list[Metric] = Field(min_length=2, max_length=6)
    event: Literal["arrival", "departure"] = "arrival"
    include_zero_arrivals: bool = True
    include_zero_departures: bool = True
    curve_train_ids: list[str] | None = Field(default=None, max_length=20000)
    curve_station_ids: list[str] | None = Field(default=None, max_length=10000)
    curve_mode: Literal["2d", "3d"] = "2d"
    curve_fields: list[Literal["arrival", "departure"]] = Field(
        default_factory=lambda: ["arrival", "departure"], max_length=2
    )
    curve_camera: MetricCamera = Field(default_factory=MetricCamera)
    time_heatmap: MetricTimeHeatmap = Field(default_factory=MetricTimeHeatmap)
    unit: Literal["seconds", "minutes"] = "minutes"
    threshold_seconds: float = Field(default=0, ge=0, le=86400, allow_inf_nan=False)
    scope: Literal["all", "selected"] = "all"
    station_ids: list[str] = Field(default_factory=list, max_length=10000)
    train_ids: list[str] = Field(default_factory=list, max_length=20000)
    active_train_id: str = ""
    row_offset: int = Field(default=0, ge=0)
    train_offset: int = Field(default=0, ge=0)


class MetricSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: MetricDisplay
    snapshot: dict[str, JsonValue]


class AnalysisState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    expanded_sections: list[Section] = Field(default_factory=lambda: ["diagram"], max_length=3)
    diagram: CreateDiagramView | None = None
    log: LogDisplay = Field(default_factory=LogDisplay)
    delay: DelaySection | None = None
    metrics: MetricSection | None = None
    active_view: Literal["workspace", "metrics"] = "workspace"


class AnalysisMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    notes: str = Field(default="", max_length=20000)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("请输入分析节点名称")
        return value.strip()


class CreateAnalysisNode(AnalysisMetadata):
    node_type: NodeType
    state: AnalysisState
    section_notes: SectionNotes = Field(default_factory=dict)


class AnalysisNodeSummary(BaseModel):
    id: str
    run_id: str
    node_type: NodeType
    name: str
    created_at: str
    notes: str = ""
    section_notes: SectionNotes = Field(default_factory=dict)


class SavedAnalysisNode(AnalysisNodeSummary):
    state: AnalysisState


def router(database):
    api = APIRouter(prefix="/api/v1", tags=["run-analysis"])

    def check_run(c, run_id):
        if not c.execute(
            "SELECT 1 FROM runs WHERE id=? AND id NOT IN "
            "(SELECT run_id FROM base_run_data WHERE role='base')",
            [run_id],
        ).fetchone():
            raise HTTPException(404, "run 不存在")

    def summary(row):
        return dict(
            zip(
                ("id", "run_id", "node_type", "name", "created_at", "notes", "section_notes"),
                (*row[:4], row[4].isoformat(), row[5] or "", json.loads(row[6] or "{}")),
                strict=True,
            )
        )

    @api.get("/analysis/nodes", response_model=list[AnalysisNodeSummary])
    def all_nodes():
        with database.transaction() as c:
            return [
                summary(row)
                for row in c.execute(
                    "SELECT v.id,v.run_id,v.node_type,v.name,v.created_at,v.notes,v.section_notes "
                    "FROM run_analysis_nodes v "
                    "JOIN runs r ON r.id=v.run_id WHERE r.id NOT IN "
                    "(SELECT run_id FROM base_run_data WHERE role='base') "
                    "ORDER BY v.created_at,v.id"
                ).fetchall()
            ]

    @api.post("/runs/{run_id}/analysis-nodes", status_code=201, response_model=AnalysisNodeSummary)
    def save_node(run_id: str, payload: CreateAnalysisNode):
        state = payload.state
        try:
            if state.diagram:
                validate_snapshot(run_id, state.diagram)
            if payload.node_type == "view" and not state.diagram:
                raise ValueError("请先展开运行图分析并读取可绘制的运行图")
            if payload.node_type == "solver-log" and not state.log.log_id:
                raise ValueError("请先选择求解日志")
            if payload.node_type == "delay" and not state.delay:
                raise ValueError("请先展开延误预览并读取数据")
            if payload.node_type == "metrics":
                if not state.metrics:
                    raise ValueError("请先进入指标分析并读取数据")
                state.active_view = "metrics"
            if state.delay:
                delay = state.delay
                snapshot = delay.snapshot
                if snapshot["object"]["id"] != run_id or not snapshot.get("base"):
                    raise ValueError("延误快照与当前run不一致或缺少基本图")
                stations = {s["id"] for s in snapshot["stations"]}
                trains = {t["id"] for t in snapshot["trains"]}
                if not set(delay.state.station_ids) <= stations:
                    raise ValueError("延误分析包含未知车站")
                if not isinstance(snapshot["rows"], list) or not isinstance(
                    snapshot["cells"], list
                ):
                    raise ValueError("延误数据快照格式无效")
                for field in ("train_ids", "highlighted_ids"):
                    if not set(getattr(delay.state, field)) <= trains:
                        raise ValueError("延误分析包含未知列车")
            if state.metrics:
                metric = state.metrics
                snapshot = metric.snapshot
                if snapshot["object"]["id"] != run_id or not snapshot.get("base"):
                    raise ValueError("指标快照与当前run不一致或缺少基本图")
                stations = {s["id"] for s in snapshot["stations"]}
                trains = {t["id"] for t in snapshot["trains"]}
                if not isinstance(snapshot["cells"], list) or not isinstance(
                    snapshot["rows"], list
                ):
                    raise ValueError("指标数据快照格式无效")
                if (
                    not set(metric.state.station_ids) <= stations
                    or not set(metric.state.train_ids) <= trains
                ):
                    raise ValueError("指标分析包含未知车站或列车")
                if metric.state.active_train_id and metric.state.active_train_id not in trains:
                    raise ValueError("指标分析包含未知高亮列车")
                if metric.state.curve_train_ids is not None:
                    if not set(metric.state.curve_train_ids) <= trains:
                        raise ValueError("偏差曲线包含未知列车")
                    if len(set(metric.state.curve_train_ids)) != len(metric.state.curve_train_ids):
                        raise ValueError("偏差曲线列车不能重复")
                if metric.state.curve_station_ids is not None:
                    if not set(metric.state.curve_station_ids) <= stations:
                        raise ValueError("偏差曲线包含未知车站")
                    if len(set(metric.state.curve_station_ids)) != len(
                        metric.state.curve_station_ids
                    ):
                        raise ValueError("偏差曲线车站不能重复")
                if len(set(metric.state.curve_fields)) != len(metric.state.curve_fields):
                    raise ValueError("偏差曲线观测事件不能重复")
                if len(set(metric.state.selected)) != len(metric.state.selected):
                    raise ValueError("指标不能重复选择")
            encoded = json.dumps(state.model_dump(), ensure_ascii=False, allow_nan=False)
        except (ValueError, KeyError, TypeError) as error:
            raise HTTPException(422, str(error)) from error
        if len(encoded.encode("utf-8")) > MAX_ANALYSIS_BYTES:
            raise HTTPException(413, "分析快照超过32 MB，请减少运行图列车选择后重试")
        try:
            with database.transaction() as c:
                check_run(c, run_id)
                if (
                    state.log.log_id
                    and not c.execute(
                        "SELECT 1 FROM run_solver_logs WHERE run_id=? AND id=?",
                        [run_id, state.log.log_id],
                    ).fetchone()
                ):
                    raise HTTPException(422, "求解日志不属于当前run")
                row = c.execute(
                    "INSERT INTO run_analysis_nodes "
                    "(id,run_id,node_type,name,state,notes,section_notes) "
                    "VALUES (?,?,?,?,?,?,?) RETURNING "
                    "id,run_id,node_type,name,created_at,notes,section_notes",
                    [
                        str(uuid4()),
                        run_id,
                        payload.node_type,
                        payload.name,
                        encoded,
                        payload.notes,
                        json.dumps(payload.section_notes, ensure_ascii=False),
                    ],
                ).fetchone()
                return summary(row)
        except duckdb.ConstraintException as error:
            raise HTTPException(409, "该run下已有同类型同名节点，请使用其他名称") from error

    @api.get("/runs/{run_id}/analysis-nodes/{node_id}", response_model=SavedAnalysisNode)
    def read_node(run_id: str, node_id: str):
        with database.transaction() as c:
            check_run(c, run_id)
            row = c.execute(
                "SELECT id,run_id,node_type,name,created_at,notes,section_notes,state FROM "
                "run_analysis_nodes "
                "WHERE run_id=? AND id=?",
                [run_id, node_id],
            ).fetchone()
            if not row:
                raise HTTPException(404, "分析节点不存在")
            return summary(row) | {"state": json.loads(row[7])}

    @api.patch("/runs/{run_id}/analysis-nodes/{node_id}", response_model=AnalysisNodeSummary)
    def update_node(run_id: str, node_id: str, payload: AnalysisMetadata):
        try:
            with database.transaction() as c:
                check_run(c, run_id)
                row = c.execute(
                    "UPDATE run_analysis_nodes SET name=?,notes=? WHERE run_id=? AND id=? "
                    "RETURNING id,run_id,node_type,name,created_at,notes,section_notes",
                    [payload.name, payload.notes, run_id, node_id],
                ).fetchone()
                if not row:
                    raise HTTPException(404, "分析节点不存在")
                return summary(row)
        except duckdb.ConstraintException as error:
            raise HTTPException(409, "该run下已有同类型同名节点，请使用其他名称") from error

    @api.patch(
        "/runs/{run_id}/analysis-nodes/{node_id}/section-notes", response_model=AnalysisNodeSummary
    )
    def update_section_notes(run_id: str, node_id: str, payload: SectionNoteUpdate):
        with database.transaction() as c:
            check_run(c, run_id)
            current = c.execute(
                "SELECT section_notes FROM run_analysis_nodes WHERE run_id=? AND id=?",
                [run_id, node_id],
            ).fetchone()
            if not current:
                raise HTTPException(404, "分析节点不存在")
            notes = json.loads(current[0] or "{}") | {payload.section: payload.notes}
            row = c.execute(
                "UPDATE run_analysis_nodes SET section_notes=? WHERE run_id=? AND id=? "
                "RETURNING id,run_id,node_type,name,created_at,notes,section_notes",
                [json.dumps(notes, ensure_ascii=False), run_id, node_id],
            ).fetchone()
            return summary(row)

    @api.delete("/runs/{run_id}/analysis-nodes/{node_id}")
    def delete_node(run_id: str, node_id: str):
        with database.transaction() as c:
            check_run(c, run_id)
            row = c.execute(
                "DELETE FROM run_analysis_nodes WHERE run_id=? AND id=? RETURNING id",
                [run_id, node_id],
            ).fetchone()
            if not row:
                raise HTTPException(404, "分析节点不存在")
            return {"deleted_node_id": row[0]}

    @api.get("/analysis/logs")
    def all_logs():
        with database.transaction() as c:
            return [
                {"id": row[0], "run_id": row[1], "filename": row[2]}
                for row in c.execute(
                    "SELECT l.id,l.run_id,l.filename FROM run_solver_logs l "
                    "JOIN runs r ON r.id=l.run_id WHERE r.id NOT IN "
                    "(SELECT run_id FROM base_run_data WHERE role='base') "
                    "ORDER BY l.created_at,l.id"
                ).fetchall()
            ]

    return api
