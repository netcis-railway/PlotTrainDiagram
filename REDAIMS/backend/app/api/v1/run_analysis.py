"""Persist the three-section run analysis workspace independently of source edits."""

import json
from typing import Literal
from uuid import uuid4

import duckdb
from app.api.v1.diagram_views import CreateDiagramView, Viewport, validate_snapshot
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

MAX_ANALYSIS_BYTES = 32 * 1024 * 1024
Section = Literal["diagram", "log", "delay"]
NodeType = Literal["view", "solver-log", "delay"]


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


class AnalysisState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    expanded_sections: list[Section] = Field(default_factory=lambda: ["diagram"], max_length=3)
    diagram: CreateDiagramView | None = None
    log: LogDisplay = Field(default_factory=LogDisplay)
    delay: DelaySection | None = None


class CreateAnalysisNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_type: NodeType
    name: str = Field(min_length=1, max_length=200)
    state: AnalysisState

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("请输入分析节点名称")
        return value.strip()


class AnalysisNodeSummary(BaseModel):
    id: str
    run_id: str
    node_type: NodeType
    name: str
    created_at: str


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
                ("id", "run_id", "node_type", "name", "created_at"),
                (*row[:4], row[4].isoformat()),
                strict=True,
            )
        )

    @api.get("/analysis/nodes", response_model=list[AnalysisNodeSummary])
    def all_nodes():
        with database.transaction() as c:
            return [
                summary(row)
                for row in c.execute(
                    "SELECT v.id,v.run_id,v.node_type,v.name,v.created_at "
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
                raise ValueError("请先展开延误分析并读取数据")
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
                    "INSERT INTO run_analysis_nodes (id,run_id,node_type,name,state) "
                    "VALUES (?,?,?,?,?) RETURNING id,run_id,node_type,name,created_at",
                    [str(uuid4()), run_id, payload.node_type, payload.name, encoded],
                ).fetchone()
                return summary(row)
        except duckdb.ConstraintException as error:
            raise HTTPException(409, "该run下已有同类型同名节点，请使用其他名称") from error

    @api.get("/runs/{run_id}/analysis-nodes/{node_id}", response_model=SavedAnalysisNode)
    def read_node(run_id: str, node_id: str):
        with database.transaction() as c:
            check_run(c, run_id)
            row = c.execute(
                "SELECT id,run_id,node_type,name,created_at,state FROM run_analysis_nodes "
                "WHERE run_id=? AND id=?",
                [run_id, node_id],
            ).fetchone()
            if not row:
                raise HTTPException(404, "分析节点不存在")
            return summary(row) | {"state": json.loads(row[5])}

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
