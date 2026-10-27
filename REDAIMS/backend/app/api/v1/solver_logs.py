from hashlib import sha256
from pathlib import PurePosixPath
from typing import Literal
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

MAX_LOG_BYTES = 32 * 1024 * 1024


class SolverLog(BaseModel):
    id: str
    run_id: str
    filename: str
    size_bytes: int
    digest: str
    created_at: str


def router(database):
    api = APIRouter(prefix="/api/v1/runs", tags=["solver-logs"])

    def check_run(connection, run_id):
        exists = connection.execute(
            "SELECT 1 FROM runs WHERE id=? AND id NOT IN "
            "(SELECT run_id FROM base_run_data WHERE role='base')",
            [run_id],
        ).fetchone()
        if not exists:
            raise HTTPException(404, "run 不存在")

    def info(row):
        return dict(
            zip(
                ("id", "run_id", "filename", "size_bytes", "digest", "created_at"),
                (*row[:5], row[5].isoformat()),
                strict=True,
            )
        )

    @api.get("/{run_id}/solver-logs", response_model=list[SolverLog])
    def list_logs(run_id: str):
        with database.transaction() as connection:
            check_run(connection, run_id)
            return [
                info(row)
                for row in connection.execute(
                    "SELECT id,run_id,filename,size_bytes,digest,created_at "
                    "FROM run_solver_logs WHERE run_id=? ORDER BY created_at DESC,id",
                    [run_id],
                ).fetchall()
            ]

    def save_log(run_id, filename, content):
        with database.transaction() as connection:
            check_run(connection, run_id)
            digest = sha256(content).hexdigest()
            # A retried upload of the same named file returns its existing attachment.
            previous = connection.execute(
                "SELECT id,run_id,filename,size_bytes,digest,created_at FROM run_solver_logs "
                "WHERE run_id=? AND filename=? AND digest=?",
                [run_id, filename, digest],
            ).fetchone()
            if previous:
                return info(previous)
            log_id = str(uuid4())
            row = connection.execute(
                "INSERT INTO run_solver_logs (id,run_id,filename,size_bytes,digest,content) "
                "VALUES (?,?,?,?,?,?) "
                "RETURNING id,run_id,filename,size_bytes,digest,created_at",
                [log_id, run_id, filename, len(content), digest, content],
            ).fetchone()
            return info(row)

    @api.post(
        "/{run_id}/solver-logs",
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

    @api.get("/{run_id}/solver-logs/{log_id}/text")
    def read_text(run_id: str, log_id: str, encoding: Literal["utf-8", "gb18030"] = "utf-8"):
        with database.transaction() as connection:
            check_run(connection, run_id)
            row = connection.execute(
                "SELECT filename,content,digest FROM run_solver_logs WHERE run_id=? AND id=?",
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
        }

    @api.get("/{run_id}/solver-logs/{log_id}/download")
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

    return api
