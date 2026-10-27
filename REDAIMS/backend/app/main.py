import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.api.v1.diagram_views import router as diagram_view_router
from app.api.v1.run_analysis import router as run_analysis_router
from app.api.v1.solver_logs import router as solver_log_router
from app.api.v1.timetables import router as timetable_router
from app.base_timetables.service import TimetableService
from app.catalog.service import (
    CatalogCreate,
    CatalogDelete,
    CatalogPatch,
    CatalogService,
    StalePreviewError,
)
from app.core.config import Settings, load_settings
from app.ingest.inspection import inspect_workbook
from app.storage.database import Database

logger = logging.getLogger("redaims")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    database = Database(settings.database)
    catalog = CatalogService(database)
    importer = TimetableService(database, settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        database.initialize()
        importer.recover()
        logger.info("REDAIMS database ready")
        yield

    application = FastAPI(title="REDAIMS API", version="0.1.0", lifespan=lifespan)
    application.openapi_version = "3.1.0"
    application.state.database = database

    @application.get("/api/v1/health", tags=["system"])
    def health():
        with database.transaction() as connection:
            connection.execute("SELECT 1").fetchone()
        return {"status": "ok", "version": "0.1.0"}

    @application.get("/api/v1/catalog", tags=["catalog"])
    def list_catalog():
        return catalog.list_nodes()

    @application.post("/api/v1/catalog", status_code=201, tags=["catalog"])
    def create_catalog(payload: CatalogCreate):
        try:
            return catalog.create(payload)
        except FileExistsError as error:
            raise HTTPException(409, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @application.patch("/api/v1/catalog/{node_id}", tags=["catalog"])
    def patch_catalog(node_id: str, payload: CatalogPatch):
        try:
            return catalog.update_notes(node_id, payload.notes)
        except LookupError as error:
            raise HTTPException(404, str(error)) from error

    @application.post(
        "/api/v1/ingest/inspect",
        tags=["ingest"],
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
    async def inspect_excel(request: Request, sheet: str | None = None):
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > 32 * 1024 * 1024:
                raise HTTPException(413, "文件超过 32 MB 限制")
        try:
            return await run_in_threadpool(inspect_workbook, bytes(content), sheet)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @application.get("/api/v1/catalog/{node_id}/deletion-preview", tags=["catalog"])
    def deletion_preview(node_id: str):
        try:
            return catalog.deletion_preview(node_id)
        except LookupError as error:
            raise HTTPException(404, str(error)) from error

    @application.delete("/api/v1/catalog/{node_id}", tags=["catalog"])
    def delete_catalog(node_id: str, payload: CatalogDelete):
        try:
            result = catalog.delete(node_id, payload)
            importer.cleanup_files()
            return result
        except LookupError as error:
            raise HTTPException(404, str(error)) from error
        except (StalePreviewError, FileExistsError) as error:
            raise HTTPException(409, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @application.get("/api/v1/runs/ungrouped", tags=["catalog"])
    def ungrouped_runs():
        return catalog.ungrouped_runs()

    application.include_router(timetable_router(importer, settings))
    application.include_router(solver_log_router(database))
    application.include_router(diagram_view_router(database))
    application.include_router(run_analysis_router(database))
    return application


app = create_app()
