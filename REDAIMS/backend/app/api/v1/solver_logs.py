import json
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Literal
from urllib.parse import quote
from uuid import uuid4

from app.solver_visualizers.configuration import ConfigurationError, identify, read_configuration
from app.solver_visualizers.rendering import render_plot
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator
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
        "id,run_id,filename,size_bytes,digest,created_at,solver_type,default_plotter,detection"
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
        with database.transaction() as connection:
            check_run(connection, run_id)
            digest = sha256(content).hexdigest()
            # A retried upload of the same named file returns its existing attachment.
            previous = connection.execute(
                f"SELECT {columns} FROM run_solver_logs WHERE run_id=? AND filename=? AND digest=?",
                [run_id, filename, digest],
            ).fetchone()
            if previous:
                return info(previous)
            log_id = str(uuid4())
            row = connection.execute(
                "INSERT INTO run_solver_logs (id,run_id,filename,size_bytes,digest,content,"
                "solver_type,default_plotter,detection) VALUES (?,?,?,?,?,?,?,?,?) "
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

    return api
