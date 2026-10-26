"""Read-only plot datasets; the only side effect is the required diagnostic log."""

from datetime import UTC, date, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.base_timetables.editing import Change, EditRequest
from app.base_timetables.service import token
from app.diagram.axis import build_axis, number, problem
from app.diagram.series import build_series
from app.diagram.styles import StyleLoader
from app.diagram.tracks import expand_track_usage, track_resources
from app.ingest.base_service import ImportConflict, encode


class PlotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_type: Literal["base", "run"]
    object_id: str
    revision: str
    line_ind: int = Field(ge=1)
    overlay_base: bool = False
    expanded_stations: list[str] = Field(default_factory=list, max_length=500)
    date_base: date | None = None
    changes: list[Change] = Field(default_factory=list, max_length=100000)


class PlotService:
    def __init__(self, editor):
        self.editor = editor
        self.base = editor.base
        self.database = editor.database
        self.styles = StyleLoader()
        self.style_warning = None
        self.style_log_written = True

    def load(self, c, kind, object_id):
        meta, doc, infrastructure, revision = self.editor._load(c, kind, object_id)
        if kind == "base":
            base_meta = meta
        else:
            base_id = meta["effective_base"]["base_tt_id"]
            base_meta = self.base._detail(c, self.base._row(c, base_id)) if base_id else None
        info = (
            {
                k: base_meta[k]
                for k in (
                    "id",
                    "baseTT_no",
                    "name",
                    "owner_category_id",
                    "classification_path",
                    "date_base",
                    "revision",
                )
            }
            if base_meta
            else None
        )
        return meta, doc, infrastructure, revision, info

    def context(self, kind, object_id):
        with self.database.transaction() as c:
            meta, doc, infrastructure, revision, base = self.load(c, kind, object_id)
            lines = []
            for row in infrastructure.get("lines", []):
                ind = number(row.get("LINE_IND"))
                if ind is None:
                    continue
                axis, issues = build_axis(infrastructure, ind)
                lines.append(
                    {
                        "line_ind": ind,
                        "line_code": row["LINE_CODE"],
                        "line_name_chn": row["LINE_NAME_CHN"],
                        "available": not issues,
                        "station_count": len(axis["stations"]),
                        "issues": issues,
                    }
                )
            return {
                "object": meta,
                "revision": revision,
                "base": base,
                "lines": sorted(lines, key=lambda line: line["line_ind"]),
                "overlay_available": bool(
                    base and kind == "run" and meta["date_base"] == base["date_base"]
                ),
                "issues": []
                if base
                else [
                    problem(
                        "missing_base",
                        "当前run没有有效基本图，缺少线路站序及最小运行时间，无法作图",
                    )
                ],
            }

    def log(self, issues, context):
        operation_id = str(uuid4())
        if not issues:
            return operation_id, True
        try:
            self.base.logs.mkdir(parents=True, exist_ok=True)
            entry = {
                "time": datetime.now(UTC).isoformat(),
                "operation_id": operation_id,
                "context": context,
                "issues": issues,
            }
            with self.database.lock:
                with (self.base.logs / "log_plottraindiagram.md").open(
                    "a", encoding="utf-8"
                ) as stream:
                    stream.write("\n```json\n" + encode(entry) + "\n```\n")
                if any(issue["code"] == "style_config" for issue in issues):
                    self.base.log_report(operation_id, "diagram_styles.json", issues)
            return operation_id, True
        except OSError as error:
            issues.append(problem("log_failure", f"绘图日志未能写入：{error}", "warning"))
            return operation_id, False

    def style_config(self):
        styles, issues = self.styles.read()
        signature = token(issues) if issues else None
        written = self.style_log_written if signature else True
        if signature and (signature != self.style_warning or not written):
            _, written = self.log(issues, {"source": str(self.styles.path)})
        self.style_warning = signature
        self.style_log_written = written
        return {
            "styles": styles,
            "issues": issues,
            "revision": token(styles),
            "source": str(self.styles.path),
            "log_written": written,
        }

    def read_log(self):
        path = self.base.logs / "log_plottraindiagram.md"
        if not path.exists():
            return {"filename": path.name, "text": "尚无绘图提示记录。"}
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - 65536))
            content = stream.read().decode("utf-8", errors="replace")
        return {"filename": path.name, "text": content}

    def data(self, payload: PlotRequest):
        styles, style_issues = self.styles.read()
        issues = list(style_issues)
        with self.database.transaction() as c:
            meta, doc, infrastructure, revision, base = self.load(
                c, payload.object_type, payload.object_id
            )
            if payload.revision != revision:
                raise ImportConflict(
                    "对象、归属或基本图已变化，请重新加载绘图数据；旧草稿需先在编辑器核对"
                )
            preview = bool(
                payload.changes
                or (payload.date_base and str(payload.date_base) != meta["date_base"])
            )
            if preview:
                validation, doc = self.editor._validate(
                    c,
                    payload.object_type,
                    payload.object_id,
                    EditRequest(
                        revision=revision, changes=payload.changes, date_base=payload.date_base
                    ),
                )
                issues.extend(
                    {"code": "draft_validation", **issue} for issue in validation["issues"]
                )
                meta = meta | {
                    "date_base": str(payload.date_base) if payload.date_base else meta["date_base"]
                }
            if not base:
                issues.append(problem("missing_base", "当前run没有有效基本图，无法生成运行图站轴"))
            if not meta["date_base"]:
                issues.append(problem("missing_data", "当前对象没有正式时刻数据和运行基准日"))
            axis, axis_issues = build_axis(infrastructure, payload.line_ind)
            issues.extend(axis_issues)
            series = []
            if not any(i["severity"] == "error" for i in issues):
                primary, warnings = build_series(meta, doc, axis)
                series.extend(primary)
                issues.extend(warnings)
                if payload.overlay_base and payload.object_type == "run":
                    if base["date_base"] != meta["date_base"]:
                        issues.append(
                            problem(
                                "comparison_date",
                                "基本图和run运行基准日不同，当前仅支持相同基准日叠加",
                            )
                        )
                    else:
                        base_doc = infrastructure
                        original_dates = {
                            t["train_course_id"]: str(t["train_base_date"])
                            for t in base_doc["trains"]
                        }
                        mismatched = [
                            t["train_course_id"]
                            for t in doc["trains"]
                            if t["train_course_id"] in original_dates
                            and str(t["train_base_date"]) != original_dates[t["train_course_id"]]
                        ]
                        if mismatched:
                            issues.append(
                                problem(
                                    "comparison_train_date",
                                    "同名列车实例基准日不同，不能叠加：" + "、".join(mismatched),
                                )
                            )
                        else:
                            other, warnings = build_series(
                                base | {"object_type": "base"}, base_doc, axis
                            )
                            series.extend(other)
                            issues.extend(warnings)
                if not any(item["points"] for item in primary):
                    issues.append(problem("no_times", "所选线路暂无当前对象可绘制的有效时刻"))
            resources = track_resources(infrastructure, axis, payload.line_ind)
            expanded, track_issues = expand_track_usage(
                series,
                resources,
                payload.expanded_stations if axis["stations"] else [],
                styles["track_yita_seconds"],
            )
            issues.extend(track_issues)
            axis_revision = token(
                [
                    base,
                    infrastructure.get("members", []),
                    infrastructure.get("minimum_run_times", []),
                ]
            )
        operation_id, log_written = self.log(
            issues,
            {
                "object_type": payload.object_type,
                "object_id": payload.object_id,
                "line_ind": payload.line_ind,
                "revision": revision,
                "base": base,
                "preview": preview,
            },
        )
        times = [point["seconds"] for item in series for point in item["points"]]
        return {
            "object": meta,
            "revision": revision,
            "base": base,
            "line_ind": payload.line_ind,
            "axis_revision": axis_revision,
            "axis": axis,
            "series": series,
            "track_stations": resources,
            "expanded_stations": expanded,
            "preview": preview,
            "preview_changes": len(payload.changes),
            "comparison_mode": "same_base_date",
            "overlay_base": payload.overlay_base,
            "can_plot": not any(i["severity"] == "error" for i in issues),
            "time_extent": [min(times), max(times)] if times else None,
            "styles": styles,
            "style_source": str(self.styles.path),
            "issues": issues,
            "operation_id": operation_id,
            "log_written": log_written,
        }
