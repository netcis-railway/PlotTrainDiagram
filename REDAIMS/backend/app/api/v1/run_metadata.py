"""Run identity and inheritable section annotations, separate from timetable edits."""

import json
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Section = Literal["diagram", "log", "delay"]
Note = Annotated[str, Field(max_length=20000)]
SectionNotes = dict[Section, Note | None]


class SectionNoteUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section: Section
    notes: Note | None


class RunSectionNoteUpdate(SectionNoteUpdate):
    notes: Note


class RunMetadataPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    notes: Note | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if value is not None and not value.strip():
            raise ValueError("请输入run名称")
        return value.strip() if value is not None else value

    @model_validator(mode="after")
    def valid_changes(self):
        if not self.model_fields_set or any(
            getattr(self, key) is None for key in self.model_fields_set
        ):
            raise ValueError("请提供名称或备注，且不能为null")
        return self


def read_metadata(c, run_id):
    row = c.execute(
        "SELECT id,batch_id,name,run_no,notes,analysis_notes FROM runs WHERE id=? "
        "AND id NOT IN (SELECT run_id FROM base_run_data WHERE role='base')",
        [run_id],
    ).fetchone()
    if not row:
        raise HTTPException(404, "普通run不存在")
    return dict(
        zip(
            ("id", "batch_id", "name", "run_no", "notes", "analysis_notes"),
            (*row[:4], row[4] or "", json.loads(row[5] or "{}")),
            strict=True,
        )
    )


def router(database):
    api = APIRouter(prefix="/api/v1/runs", tags=["run-metadata"])

    @api.get("/{run_id}/metadata")
    def get_metadata(run_id: str):
        with database.transaction() as c:
            return read_metadata(c, run_id)

    @api.patch("/{run_id}/metadata")
    def update_metadata(run_id: str, payload: RunMetadataPatch):
        with database.transaction() as c:
            current = read_metadata(c, run_id)
            name = payload.name if "name" in payload.model_fields_set else current["name"]
            notes = payload.notes if "notes" in payload.model_fields_set else current["notes"]
            if (
                name != current["name"]
                and c.execute(
                    "SELECT 1 FROM runs WHERE batch_id IS NOT DISTINCT FROM ? "
                    "AND name=? AND run_no=? AND id<>?",
                    [current["batch_id"], name, current["run_no"], run_id],
                ).fetchone()
            ):
                raise HTTPException(409, "所属批次已有同名同编号run，请使用其他名称")
            c.execute("UPDATE runs SET name=?,notes=? WHERE id=?", [name, notes, run_id])
            return read_metadata(c, run_id)

    @api.patch("/{run_id}/analysis-notes")
    def update_notes(run_id: str, payload: RunSectionNoteUpdate):
        with database.transaction() as c:
            current = read_metadata(c, run_id)
            notes = current["analysis_notes"] | {payload.section: payload.notes}
            c.execute(
                "UPDATE runs SET analysis_notes=? WHERE id=?",
                [json.dumps(notes, ensure_ascii=False), run_id],
            )
            return read_metadata(c, run_id)

    return api
