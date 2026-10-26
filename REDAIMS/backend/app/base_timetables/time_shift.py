"""Generate a complete-train time-shift draft; validation never commits it."""

from pydantic import Field

from app.base_timetables.editing import Change, EditRequest
from app.ingest.base_service import ImportConflict


class TimeShiftRequest(EditRequest):
    train_ids: list[str] = Field(min_length=1, max_length=10000)
    offset_seconds: int = Field(ge=-2147483647, le=2147483647, strict=True)


def cumulative_time(seconds):
    hours, rem = divmod(seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


class TimeShiftService:
    def __init__(self, editor):
        self.editor = editor

    def preview(self, kind, object_id, request):
        with self.editor.database.transaction() as c:
            meta, doc, _, revision = self.editor._load(c, kind, object_id)
            if request.revision != revision:
                raise ImportConflict("数据、归属或基本图已变化，请重新打开平移窗口")
            if not meta["date_base"]:
                raise ValueError("当前对象尚无正式时刻数据和基准日期")
            if request.offset_seconds == 0:
                raise ValueError("平移量不能为0")
            selected = set(request.train_ids)
            known = {train["id"] for train in doc["trains"]}
            if len(selected) != len(request.train_ids) or not selected <= known:
                raise ValueError("所选列车不存在或重复，不允许修改其他对象")
            if request.changes or (
                request.date_base and str(request.date_base) != meta["date_base"]
            ):
                result, doc = self.editor._validate(c, kind, object_id, request)
                if not result["can_save"]:
                    return {"can_apply": False, "changes": [], "issues": result["issues"]}
            changes, counts = [], {}
            for train_id in request.train_ids:
                visits = [e for e in doc["events"] if e["train_id"] == train_id]
                cells = 0
                for event in visits:
                    for field in ("arrival", "departure"):
                        if event[field] is None:
                            continue
                        seconds = event[field]["seconds"] + request.offset_seconds
                        if seconds < 0:
                            raise ValueError(
                                f"{event['train_course_id']} / {event['node_name']} "
                                "平移后早于运行基准日，请先调整基准日"
                            )
                        changes.append(
                            Change(
                                event_id=event["id"], field=field, value=cumulative_time(seconds)
                            )
                        )
                        cells += 1
                if not cells:
                    raise ValueError("所选列车没有可平移的到发时刻")
                counts[train_id] = {"visits": len(visits), "cells": cells}
            merged = {(change.event_id, change.field): change for change in request.changes}
            merged.update({(change.event_id, change.field): change for change in changes})
            if len(merged) > 100000:
                raise ValueError("待保存单元格超过100000条，请分批选择列车")
            result, _ = self.editor._validate(
                c,
                kind,
                object_id,
                EditRequest(
                    revision=revision, date_base=request.date_base, changes=list(merged.values())
                ),
            )
            return {
                "can_apply": result["can_save"],
                "changes": [change.model_dump() for change in changes]
                if result["can_save"]
                else [],
                "issues": result["issues"],
                "offset_seconds": request.offset_seconds,
                "trains": [
                    {
                        "id": train["id"],
                        "train_course_id": train["train_course_id"],
                        **counts[train["id"]],
                    }
                    for train in doc["trains"]
                    if train["id"] in selected
                ],
                "train_date_changes": result["train_date_changes"],
            }
