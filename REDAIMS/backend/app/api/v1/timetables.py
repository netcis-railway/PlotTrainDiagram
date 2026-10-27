from datetime import date
from functools import wraps
from typing import Annotated, Literal
from urllib.parse import quote

from app.analysis.delays import read_delays
from app.base_timetables.editing import EditorService, EditRequest, SaveRequest
from app.base_timetables.exporting import ExportService
from app.base_timetables.migration import MigrationService
from app.base_timetables.service import Confirmation, Delete, Move, Options, Target
from app.base_timetables.time_shift import TimeShiftRequest, TimeShiftService
from app.base_timetables.track_repair import EditorRepairRequest, RepairRequest, TrackRepairService
from app.diagram.service import PlotRequest, PlotService
from app.ingest.base_service import ImportConflict, encode
from app.ingest.run_service import RunImportService, RunOptions
from app.ingest.sequence_repair import SequenceRepairRequest, SequenceRepairService
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from starlette.concurrency import run_in_threadpool


def guarded(fn):
    @wraps(fn)
    def call(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except LookupError as error:
            raise HTTPException(404, str(error)) from error
        except ImportConflict as error:
            raise HTTPException(409, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except OSError as error:
            raise HTTPException(503, "文件操作失败，原数据未提交，请核对目录后重试") from error

    return call


def router(service, settings):
    api = APIRouter(prefix="/api/v1", tags=["timetables"])
    editor = EditorService(service)
    time_shifter = TimeShiftService(editor)
    exporter = ExportService(editor)
    repairer = TrackRepairService(editor)
    sequence_repairer = SequenceRepairService(service)
    plotter = PlotService(editor)
    result_importer = RunImportService(service)
    migration = MigrationService(service, settings)

    @api.post("/time-shift/{kind}/{object_id}/preview")
    @guarded
    def time_shift_preview(kind: Literal["base", "run"], object_id: str, payload: TimeShiftRequest):
        return time_shifter.preview(kind, object_id, payload)

    @api.get("/ingest/jobs/{job_id}/sequence-repair/context")
    @guarded
    def sequence_context(job_id: str):
        return sequence_repairer.context(job_id)

    @api.post("/ingest/jobs/{job_id}/sequence-repair/apply")
    @guarded
    def sequence_apply(job_id: str, payload: SequenceRepairRequest):
        content = sequence_repairer.apply(job_id, payload)
        return Response(
            content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Cache-Control": "no-store"},
        )

    @api.post("/track-repair/{kind}/{object_id}/context")
    @guarded
    def repair_context(kind: Literal["base", "run"], object_id: str, payload: EditRequest):
        return repairer.editor_context(kind, object_id, payload)

    @api.post("/track-repair/{kind}/{object_id}/apply")
    @guarded
    def repair_apply(kind: Literal["base", "run"], object_id: str, payload: EditorRepairRequest):
        return repairer.editor_apply(kind, object_id, payload)

    @api.get("/ingest/jobs/{job_id}/track-repair/context")
    @guarded
    def repair_import_context(job_id: str):
        return repairer.workbook_context(job_id)

    @api.post("/ingest/jobs/{job_id}/track-repair/apply")
    @guarded
    def repair_import_apply(job_id: str, payload: RepairRequest):
        result, content = repairer.workbook_apply(job_id, payload)
        if content is None:
            return result
        return Response(
            content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Cache-Control": "no-store",
                "X-Repair-Warnings": str(len(result["warnings"])),
            },
        )

    @api.get("/runs/{run_id}/delay-analysis")
    @guarded
    def delay_analysis(run_id: str):
        return read_delays(editor, run_id)

    @api.get("/diagram/lines")
    @guarded
    def diagram_lines(object_type: Literal["base", "run"], object_id: str):
        return plotter.context(object_type, object_id)

    @api.post("/diagram/data")
    @guarded
    def diagram_data(payload: PlotRequest):
        return plotter.data(payload)

    @api.get("/diagram/styles")
    @guarded
    def diagram_styles():
        return plotter.style_config()

    @api.get("/diagram/warnings")
    @guarded
    def diagram_warnings():
        return plotter.read_log()

    @api.post(
        "/base-timetables/import/preview",
        status_code=201,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
                },
            }
        },
    )
    async def preview(
        request: Request,
        owner_category_id: str,
        name: Annotated[str, Query(min_length=1, max_length=200)],
        filename: str,
        date_base: date = date(2026, 1, 1),
        date_mode: Literal["rebase", "preserve"] = "rebase",
        sheet: str | None = None,
    ):
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > 32 * 1024 * 1024:
                raise HTTPException(413, "文件超过32 MB限制")
        return await run_in_threadpool(
            guarded(service.preview),
            bytes(content),
            filename,
            Options(
                owner_category_id=owner_category_id,
                name=name,
                date_base=date_base,
                date_mode=date_mode,
                sheet=sheet,
            ),
        )

    @api.get("/base-timetables")
    def bases():
        return service.list_bases()

    @api.get("/base-timetables/{base_id}")
    @guarded
    def detail(base_id: str):
        return service.detail(base_id)

    @api.get("/base-timetables/{base_id}/tables")
    @guarded
    def tables(base_id: str):
        return editor.read("base", base_id)

    @api.get("/ingest/jobs")
    def jobs():
        return service.jobs()

    @api.get("/ingest/jobs/{job_id}")
    @guarded
    def job(job_id: str):
        return service.job(job_id)

    @api.delete("/ingest/jobs/{job_id}")
    @guarded
    def cancel(job_id: str):
        return service.cancel(job_id)

    @api.post("/base-timetables/import/{job_id}/commit")
    @guarded
    def commit(job_id: str, payload: Confirmation):
        return service.commit(job_id, payload)

    @api.get("/catalog/{category_id}/base-timetable")
    @guarded
    def resolution(category_id: str):
        return service.resolution(category_id)

    @api.post("/base-timetables/{base_id}/move-preview")
    @guarded
    def move_preview(base_id: str, payload: Target):
        return service.move_preview(base_id, payload.target_category_id)

    @api.post("/base-timetables/{base_id}/move")
    @guarded
    def move(base_id: str, payload: Move):
        return service.move(base_id, payload)

    @api.get("/base-timetables/{base_id}/deletion-preview")
    @guarded
    def delete_preview(base_id: str):
        return service.deletion_preview(base_id)

    @api.delete("/base-timetables/{base_id}")
    @guarded
    def delete(base_id: str, payload: Delete):
        return service.delete(base_id, payload)

    @api.get("/base-timetable-migrations")
    def legacy():
        return migration.list_legacy()

    @api.post("/base-timetable-migrations/{old_id}/preview")
    @guarded
    def migration_preview(old_id: str, payload: Target):
        return migration.preview(old_id, payload.target_category_id)

    @api.post("/base-timetable-migrations/{old_id}/commit")
    @guarded
    def migration_commit(old_id: str, payload: Move):
        return migration.commit(old_id, payload)

    @api.get("/source-files/{source_id}")
    @guarded
    def source(source_id: str):
        with service.database.transaction() as c:
            row = c.execute(
                "SELECT managed_name,filename FROM base_tt_sources WHERE id=? "
                "UNION ALL SELECT managed_name,filename FROM source_files WHERE "
                "id=?",
                [source_id, source_id],
            ).fetchone()
        if not row:
            raise LookupError("来源不存在")
        path = (service.sources / row[0]).resolve()
        if path.parent != service.sources.resolve() or not path.is_file():
            raise LookupError("受管源文件不存在")
        return FileResponse(path, filename=row[1])

    @api.post(
        "/runs/import/preview",
        status_code=201,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
                },
            }
        },
    )
    async def run_preview(
        request: Request,
        batch_id: str,
        name: Annotated[str, Query(min_length=1, max_length=200)],
        filename: str,
        run_no: Annotated[int | None, Query(ge=0, le=2147483647)] = None,
        date_base: date = date(2026, 1, 1),
        date_mode: Literal["rebase", "preserve"] = "rebase",
        sheet: str | None = None,
        write_mode: Literal["create", "replace"] = "create",
        target_run_id: str | None = None,
    ):
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > 32 * 1024 * 1024:
                raise HTTPException(413, "文件超过32 MB限制")
        return await run_in_threadpool(
            guarded(result_importer.preview),
            bytes(content),
            filename,
            RunOptions(
                batch_id=batch_id,
                name=name,
                run_no=run_no,
                date_base=date_base,
                date_mode=date_mode,
                sheet=sheet,
                write_mode=write_mode,
                target_run_id=target_run_id,
            ),
        )

    @api.get("/runs/import/jobs")
    def run_jobs():
        return result_importer.jobs()

    @api.get("/runs/import/jobs/{job_id}")
    @guarded
    def run_job(job_id: str):
        return result_importer.job(job_id)

    @api.delete("/runs/import/jobs/{job_id}")
    @guarded
    def cancel_run_job(job_id: str):
        return result_importer.cancel(job_id)

    @api.post("/runs/import/{job_id}/commit")
    @guarded
    def run_commit(job_id: str, payload: Confirmation):
        return result_importer.commit(job_id, payload)

    @api.get("/runs")
    def runs():
        with service.database.transaction() as c:
            return [
                dict(zip(("id", "batch_id", "name", "run_no"), r, strict=True))
                for r in c.execute(
                    "SELECT id,batch_id,name,run_no FROM runs WHERE id NOT IN (SELECT "
                    "run_id FROM base_run_data WHERE role='base') ORDER BY name,id"
                ).fetchall()
            ]

    @api.get("/runs/{run_id}/tables")
    @guarded
    def run_tables(run_id: str):
        return editor.read("run", run_id)

    @api.get("/runs/{run_id}")
    @guarded
    def run_detail(run_id: str):
        return editor.read("run", run_id)["object"]

    def run_move_info(c, run_id, target):
        meta, doc, _, revision = editor._load(c, "run", run_id)
        path = service.category(c, target)
        if path[-1]["kind"] != "batch":
            raise ValueError("普通 run 只能归属批次")
        if meta["owner_category_id"] == target:
            raise ValueError("目标与当前位置相同")
        duplicate = c.execute(
            "SELECT id FROM runs WHERE batch_id=? AND name=? AND run_no=? AND id<>?",
            [target, meta["name"], meta["run_no"], run_id],
        ).fetchone()
        if duplicate:
            raise ValueError("目标批次已有同名同编号 run")
        if doc["events"]:
            old_network = next(
                (n["id"] for n in meta["classification_path"] if n["kind"] == "network"), None
            )
            new_network = next(n["id"] for n in path if n["kind"] == "network")
            if old_network != new_network:
                raise ValueError("有时刻数据的 run 跨路网转移尚需映射确认，暂不开放")
        return {
            "can_move": True,
            "source_path": meta["classification_path"],
            "target_path": path,
            "preview_token": encode([revision, target]),
            "issues": [],
            "impact": [
                {
                    "kind": "run",
                    "id": run_id,
                    "name": meta["name"],
                    "before": meta["effective_base"],
                    "after": service.resolve_state(service.state(c), target),
                }
            ],
        }

    @api.post("/runs/{run_id}/move-preview")
    @guarded
    def run_move_preview(run_id: str, payload: Target):
        with service.database.transaction() as c:
            return run_move_info(c, run_id, payload.target_category_id)

    @api.post("/runs/{run_id}/move")
    @guarded
    def run_move(run_id: str, payload: Move):
        with service.database.transaction() as c:
            info = run_move_info(c, run_id, payload.target_category_id)
            if info["preview_token"] != payload.preview_token:
                raise ImportConflict("归属预览已过期")
            c.execute("UPDATE runs SET batch_id=? WHERE id=?", [payload.target_category_id, run_id])
        return editor.read("run", run_id)["object"]

    @api.post("/base-timetables/{object_id}/events/validate")
    @guarded
    def validate_base(object_id: str, payload: EditRequest):
        return editor.validate("base", object_id, payload)

    @api.post("/base-timetables/{object_id}/events/edit")
    @guarded
    def save_base(object_id: str, payload: SaveRequest):
        return editor.save("base", object_id, payload)

    @api.post("/runs/{object_id}/events/validate")
    @guarded
    def validate_run(object_id: str, payload: EditRequest):
        return editor.validate("run", object_id, payload)

    @api.post("/runs/{object_id}/events/edit")
    @guarded
    def save_run(object_id: str, payload: SaveRequest):
        return editor.save("run", object_id, payload)

    @api.get("/base-timetables/{object_id}/export-options")
    @guarded
    def base_export_options(object_id: str):
        return exporter.options("base", object_id)

    @api.get("/runs/{object_id}/export-options")
    @guarded
    def run_export_options(object_id: str):
        return exporter.options("run", object_id)

    async def export_response(kind, object_id, request, revision, sheets, replace):
        original = bytearray()
        async for chunk in request.stream():
            original.extend(chunk)
            if len(original) > 32 * 1024 * 1024:
                raise HTTPException(413, "源文件超过32 MB限制")
        if replace and not original:
            raise HTTPException(422, "覆盖表单需要用户选择并提供源Excel文件")
        if original and not replace:
            raise HTTPException(422, "另存新文件不接受源文件内容")
        content, filename = await run_in_threadpool(
            guarded(exporter.render),
            kind,
            object_id,
            revision,
            sheets.split(","),
            bytes(original) if replace else None,
        )
        return Response(
            content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename),
                "Cache-Control": "no-store",
            },
        )

    @api.post(
        "/base-timetables/{object_id}/export",
        openapi_extra={
            "requestBody": {
                "content": {
                    "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
                }
            }
        },
    )
    async def export_base(
        object_id: str, request: Request, revision: str, sheets: str, replace: bool = False
    ):
        return await export_response("base", object_id, request, revision, sheets, replace)

    @api.post(
        "/runs/{object_id}/export",
        openapi_extra={
            "requestBody": {
                "content": {
                    "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
                }
            }
        },
    )
    async def export_run(
        object_id: str, request: Request, revision: str, sheets: str, replace: bool = False
    ):
        return await export_response("run", object_id, request, revision, sheets, replace)

    @api.post("/ingest/base/preview", deprecated=True)
    @api.post("/ingest/jobs/{scope_id}/commit", deprecated=True)
    @api.put("/bindings/{scope_id}", deprecated=True)
    def retired(scope_id: str = ""):
        raise HTTPException(
            410, "基本图已独立管理，请刷新页面使用新导入/所属类别入口；旧数据请显式迁移"
        )

    return api
