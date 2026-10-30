"""One editor contract, separate owners, full-state validation and atomic saves."""

import copy
import json
from datetime import date, datetime, time, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.base_timetables.ordering import editor_order, route_nodes
from app.base_timetables.service import token
from app.base_timetables.workbooks import book_bytes, materialize, working_copy_write
from app.ingest.base_parser import event_time, integer
from app.ingest.base_service import ImportConflict, ancestry, encode
from app.ingest.sequences import sequence_problem
from app.ingest.tracks import check_event_track, invalid_track_message


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str
    field: Literal["arrival", "departure", "track_code", "visit_seq"]
    value: str | int | None


class EditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str
    changes: list[Change] = Field(default_factory=list, max_length=100000)
    date_base: date | None = None


class SaveRequest(EditRequest):
    validation_token: str
    warnings_confirmed: bool = False
    train_dates_confirmed: bool = False
    date_base_confirmed: bool = False


class EditorService:
    def __init__(self, base):
        self.base = base
        self.database = base.database

    def _load(self, c, kind, object_id):
        if kind == "base":
            row = self.base._row(c, object_id)
            meta = self.base._detail(c, row)
            meta.pop("working_file", None)  # Exporting a backup does not revise timetable data.
            doc = json.loads(row[5])
            infrastructure = doc
        else:
            row = c.execute(
                "SELECT r.id,r.batch_id,r.name,r.run_no,w.date_base,w.revision "
                "FROM runs r LEFT JOIN run_working_data w ON w.run_id=r.id WHERE "
                "r.id=? AND r.id NOT IN (SELECT run_id FROM base_run_data WHERE "
                "role='base')",
                [object_id],
            ).fetchone()
            if not row:
                raise LookupError("普通 run 不存在；旧基本图请通过迁移入口处理")
            path = self.base.category(c, row[1]) if row[1] else []
            meta = {
                "id": row[0],
                "name": row[2],
                "run_no": row[3],
                "owner_category_id": row[1],
                "date_base": str(row[4]) if row[4] else None,
                "classification_path": path,
                "object_type": "run",
                "revision": row[5] or 0,
            }
            state = self.base.state(c)
            effective = self.base.resolve_state(state, row[1])
            meta["effective_base"] = effective
            infrastructure = (
                json.loads(self.base._row(c, effective["base_tt_id"])[5])
                if effective["base_tt_id"]
                else {"members": []}
            )
            doc = {
                "nodes": [],
                "trains": [],
                "events": [],
                "lines": [],
                "members": [],
                "minimum_run_times": [],
            }
            for tid, course, day, data in c.execute(
                "SELECT id,train_course_id,train_base_date,data FROM run_trains "
                "WHERE run_id=? ORDER BY id",
                [object_id],
            ).fetchall():
                doc["trains"].append(
                    json.loads(data)
                    | {"id": tid, "train_course_id": course, "train_base_date": str(day)}
                )
            cursor = c.execute(
                "SELECT * FROM timetable_events WHERE run_id=? ORDER BY train_course_id,visit_seq",
                [object_id],
            )
            names = [d[0] for d in cursor.description]
            for r in cursor.fetchall():
                e = dict(zip(names, r, strict=True))
                item = {
                    k: e[k]
                    for k in (
                        "id",
                        "train_id",
                        "node_id",
                        "node_name",
                        "train_course_id",
                        "visit_seq",
                        "track_code",
                    )
                }
                item["source"] = json.loads(e["source"])
                item["line_inds"] = json.loads(e["line_inds"])
                for prefix in ("arrival", "departure"):
                    item[prefix] = (
                        None
                        if e[prefix + "_seconds"] is None
                        else {
                            "seconds": e[prefix + "_seconds"],
                            "hms": e[prefix + "_hms"],
                            "day_offset": e[prefix + "_day_offset"],
                        }
                    )
                doc["events"].append(item)
                if not any(n["id"] == e["node_id"] for n in doc["nodes"]):
                    doc["nodes"].append(
                        {
                            "id": e["node_id"],
                            "node_name": e["node_name"],
                            "node_name_chn": e["node_name_chn"],
                        }
                    )
        revision = token([meta, doc, self.base.state(c), infrastructure.get("members", [])])
        return meta, doc, infrastructure, revision

    def read(self, kind, object_id):
        with self.database.transaction() as c:
            meta, doc, infrastructure, revision = self._load(c, kind, object_id)
            display_nodes, original_order = editor_order(
                c, self.base, kind, object_id, doc, infrastructure
            )
            route = route_nodes(display_nodes, infrastructure)
            sequences = {n["node_name"]: n["line_seqs"] for n in route}
            for node in display_nodes:
                node["line_seqs"] = sequences.get(node["node_name"], {})
            public_events = copy.deepcopy(doc["events"])
            if meta["date_base"]:
                start = datetime.combine(date.fromisoformat(meta["date_base"]), time())
                for event in public_events:
                    for field in ("arrival", "departure"):
                        event[field + "_datetime"] = (
                            (start + timedelta(seconds=event[field]["seconds"])).isoformat()
                            if event[field]
                            else None
                        )
            return {
                "object": meta,
                "revision": revision,
                "nodes": display_nodes,
                "route_nodes": route,
                "display_lines": [
                    {
                        "line_ind": line["LINE_IND"],
                        "line_code": line["LINE_CODE"],
                        "line_name_chn": line["LINE_NAME_CHN"],
                    }
                    for line in infrastructure.get("lines", [])
                ],
                "original_order": original_order,
                "trains": doc["trains"],
                "events": public_events,
                "infrastructure": {k: doc[k] for k in ("lines", "members", "minimum_run_times")},
            }

    def _validate(self, c, kind, object_id, request):
        meta, original, infra, revision = self._load(c, kind, object_id)
        if revision != request.revision:
            raise ImportConflict("数据、归属或基本图上下文已变化，请重新加载后校验")
        if not meta["date_base"]:
            raise ValueError("当前 run 尚无正式时刻数据和基准日期")
        old_day = date.fromisoformat(meta["date_base"])
        day = request.date_base or old_day
        if day.year < 2020:
            raise ValueError("运行基准日须为2020年以后的日期")
        if not request.changes and day == old_day:
            raise ValueError("没有待保存的日期或时刻修改")
        doc = copy.deepcopy(original)
        by_id = {e["id"]: e for e in doc["events"]}
        issues, seen = [], set()

        def issue(message, event_id=None, field="", severity="error"):
            issues.append(
                {"severity": severity, "message": message, "event_id": event_id, "field": field}
            )

        for change in request.changes:
            key = (change.event_id, change.field)
            if key in seen:
                issue("同一单元格重复提交", *key)
                continue
            seen.add(key)
            event = by_id.get(change.event_id)
            if event is None:
                issue("事件不属于当前对象，不能新增不经过车站的访问", *key)
                continue
            try:
                value = change.value
                if change.field in ("arrival", "departure"):
                    if isinstance(value, str) and ("T" in value or " " in value.strip()):
                        value = datetime.fromisoformat(value)
                        if value.tzinfo is not None:
                            raise ValueError("使用不带时区的运行日期时刻")
                    event[change.field] = event_time(value, day, day, "preserve")
                else:
                    event[change.field] = (
                        None
                        if change.field == "track_code" and value in (None, "")
                        else integer(value)
                    )
            except (ValueError, TypeError, OverflowError) as error:
                issue(str(error), *key)
        date_changes = []
        for train in doc["trains"]:
            visits = sorted(
                (e for e in doc["events"] if e["train_id"] == train["id"]),
                key=lambda e: e["visit_seq"],
            )
            if not visits:
                continue
            problem = sequence_problem([e["visit_seq"] for e in visits])
            if problem:
                message, index = problem
                issue(message, visits[index]["id"], "visit_seq")
            departure = next((e for e in visits if e["departure"] is not None), None)
            if departure is None:
                issue("全部缺少发车时刻，不能确定列车基准日", visits[0]["id"], "departure")
            else:
                try:
                    new_date = str(day + timedelta(days=departure["departure"]["day_offset"]))
                except OverflowError:
                    issue("列车基准日超出支持的日期范围", departure["id"], "departure")
                    new_date = str(train["train_base_date"])
                if new_date != str(train["train_base_date"]):
                    date_changes.append(
                        {
                            "train_course_id": train["train_course_id"],
                            "before": str(train["train_base_date"]),
                            "after": new_date,
                        }
                    )
                train["train_base_date"] = new_date
                train["adopted_seq"] = departure["visit_seq"]
                train["departure"] = departure["departure"]
                train["source"] = departure["source"]
                train["fallback"] = departure is not visits[0]
                if train["fallback"]:
                    issue(
                        "首条访问缺发车，列车基准日按有发车的最小SEQ确定，请核验",
                        departure["id"],
                        "departure",
                        "warning",
                    )
            for index, e in enumerate(visits):
                for field in ("arrival", "departure"):
                    if e[field]:
                        try:
                            datetime.combine(day, time()) + timedelta(seconds=e[field]["seconds"])
                        except OverflowError:
                            issue("到发日期超出支持的日期范围", e["id"], field)
                if (index > 0 and e["arrival"] is None) or (
                    index < len(visits) - 1 and e["departure"] is None
                ):
                    issue("到发时刻缺失，相关点和线段不能完整绘制", e["id"], "arrival", "warning")
                if e["track_code"] is not None:
                    state, allowed, station_lines = check_event_track(
                        infra.get("members", []), e["node_name"], e["track_code"]
                    )
                    if state == "invalid":
                        issue(
                            invalid_track_message(e["track_code"], station_lines, allowed),
                            e["id"],
                            "track_code",
                        )
                    elif state == "unknown":
                        changed = (e["id"], "track_code") in seen
                        issue(
                            "本站所属线路的股道资料不完整，无法完整核对该编号，请核验基本图",
                            e["id"],
                            "track_code",
                            "error" if changed else "warning",
                        )
        if kind == "base":
            issues.extend(
                self.base.validate_scope(c, doc, meta["owner_category_id"], exclude_base=object_id)
            )
        else:
            path = ancestry(c, object_id)
            network = next((n["id"] for n in path if n["kind"] == "network"), None)
            dates = {t["train_course_id"]: t["train_base_date"] for t in doc["trains"]}
            for _, owner, content in c.execute(
                "SELECT id,owner_category_id,document FROM base_timetables"
            ).fetchall():
                if network not in self.base.scope_networks(c, owner):
                    continue
                other = json.loads(content)
                old_dates = {t["train_course_id"]: t["train_base_date"] for t in other["trains"]}
                for e in doc["events"]:
                    if old_dates.get(e["train_course_id"]) != dates[e["train_course_id"]]:
                        continue
                    if any(
                        o["train_course_id"] == e["train_course_id"]
                        and (
                            (o["node_name"] == e["node_name"] and o["visit_seq"] != e["visit_seq"])
                            or (
                                o["visit_seq"] == e["visit_seq"]
                                and o["node_name"] != e["node_name"]
                            )
                        )
                        for o in other["events"]
                    ):
                        issue("与有效路网基本图全局 SEQ 冲突", e["id"], "visit_seq")
        if kind == "run":
            issues.extend(self.base.result_sequence_issues(c, doc, [network], object_id))
        result = {
            "can_save": not any(i["severity"] == "error" for i in issues),
            "issues": issues,
            "train_date_changes": date_changes,
            "date_base_change": {"before": str(old_day), "after": str(day)}
            if day != old_day
            else None,
            "validation_token": token(
                [revision, str(day), [v.model_dump() for v in request.changes], doc]
            ),
            "change_count": len(seen),
        }
        return result, doc

    def validate(self, kind, object_id, request):
        with self.database.transaction() as c:
            return self._validate(c, kind, object_id, request)[0]

    def save(self, kind, object_id, request):
        with working_copy_write(self.base) as writer, self.database.transaction() as c:
            result, doc = self._validate(c, kind, object_id, request)
            if request.validation_token != result["validation_token"]:
                raise ImportConflict("校验结果已过期，请对当前修改重新校验")
            if not result["can_save"]:
                raise ValueError("校验存在阻断错误，不能保存")
            if (
                any(i["severity"] == "warning" for i in result["issues"])
                and not request.warnings_confirmed
            ):
                raise ValueError("请核对并确认警告")
            if result["train_date_changes"] and not request.train_dates_confirmed:
                raise ValueError("请确认列车基准日变化")
            if result["date_base_change"] and not request.date_base_confirmed:
                raise ValueError("请确认运行基准日修改及全部到发日期更新")
            saved_day = request.date_base or self._load(c, kind, object_id)[0]["date_base"]
            if kind == "base":
                if c.execute(
                    "SELECT 1 FROM base_tt_sources WHERE base_tt_id=?", [object_id]
                ).fetchone():
                    book, _ = materialize(self.base, c, object_id, doc, saved_day)
                    try:
                        writer.save(c, object_id, book_bytes(book))
                    finally:
                        book.close()
                c.execute(
                    "UPDATE base_timetables SET document=?,date_base=?,"
                    "revision=revision+1 WHERE id=?",
                    [encode(doc), saved_day, object_id],
                )
            else:
                # Stage SEQ swaps while retaining event identities and untouched values.
                c.execute(
                    "UPDATE timetable_events SET visit_seq=-visit_seq WHERE run_id=?", [object_id]
                )
                for e in doc["events"]:
                    a, d = e["arrival"] or {}, e["departure"] or {}
                    c.execute(
                        "UPDATE timetable_events SET "
                        "visit_seq=?,track_code=?,arrival_hms=?,arrival_seconds=?,arrival_day_offset=?,"
                        "departure_hms=?,departure_seconds=?,departure_day_offset=? "
                        "WHERE id=? AND run_id=?",
                        [
                            e["visit_seq"],
                            e["track_code"],
                            a.get("hms"),
                            a.get("seconds"),
                            a.get("day_offset"),
                            d.get("hms"),
                            d.get("seconds"),
                            d.get("day_offset"),
                            e["id"],
                            object_id,
                        ],
                    )
                for t in doc["trains"]:
                    c.execute(
                        "UPDATE run_trains SET train_base_date=?,data=? WHERE id=? AND run_id=?",
                        [t["train_base_date"], encode(t), t["id"], object_id],
                    )
                c.execute(
                    "UPDATE run_working_data SET date_base=?,revision=revision+1 WHERE run_id=?",
                    [saved_day, object_id],
                )
        return self.read(kind, object_id)
