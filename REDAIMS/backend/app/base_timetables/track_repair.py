"""Explicit draft-only track repair shared by imports and the timetable editor."""

import re
from collections import defaultdict
from datetime import date
from io import BytesIO
from typing import Literal

from openpyxl import load_workbook
from pydantic import BaseModel, ConfigDict, Field

from app.base_timetables.editing import EditRequest
from app.base_timetables.service import token
from app.ingest.base_parser import integer, parse_base
from app.ingest.base_service import ImportConflict
from app.ingest.inspection import inspect_workbook, train_columns
from app.ingest.repair_source import import_source
from app.ingest.tracks import read_direction


class LineChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line_ind: int = Field(ge=1, le=2147483647)
    directions: list[Literal["UB", "DB"]] = Field(min_length=1, max_length=2)


class TrainChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    train_id: str
    lines: list[LineChoice] = Field(min_length=1, max_length=1000)


class RepairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repair_token: str
    selections: list[TrainChoice] = Field(min_length=1, max_length=10000)


class EditorRepairRequest(EditRequest):
    repair_token: str
    selections: list[TrainChoice] = Field(min_length=1, max_length=10000)


def default_direction(course):
    first = course.split("/", 1)[0]
    match = re.search(r"(\d+)$", first)
    return ("DB" if int(match[1]) % 2 else "UB") if match else None


def repair_context(doc, infrastructure, missing=()):
    missing = set(missing)
    lines = sorted(infrastructure.get("lines", []), key=lambda line: int(line["LINE_IND"]))
    members = infrastructure.get("members", [])
    trains = []
    for train in doc["trains"]:
        visits = [e for e in doc["events"] if e["train_id"] == train["id"]]
        stations = {e["node_name"] for e in visits}
        related = sorted({int(m["line_ind"]) for m in members if m["node_name"] in stations})
        empty = sum(e.get("track_code") in (None, "") for e in visits)
        trains.append(
            {
                "id": train["id"],
                "train_course_id": train["train_course_id"],
                "related_lines": related,
                "direction": default_direction(train["train_course_id"]),
                "missing_g": train["id"] in missing,
                "empty_count": empty,
                "visits": len(visits),
            }
        )
    return {
        "trains": trains,
        "lines": [
            {"line_ind": int(line["LINE_IND"]), "line_name_chn": line["LINE_NAME_CHN"]}
            for line in lines
        ],
    }


def interval(event):
    a, d = event.get("arrival"), event.get("departure")
    if not a and not d:
        raise ValueError("缺少到达和出发时刻，无法确定占用时间")
    start = (a or d)["seconds"]
    end = (d or a)["seconds"]
    if end < start:
        raise ValueError("出发早于到达，无法分配股道，请先修正时刻")
    # A point visit reserves one second, matching the timetable's second precision.
    return start, max(start + 1, end)


def overlaps(left, right):
    return left[0] < right[1] and right[0] < left[1]


def allocate(doc, infrastructure, selections):
    """Solve each physical station independently, keeping unselected trains fixed."""
    trains = {t["id"]: t for t in doc["trains"]}
    choices = {}
    known_lines = {int(line["LINE_IND"]) for line in infrastructure.get("lines", [])}
    for choice in selections:
        if choice.train_id not in trains or choice.train_id in choices:
            raise ValueError("修复列车不存在或重复，请重新选择")
        ids = [line.line_ind for line in choice.lines]
        if len(ids) != len(set(ids)) or not set(ids) <= known_lines:
            raise ValueError("所选线路不存在或重复")
        choices[choice.train_id] = choice
    issues, warnings, jobs, reserved = [], [], defaultdict(list), defaultdict(list)
    members = infrastructure.get("members", [])
    names = {n["node_name"]: n.get("node_name_chn", n["node_name"]) for n in doc["nodes"]}

    def problem(event, message):
        return {
            "event_id": event["id"],
            "train_course_id": event["train_course_id"],
            "node_name": event["node_name"],
            "node_name_chn": names.get(event["node_name"], event["node_name"]),
            "message": message,
        }

    selected_stations = {e["node_name"] for e in doc["events"] if e["train_id"] in choices}
    for event in doc["events"]:
        if event["node_name"] not in selected_stations:
            continue
        selected = choices.get(event["train_id"])
        if not selected:
            try:
                track = integer(event["track_code"])
            except (ValueError, TypeError):
                warnings.append(
                    problem(event, "未选列车股道缺失或无效，无法检查其占用；可将该列车一并选中修复")
                )
                continue
            try:
                reserved[(event["node_name"], track)].append(interval(event))
            except ValueError as error:
                issues.append(problem(event, f"未选列车已有股道但{error}"))
            continue
        try:
            span = interval(event)
        except ValueError as error:
            issues.append(problem(event, str(error)))
            continue
        preferred, fallback = set(), set()
        passing = bool(
            event.get("arrival")
            and event.get("departure")
            and event["arrival"]["seconds"] == event["departure"]["seconds"]
        )
        unknown = False
        for choice in selected.lines:
            for member in members:
                if (
                    member["node_name"] != event["node_name"]
                    or int(member["line_ind"]) != choice.line_ind
                ):
                    continue
                for direction in set(choice.directions):
                    try:
                        tracks = read_direction(member, direction)
                    except ValueError:
                        unknown = True
                        continue
                    stops = set(tracks.stop_tracks)
                    main = {tracks.main_track} if tracks.main_track is not None else set()
                    preferred.update(main if passing else stops)
                    fallback.update(stops if passing else main)
        candidates = sorted(preferred) + sorted(fallback - preferred)
        if not candidates:
            issues.append(
                problem(
                    event,
                    "所选线路/方向的股道资料未知" if unknown else "所选线路/方向在本站没有可用股道",
                )
            )
        jobs[event["node_name"]].append((event, span, candidates))
    # Filter after all fixed reservations have been gathered, regardless of source order.
    assignments = {}
    for station, rows in jobs.items():
        pending = []
        for event, span, tracks in rows:
            allowed = [
                t for t in tracks if not any(overlaps(span, s) for s in reserved[(station, t)])
            ]
            if tracks and not allowed:
                issues.append(problem(event, "可选股道均与未选列车占用重叠"))
            pending.append((event, span, allowed))
        if any(not row[2] for row in pending):
            continue
        occupied = defaultdict(list)
        attempts = 0

        def solve(remaining):
            nonlocal attempts
            attempts += 1
            if attempts > 20000:
                return False
            if not remaining:
                return True
            options = []
            for event, span, tracks in remaining:
                free = [t for t in tracks if not any(overlaps(span, s) for s in occupied[t])]
                options.append((event, span, free))
            event, span, free = min(
                options, key=lambda r: (len(r[2]), r[1][0], r[0]["train_course_id"], r[0]["id"])
            )
            rest = [r for r in remaining if r[0]["id"] != event["id"]]
            for track in free:
                occupied[track].append(span)
                assignments[event["id"]] = track
                if solve(rest):
                    return True
                occupied[track].pop()
                assignments.pop(event["id"], None)
            return False

        # Bound per-station recursion depth and report oversized selections explicitly.
        if len(pending) > 500:
            issues.append(problem(pending[0][0], "本站待分配访问超过500条，请分批选择列车"))
        elif not solve(pending):
            issues.append(
                problem(
                    pending[0][0],
                    "搜索达到上限，请缩小选择范围"
                    if attempts > 20000
                    else "股道容量不足，无法在占用不重叠的条件下分配，请调整线路/方向或时刻",
                )
            )
    if issues:
        return {"can_apply": False, "changes": [], "issues": issues, "warnings": warnings}
    changes = [
        {"event_id": e["id"], "field": "track_code", "value": assignments[e["id"]]}
        for e in doc["events"]
        if e["id"] in assignments
    ]
    return {"can_apply": True, "changes": changes, "issues": [], "warnings": warnings}


class TrackRepairService:
    def __init__(self, editor):
        self.editor = editor
        self.base = editor.base

    def editor_state(self, c, kind, object_id, request):
        meta, doc, infrastructure, revision = self.editor._load(c, kind, object_id)
        if request.revision != revision:
            raise ImportConflict("数据、归属或基本图已变化，请重新打开修复窗口")
        if request.changes or (request.date_base and str(request.date_base) != meta["date_base"]):
            result, doc = self.editor._validate(c, kind, object_id, request)
            errors = [
                i
                for i in result["issues"]
                if i["severity"] == "error" and i.get("field") != "track_code"
            ]
            if errors:
                raise ValueError("请先修正其他时刻表错误：" + errors[0]["message"])
        return (
            doc,
            infrastructure,
            token([revision, request.date_base, [v.model_dump() for v in request.changes], doc]),
        )

    def editor_context(self, kind, object_id, request):
        with self.base.database.transaction() as c:
            doc, infrastructure, stamp = self.editor_state(c, kind, object_id, request)
            return repair_context(doc, infrastructure) | {"repair_token": stamp}

    def editor_apply(self, kind, object_id, request):
        with self.base.database.transaction() as c:
            doc, infrastructure, stamp = self.editor_state(c, kind, object_id, request)
            if request.repair_token != stamp:
                raise ImportConflict("修复预览已过期，请重新打开窗口")
            return allocate(doc, infrastructure, request.selections)

    def workbook_state(self, c, job_id):
        original, options, infrastructure, stamp = import_source(c, self.base, job_id)
        structure = inspect_workbook(original, options.get("sheet"))
        if not structure["sheets"]:
            raise ValueError("请先指定时刻表表单")
        book = load_workbook(BytesIO(original))
        missing = []
        try:
            for sheet in structure["sheets"]:
                groups, issues = train_columns(sheet["headers"])
                if any(group["missing_seq"] for group in groups):
                    raise ValueError("请先点击修复SEQ信息补齐_SEQ列，再修复股道信息")
                if sheet["headers"][:5] != [
                    "NODE_NAME_CHN",
                    "NODE_IND",
                    "NODE_CODE",
                    "LINE_IND",
                    "NODE_NAME",
                ] or any(not i.get("field", "").endswith("_G") for i in issues):
                    raise ValueError("除缺少_G以外仍有表头错误，请先修正列名与顺序")
                table = book[sheet["name"]]
                for group in reversed(groups):
                    if group["missing_g"]:
                        table.insert_cols(group["start"] + 2)
                        table.cell(1, group["start"] + 2, group["course"] + "_G")
                        missing.append(group["course"])
            normalized = BytesIO()
            book.save(normalized)
            # Clear only G values in an analysis copy, allowing invalid G values to be repaired.
            for sheet in structure["sheets"]:
                table = book[sheet["name"]]
                for col in range(8, table.max_column + 1, 4):
                    for r in range(2, table.max_row + 1):
                        table.cell(r, col).value = None
            analysis = BytesIO()
            book.save(analysis)
        finally:
            book.close()
        doc = parse_base(
            analysis.getvalue(),
            date.fromisoformat(options["date_base"]),
            options["date_mode"],
            options.get("sheet"),
            track_lists=True,
            result_context=infrastructure,
        )
        errors = [i for i in doc["issues"] if i["severity"] == "error"]
        if errors:
            raise ValueError("请先修正其他导入错误：" + errors[0]["message"])
        source = load_workbook(BytesIO(normalized.getvalue()), read_only=True)
        try:
            values = {
                s.title: list(s.values)
                for s in source
                if s.title in {v["name"] for v in structure["sheets"]}
            }
            for train in doc["trains"]:
                train["id"] = train["train_course_id"]
            for index, event in enumerate(doc["events"]):
                event["id"] = str(index)
                event["train_id"] = event["train_course_id"]
                src = event["source"]
                event["track_code"] = values[src["sheet"]][src["row"] - 1][src["first_column"] + 1]
        finally:
            source.close()
        return (
            original,
            normalized.getvalue(),
            doc,
            infrastructure if infrastructure is not None else doc,
            missing,
            stamp,
            options,
        )

    def workbook_context(self, job_id):
        with self.base.database.transaction() as c:
            _, _, doc, infrastructure, missing, stamp, _ = self.workbook_state(c, job_id)
            return repair_context(doc, infrastructure, missing) | {"repair_token": stamp}

    def workbook_apply(self, job_id, request):
        with self.base.database.transaction() as c:
            original, normalized, doc, infrastructure, _, stamp, options = self.workbook_state(
                c, job_id
            )
            if request.repair_token != stamp:
                raise ImportConflict("源文件或基本图上下文已变化，请重新打开修复窗口")
            result = allocate(doc, infrastructure, request.selections)
            if not result["can_apply"]:
                return result, None
            # Write selected G columns only. Nonselected missing-G groups remain blocking.
            selected = {s.train_id for s in request.selections}
            book = load_workbook(BytesIO(original))
            try:
                structure = inspect_workbook(original, options.get("sheet"))
                for sheet in structure["sheets"]:
                    table = book[sheet["name"]]
                    groups, _ = train_columns(sheet["headers"])
                    for group in reversed(groups):
                        if group["missing_g"] and group["course"] in selected:
                            table.insert_cols(group["start"] + 2)
                            table.cell(1, group["start"] + 2, group["course"] + "_G")
                assigned = {change["event_id"]: change["value"] for change in result["changes"]}
                for event in doc["events"]:
                    if event["id"] not in assigned:
                        continue
                    source = event["source"]
                    table = book[source["sheet"]]
                    headers = [cell.value for cell in table[1]]
                    col = headers.index(event["train_course_id"] + "_G") + 1
                    table.cell(source["row"], col, assigned[event["id"]])
                output = BytesIO()
                book.save(output)
                return result, output.getvalue()
            finally:
                book.close()
