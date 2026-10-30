"""Plot experiment members from one consistent transaction and one shared axis."""

from colorsys import hsv_to_rgb

from pydantic import BaseModel, ConfigDict, Field

from app.base_timetables.editing import EditorService
from app.base_timetables.service import token
from app.diagram.axis import build_axis, number, problem
from app.diagram.series import build_series
from app.diagram.service import PlotService
from app.diagram.tracks import expand_track_usage, track_resources
from app.experiments.service import ExperimentConflict


class ExperimentPlotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(min_length=1, max_length=200)
    line_ind: int = Field(ge=1)
    overlay_base: bool = True
    expanded_stations: list[str] = Field(default_factory=list, max_length=500)


def run_color(index):
    first = ["#d32f2f", "#1565c0", "#006400", "#7b1fa2", "#e67e22", "#00838f"]
    if index < len(first):
        return first[index]
    rgb = hsv_to_rgb((index * 0.61803398875) % 1, 0.72, 0.72)
    return "#" + "".join(f"{round(channel * 255):02x}" for channel in rgb)


class ExperimentAnalysisService:
    def __init__(self, experiments):
        self.experiments = experiments
        self.database = experiments.database
        self.editor = EditorService(experiments.timetables)
        self.plotter = PlotService(self.editor)

    def _inputs(self, c, experiment_id):
        experiment = self.experiments._detail(
            c, self.experiments._row(c, experiment_id), self.experiments._runs(c)
        )
        if experiment["status"] != "ready":
            raise ExperimentConflict(
                "实验尚不能分析：" + ("；".join(experiment["issues"]) or "请先加入成员run")
            )
        members = sorted(experiment["members"], key=lambda m: (m["run_no"], m["id"]))
        loaded = [self.plotter.load(c, "run", member["id"]) for member in members]
        revision = token([experiment["id"], experiment["revision"], [item[3] for item in loaded]])
        sources = [{**member, "color": run_color(index)} for index, member in enumerate(members)]
        meta = {
            **loaded[0][0],
            "id": experiment["id"],
            "name": experiment["name"],
            "owner_category_id": experiment["owner_category_id"],
            "classification_path": experiment["classification_path"],
            "run_no": None,
        }
        return meta, loaded, sources, revision

    def context(self, experiment_id):
        with self.database.transaction() as c:
            meta, loaded, members, revision = self._inputs(c, experiment_id)
            infrastructure, base = loaded[0][2], loaded[0][4]
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
                "members": members,
                "lines": sorted(lines, key=lambda line: line["line_ind"]),
                "overlay_available": True,
                "issues": [],
            }

    def data(self, experiment_id, payload):
        styles, style_issues = self.plotter.styles.read()
        issues = list(style_issues)
        with self.database.transaction() as c:
            meta, loaded, members, revision = self._inputs(c, experiment_id)
            if payload.revision != revision:
                raise ExperimentConflict("实验成员、时刻表或基本图已变化，请刷新实验图形数据")
            infrastructure, base = loaded[0][2], loaded[0][4]
            axis, axis_issues = build_axis(infrastructure, payload.line_ind)
            issues.extend(axis_issues)
            series = []
            if not any(issue["severity"] == "error" for issue in issues):
                for member, (run_meta, doc, _, _, _) in zip(members, loaded, strict=True):
                    current, warnings = build_series(run_meta, doc, axis)
                    for item in current:
                        item["color"] = member["color"]
                    series.extend(current)
                    issues.extend(warnings)
                    if not any(item["points"] for item in current):
                        issues.append(
                            problem("no_times", f"{member['name']}：所选线路无有效时刻", "warning")
                        )
                if payload.overlay_base:
                    planned_dates = {
                        t["train_course_id"]: str(t["train_base_date"])
                        for t in infrastructure["trains"]
                    }
                    for member, (_, doc, _, _, _) in zip(members, loaded, strict=True):
                        mismatched = [
                            t["train_course_id"]
                            for t in doc["trains"]
                            if t["train_course_id"] in planned_dates
                            and str(t["train_base_date"]) != planned_dates[t["train_course_id"]]
                        ]
                        if mismatched:
                            issues.append(
                                problem(
                                    "comparison_train_date",
                                    f"{member['name']}：同名列车实例基准日不同，不能叠加："
                                    + "、".join(mismatched),
                                )
                            )
                    other, warnings = build_series(
                        base | {"object_type": "base"}, infrastructure, axis
                    )
                    series.extend(other)
                    issues.extend(warnings)
                if not any(item["points"] for item in series if item["object_type"] == "run"):
                    issues.append(problem("no_times", "实验成员在所选线路均无可绘制时刻"))
            resources = track_resources(infrastructure, axis, payload.line_ind)
            expanded, warnings = expand_track_usage(
                series,
                resources,
                payload.expanded_stations if axis["stations"] else [],
                styles["track_yita_seconds"],
            )
            issues.extend(warnings)
            axis_revision = token(
                [
                    base,
                    infrastructure.get("members", []),
                    infrastructure.get("minimum_run_times", []),
                ]
            )
        operation_id, written = self.plotter.log(
            issues,
            {"experiment_id": experiment_id, "revision": revision, "line_ind": payload.line_ind},
        )
        times = [point["seconds"] for item in series for point in item["points"]]
        return {
            "object": meta,
            "revision": revision,
            "base": base,
            "members": members,
            "line_ind": payload.line_ind,
            "axis_revision": axis_revision,
            "axis": axis,
            "series": series,
            "track_stations": resources,
            "expanded_stations": expanded,
            "preview": False,
            "preview_changes": 0,
            "overlay_base": payload.overlay_base,
            "can_plot": not any(issue["severity"] == "error" for issue in issues),
            "time_extent": [min(times), max(times)] if times else None,
            "styles": styles,
            "style_source": str(self.plotter.styles.path),
            "issues": issues,
            "operation_id": operation_id,
            "log_written": written,
        }
