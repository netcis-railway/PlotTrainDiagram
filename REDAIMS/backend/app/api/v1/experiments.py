from app.experiments.analysis import ExperimentAnalysisService, ExperimentPlotRequest
from app.experiments.service import (
    AddMembers,
    CreateExperiment,
    DeleteExperiment,
    ExperimentConflict,
    ExperimentDetail,
    ExperimentRun,
    ExperimentService,
    PatchExperiment,
    RemoveMembers,
)
from fastapi import APIRouter, HTTPException


def router(database, timetables):
    api = APIRouter(prefix="/api/v1/experiments", tags=["experiments"])
    service = ExperimentService(database, timetables)
    analysis = ExperimentAnalysisService(service)

    def call(method, *args):
        try:
            return method(*args)
        except LookupError as error:
            raise HTTPException(404, str(error)) from error
        except ExperimentConflict as error:
            raise HTTPException(409, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @api.get("", response_model=list[ExperimentDetail])
    def list_experiments():
        return call(service.list)

    @api.get("/runs", response_model=list[ExperimentRun])
    def candidates():
        return call(service.candidates)

    @api.post("", status_code=201, response_model=ExperimentDetail)
    def create(payload: CreateExperiment):
        return call(service.create, payload)

    @api.get("/{experiment_id}", response_model=ExperimentDetail)
    def detail(experiment_id: str):
        return call(service.detail, experiment_id)

    @api.get("/{experiment_id}/diagram/lines")
    def diagram_context(experiment_id: str):
        return call(analysis.context, experiment_id)

    @api.post("/{experiment_id}/diagram/data")
    def diagram_data(experiment_id: str, payload: ExperimentPlotRequest):
        return call(analysis.data, experiment_id, payload)

    @api.patch("/{experiment_id}", response_model=ExperimentDetail)
    def update(experiment_id: str, payload: PatchExperiment):
        return call(service.update, experiment_id, payload)

    @api.post("/{experiment_id}/members", response_model=ExperimentDetail)
    def add_members(experiment_id: str, payload: AddMembers):
        return call(service.add, experiment_id, payload)

    @api.delete("/{experiment_id}/members", response_model=ExperimentDetail)
    def remove_members(experiment_id: str, payload: RemoveMembers):
        return call(service.remove, experiment_id, payload)

    @api.delete("/{experiment_id}")
    def delete(experiment_id: str, payload: DeleteExperiment):
        return call(service.delete, experiment_id, payload)

    return api
