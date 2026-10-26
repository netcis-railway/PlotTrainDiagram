from datetime import date
from typing import Literal

from app.ingest.base_service import (
    BaseDelete,
    BaseImportService,
    BindingChange,
    CommitImport,
    ImportConflict,
    ImportOptions,
)
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool


def router(service: BaseImportService):
    api = APIRouter(prefix="/api/v1", tags=["base-import"])

    async def upload(request):
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > 32 * 1024 * 1024:
                raise HTTPException(413, "文件超过32 MB限制")
        return bytes(content)

    @api.post(
        "/ingest/base/preview",
        status_code=201,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {
                        "schema": {"type": "string", "format": "binary"}
                    }
                },
            }
        },
    )
    async def preview(
        request: Request,
        batch_id: str,
        name: str,
        filename: str,
        date_base: date = date(2026, 1, 1),
        date_mode: Literal["rebase", "preserve"] = "rebase",
        run_no: int | None = 0,
        auto_number: bool = False,
        sheet: str | None = None,
        write_mode: Literal["create", "replace"] = "create",
    ):
        try:
            options = ImportOptions(
                batch_id=batch_id,
                name=name,
                date_base=date_base,
                date_mode=date_mode,
                run_no=None if auto_number else run_no,
                sheet=sheet,
                write_mode=write_mode,
            )
            return await run_in_threadpool(
                service.preview, await upload(request), filename, options
            )
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except OSError as error:
            raise HTTPException(503, "暂存文件写入失败，请检查存储目录后重试") from error

    @api.get("/ingest/jobs")
    def jobs():
        return service.jobs()

    @api.get("/ingest/jobs/{job_id}")
    def job(job_id: str):
        try:
            return service.job(job_id)
        except LookupError as error:
            raise HTTPException(404, str(error)) from error

    @api.post("/ingest/jobs/{job_id}/commit")
    def commit(job_id: str, payload: CommitImport):
        try:
            return service.commit(job_id, payload)
        except LookupError as error:
            raise HTTPException(404, str(error)) from error
        except ImportConflict as error:
            raise HTTPException(409, str(error)) from error
        except (ValueError, FileNotFoundError) as error:
            raise HTTPException(422, str(error)) from error
        except OSError as error:
            raise HTTPException(503, "文件保存失败，未完成导入，请查看任务后重试") from error

    @api.delete("/ingest/jobs/{job_id}")
    def cancel(job_id: str):
        try:
            return service.cancel(job_id)
        except LookupError as error:
            raise HTTPException(404, str(error)) from error
        except (ImportConflict, ValueError) as error:
            raise HTTPException(409, str(error)) from error

    @api.get("/runs")
    def runs():
        return service.list_runs()

    @api.get("/catalog/base-bindings")
    def catalog_bindings():
        return service.catalog_bindings()

    @api.get("/runs/{run_id}")
    def run(run_id: str):
        try:
            return service.run(run_id)
        except LookupError as error:
            raise HTTPException(404, str(error)) from error

    @api.get("/runs/{run_id}/deletion-preview")
    def deletion_preview(run_id: str):
        try:
            return service.deletion_preview(run_id)
        except LookupError as error:
            raise HTTPException(404, str(error)) from error

    @api.delete("/runs/{run_id}")
    def delete_base(run_id: str, payload: BaseDelete):
        try:
            return service.delete_base(run_id, payload)
        except LookupError as error:
            raise HTTPException(404, str(error)) from error
        except ImportConflict as error:
            raise HTTPException(409, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @api.get("/runs/{run_id}/tables")
    def tables(run_id: str, offset: int = 0, limit: int = 200):
        if offset < 0 or not 1 <= limit <= 1000:
            raise HTTPException(422, "分页范围非法")
        try:
            service.run(run_id)
        except LookupError as error:
            raise HTTPException(404, str(error)) from error
        with service.database.transaction() as connection:
            cursor = connection.execute(
                "SELECT * FROM timetable_events WHERE run_id=? "
                "ORDER BY train_course_id,visit_seq LIMIT ? OFFSET ?",
                [run_id, limit, offset],
            )
            fields = [d[0] for d in cursor.description]
            events = [dict(zip(fields, r, strict=True)) for r in cursor.fetchall()]
            rows = connection.execute(
                "SELECT kind,data FROM infrastructure_records WHERE run_id=?", [run_id]
            ).fetchall()
        import json

        infrastructure = {}
        for kind, data in rows:
            infrastructure.setdefault(kind, []).append(json.loads(data))
        return {
            "events": events,
            "infrastructure": infrastructure,
            "offset": offset,
            "limit": limit,
        }

    @api.get("/source-files/{file_id}")
    def source(file_id: str):
        with service.database.transaction() as connection:
            row = connection.execute(
                "SELECT managed_name,filename FROM source_files WHERE id=?", [file_id]
            ).fetchone()
        if not row:
            raise HTTPException(404, "源文件记录不存在")
        path = (service.sources / row[0]).resolve()
        if path.parent != service.sources.resolve() or not path.is_file():
            raise HTTPException(404, "受管源文件不存在")
        return FileResponse(
            path,
            filename=row[1],
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @api.get("/bindings/{scope_id}/preview")
    def binding_preview(scope_id: str):
        try:
            return service.binding_preview(scope_id)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @api.put("/bindings/{scope_id}")
    def bind(scope_id: str, payload: BindingChange):
        try:
            return service.bind(scope_id, payload)
        except ImportConflict as error:
            raise HTTPException(409, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    return api
