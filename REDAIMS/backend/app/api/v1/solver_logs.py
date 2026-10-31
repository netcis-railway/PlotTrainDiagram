import json
import math
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Literal
from urllib.parse import quote
from uuid import uuid4

from app.api.v1.run_metadata import SectionNotes, SectionNoteUpdate
from app.solver_visualizers.configuration import ConfigurationError, identify, read_configuration
from app.solver_visualizers.rendering import render_plot
from app.solver_visualizers.results import extract_results
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator
from starlette.concurrency import run_in_threadpool

MAX_LOG_BYTES = 32 * 1024 * 1024


class SolverLog(BaseModel):
    id: str
    run_id: str
    filename: str
    size_bytes: int
    digest: str
    created_at: str
    solver_type: str = "unknown"
    default_plotter: str | None = None
    detection: dict[str, JsonValue] = Field(default_factory=dict)
    section_notes: SectionNotes = Field(default_factory=dict)
    best_objective: float | None = None
    solve_seconds: float | None = None
    objective_source: Literal["solver-log", "manual", "unavailable"] = "unavailable"
    time_source: Literal["solver-log", "manual", "unavailable"] = "unavailable"
    result_extraction: dict[str, JsonValue] = Field(default_factory=dict)
    result_warnings: list[str] = Field(default_factory=list)


class SolverResultUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    best_objective: float | None = Field(default=None, allow_inf_nan=False, strict=True)
    solve_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False, strict=True)

    @field_validator("best_objective", "solve_seconds", mode="before")
    @classmethod
    def finite_input(cls, value):
        if isinstance(value, float) and not math.isfinite(value):
            # Keep non-finite JSON values out of validation-error response serialization too.
            raise HTTPException(422, "目标值和求解时间必须是有限数值")
        return value

    @model_validator(mode="after")
    def require_field(self):
        if not self.model_fields_set:
            raise ValueError("请填写目标函数最优值或求解时间")
        return self


class ClassificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    solver_type: str = Field(default="auto", max_length=64)


class VisualizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    encoding: Literal["utf-8", "gb18030"] = "utf-8"
    plotter_id: str | None = Field(default=None, max_length=64)
    options: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("options")
    @classmethod
    def limit_options(cls, value):
        if len(json.dumps(value)) > 20000:
            raise ValueError("作图配置过大")
        return value


def router(database, config_path=None):
    api = APIRouter(prefix="/api/v1", tags=["solver-logs"])
    columns = (
        "id,run_id,filename,size_bytes,digest,created_at,solver_type,default_plotter,"
        "detection,section_notes,best_objective,solve_seconds,objective_source,time_source,"
        "result_extraction"
    )

    def configuration():
        try:
            return read_configuration(config_path)
        except ConfigurationError as error:
            raise HTTPException(503, str(error)) from error

    @api.get("/solver-logs/config")
    def config():
        value, digest = configuration()
        return {**value.public(), "revision": digest}

    def check_run(connection, run_id):
        exists = connection.execute(
            "SELECT 1 FROM runs WHERE id=? AND id NOT IN "
            "(SELECT run_id FROM base_run_data WHERE role='base')",
            [run_id],
        ).fetchone()
        if not exists:
            raise HTTPException(404, "run 不存在")

    def info(row):
        warnings = []
        for value, source, label in (
            (row[10], row[12], "目标函数最优值"),
            (row[11], row[13], "求解时间"),
        ):
            if value is None:
                warnings.append(
                    f"未能从日志中获取{label}，请人工填写。"
                    if source != "manual"
                    else f"{label}尚未填写。"
                )
        return {
            **dict(
                zip(
                    ("id", "run_id", "filename", "size_bytes", "digest", "created_at"),
                    (*row[:5], row[5].isoformat()),
                    strict=True,
                )
            ),
            "solver_type": row[6] or "unknown",
            "default_plotter": row[7],
            "detection": json.loads(row[8] or "{}"),
            "section_notes": json.loads(row[9] or "{}"),
            "best_objective": row[10],
            "solve_seconds": row[11],
            "objective_source": row[12] or "unavailable",
            "time_source": row[13] or "unavailable",
            "result_extraction": json.loads(row[14] or "{}"),
            "result_warnings": warnings,
        }

    @api.get("/runs/{run_id}/solver-logs", response_model=list[SolverLog])
    def list_logs(run_id: str):
        with database.transaction() as connection:
            check_run(connection, run_id)
            return [
                info(row)
                for row in connection.execute(
                    f"SELECT {columns} FROM run_solver_logs WHERE run_id=? "
                    "ORDER BY created_at DESC,id",
                    [run_id],
                ).fetchall()
            ]

    def save_log(run_id, filename, content):
        value, revision = configuration()
        classified = identify(content, value, revision)
        result = extract_results(content, classified["detection"]["encoding"])
        with database.transaction() as connection:
            check_run(connection, run_id)
            digest = sha256(content).hexdigest()
            # A retried upload of the same named file returns its existing attachment.
            previous = connection.execute(
                f"SELECT {columns} FROM run_solver_logs WHERE run_id=? AND filename=? AND digest=?",
                [run_id, filename, digest],
            ).fetchone()
            if previous:
                # Re-import upgrades older attachments once, retaining manual values.
                if not json.loads(previous[14] or "{}"):
                    best = previous[10] if previous[12] == "manual" else result["best_objective"]
                    seconds = previous[11] if previous[13] == "manual" else result["solve_seconds"]
                    objective_source = (
                        "manual" if previous[12] == "manual" else result["objective_source"]
                    )
                    time_source = "manual" if previous[13] == "manual" else result["time_source"]
                    previous = connection.execute(
                        "UPDATE run_solver_logs SET best_objective=?,solve_seconds=?,"
                        f"objective_source=?,time_source=?,result_extraction=? WHERE id=? "
                        f"RETURNING {columns}",
                        [
                            best,
                            seconds,
                            objective_source,
                            time_source,
                            json.dumps(result["result_extraction"]),
                            previous[0],
                        ],
                    ).fetchone()
                return info(previous)
            log_id = str(uuid4())
            row = connection.execute(
                "INSERT INTO run_solver_logs (id,run_id,filename,size_bytes,digest,content,"
                "solver_type,default_plotter,detection,best_objective,solve_seconds,"
                "objective_source,time_source,result_extraction) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                f"RETURNING {columns}",
                [
                    log_id,
                    run_id,
                    filename,
                    len(content),
                    digest,
                    content,
                    classified["solver_type"],
                    classified["default_plotter"],
                    json.dumps(classified["detection"]),
                    result["best_objective"],
                    result["solve_seconds"],
                    result["objective_source"],
                    result["time_source"],
                    json.dumps(result["result_extraction"]),
                ],
            ).fetchone()
            return info(row)

    @api.post(
        "/runs/{run_id}/solver-logs",
        status_code=201,
        response_model=SolverLog,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
                },
            }
        },
    )
    async def upload_log(
        run_id: str, request: Request, filename: str = Query(min_length=1, max_length=255)
    ):
        filename = PurePosixPath(filename.replace("\\", "/")).name.strip()
        if not filename or filename in {".", ".."} or any(ord(char) < 32 for char in filename):
            raise HTTPException(422, "日志文件名无效")
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > MAX_LOG_BYTES:
                raise HTTPException(413, "日志文件超过 32 MB 限制")
        if not content:
            raise HTTPException(422, "日志文件不能为空")
        return await run_in_threadpool(save_log, run_id, filename, bytes(content))

    @api.get("/runs/{run_id}/solver-logs/{log_id}", response_model=SolverLog)
    def metadata(run_id: str, log_id: str):
        with database.transaction() as c:
            check_run(c, run_id)
            row = c.execute(
                f"SELECT {columns} FROM run_solver_logs WHERE run_id=? AND id=?", [run_id, log_id]
            ).fetchone()
            if not row:
                raise HTTPException(404, "求解日志不存在")
            return info(row)

    @api.patch("/runs/{run_id}/solver-logs/{log_id}", response_model=SolverLog)
    def update_results(run_id: str, log_id: str, payload: SolverResultUpdate):
        with database.transaction() as c:
            check_run(c, run_id)
            assignments, values = [], []
            for field, source in (
                ("best_objective", "objective_source"),
                ("solve_seconds", "time_source"),
            ):
                if field in payload.model_fields_set:
                    assignments.extend([f"{field}=?", f"{source}='manual'"])
                    values.append(getattr(payload, field))
            row = c.execute(
                f"UPDATE run_solver_logs SET {','.join(assignments)} WHERE run_id=? AND id=? "
                f"RETURNING {columns}",
                [*values, run_id, log_id],
            ).fetchone()
            if not row:
                raise HTTPException(404, "求解日志不存在")
            return info(row)

    @api.get("/runs/{run_id}/solver-logs/{log_id}/text")
    def read_text(run_id: str, log_id: str, encoding: Literal["utf-8", "gb18030"] = "utf-8"):
        with database.transaction() as connection:
            check_run(connection, run_id)
            row = connection.execute(
                "SELECT filename,content,digest,solver_type,default_plotter,detection "
                "FROM run_solver_logs WHERE run_id=? AND id=?",
                [run_id, log_id],
            ).fetchone()
            if not row:
                raise HTTPException(404, "求解日志不存在")
        try:
            text = bytes(row[1]).decode("utf-8-sig" if encoding == "utf-8" else encoding)
        except UnicodeDecodeError as error:
            raise HTTPException(422, "日志不能按所选编码读取，请切换UTF-8或GB18030") from error
        return {
            "id": log_id,
            "filename": row[0],
            "digest": row[2],
            "encoding": encoding,
            "text": text,
            "solver_type": row[3] or "unknown",
            "default_plotter": row[4],
            "detection": json.loads(row[5] or "{}"),
        }

    @api.get("/runs/{run_id}/solver-logs/{log_id}/download")
    def download_log(run_id: str, log_id: str):
        with database.transaction() as connection:
            check_run(connection, run_id)
            row = connection.execute(
                "SELECT filename,content FROM run_solver_logs WHERE run_id=? AND id=?",
                [run_id, log_id],
            ).fetchone()
            if not row:
                raise HTTPException(404, "求解日志不存在")
        return Response(
            content=bytes(row[1]),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(row[0], safe='')}",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @api.post("/runs/{run_id}/solver-logs/{log_id}/classify", response_model=SolverLog)
    def classify(run_id: str, log_id: str, payload: ClassificationRequest):
        value, revision = configuration()
        with database.transaction() as connection:
            check_run(connection, run_id)
            row = connection.execute(
                "SELECT content FROM run_solver_logs WHERE run_id=? AND id=?", [run_id, log_id]
            ).fetchone()
            if row is None:
                raise HTTPException(404, "求解日志不存在")
            try:
                classified = identify(bytes(row[0]), value, revision, payload.solver_type)
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
            saved = connection.execute(
                "UPDATE run_solver_logs SET solver_type=?,default_plotter=?,detection=? "
                f"WHERE run_id=? AND id=? RETURNING {columns}",
                [
                    classified["solver_type"],
                    classified["default_plotter"],
                    json.dumps(classified["detection"]),
                    run_id,
                    log_id,
                ],
            ).fetchone()
            return info(saved)

    @api.post("/runs/{run_id}/solver-logs/{log_id}/visualization")
    def visualization(run_id: str, log_id: str, payload: VisualizationRequest):
        with database.transaction() as connection:
            check_run(connection, run_id)
            row = connection.execute(
                "SELECT filename,content,solver_type,default_plotter "
                "FROM run_solver_logs WHERE run_id=? AND id=?",
                [run_id, log_id],
            ).fetchone()
            if row is None:
                raise HTTPException(404, "求解日志不存在")
        value, _ = configuration()
        plotter_id = payload.plotter_id or row[3]
        plotter = next((p for p in value.plotters if p.id == plotter_id), None)
        if plotter is None or plotter.solver_type != row[2]:
            raise HTTPException(422, "当前求解器没有匹配的作图函数，请先识别或设置求解器类型")
        try:
            return {
                **render_plot(bytes(row[1]), row[0], payload.encoding, plotter, payload.options),
                "solver_type": row[2],
            }
        except ConfigurationError as error:
            raise HTTPException(503, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @api.patch("/runs/{run_id}/solver-logs/{log_id}/section-notes", response_model=SolverLog)
    def update_section_notes(run_id: str, log_id: str, payload: SectionNoteUpdate):
        with database.transaction() as c:
            check_run(c, run_id)
            current = c.execute(
                "SELECT section_notes FROM run_solver_logs WHERE run_id=? AND id=?",
                [run_id, log_id],
            ).fetchone()
            if not current:
                raise HTTPException(404, "求解日志不存在")
            notes = json.loads(current[0] or "{}") | {payload.section: payload.notes}
            row = c.execute(
                "UPDATE run_solver_logs SET section_notes=? WHERE run_id=? AND id=? "
                f"RETURNING {columns}",
                [json.dumps(notes, ensure_ascii=False), run_id, log_id],
            ).fetchone()
            return info(row)

    @api.delete("/runs/{run_id}/solver-logs/{log_id}")
    def delete_log(run_id: str, log_id: str):
        with database.transaction() as connection:
            check_run(connection, run_id)
            if not connection.execute(
                "SELECT 1 FROM run_solver_logs WHERE run_id=? AND id=?", [run_id, log_id]
            ).fetchone():
                raise HTTPException(404, "求解日志不存在")
            references = connection.execute(
                "SELECT name FROM run_analysis_nodes WHERE run_id=? "
                "AND json_extract_string(state, '$.log.log_id')=? ORDER BY created_at,id",
                [run_id, log_id],
            ).fetchall()
            if references:
                names = "、".join(f"“{row[0]}”" for row in references[:5])
                if len(references) > 5:
                    names += "等"
                raise HTTPException(
                    409,
                    f"该日志仍被{len(references)}个已保存分析节点引用（{names}），"
                    "请先删除这些分析节点，再删除日志文件。",
                )
            connection.execute(
                "DELETE FROM run_solver_logs WHERE run_id=? AND id=?", [run_id, log_id]
            )
            return {"deleted_log_id": log_id}

    return api
