"""Independent basic timetables. Storage ownership is the only binding authority."""

import hashlib
import json
import shutil
from datetime import date
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.ingest.base_parser import parse_base
from app.ingest.base_service import (
    BaseImportService,
    ImportConflict,
    ancestry,
    encode,
    validate_existing,
)
from app.ingest.issues import node_context


def token(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


class Options(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner_category_id: str
    name: str = Field(min_length=1, max_length=200)
    date_base: date = date(2026, 1, 1)
    date_mode: Literal["rebase", "preserve"] = "rebase"
    sheet: str | None = None


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: Literal[True]
    preview_token: str
    date_confirmed: Literal[True]
    train_dates_confirmed: Literal[True]
    warnings_confirmed: bool = False
    replace_confirmed: bool = False


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_category_id: str


class Move(Target):
    confirmed: Literal[True]
    preview_token: str


class Delete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: Literal[True]
    preview_token: str


class TimetableService(BaseImportService):
    def category(self, connection, category_id):
        chain = ancestry(connection, category_id)
        if not chain or chain[0]["kind"] == "run":
            raise ValueError("请选择现存分类，基本图不存放在 run 下")
        return list(reversed(chain))

    def state(self, connection):
        nodes = connection.execute(
            "SELECT id,kind,parent_id,name FROM catalog_nodes ORDER BY id"
        ).fetchall()
        bases = connection.execute(
            "SELECT id,base_tt_no,owner_category_id,name,revision FROM base_timetables ORDER BY id"
        ).fetchall()
        runs = connection.execute(
            "SELECT id,batch_id,name FROM runs WHERE id NOT IN (SELECT run_id "
            "FROM base_run_data WHERE role='base') ORDER BY id"
        ).fetchall()
        return {"nodes": nodes, "bases": bases, "runs": runs}

    def resolve_state(self, state, category_id):
        nodes = {n[0]: n for n in state["nodes"]}
        local = {b[2]: b for b in state["bases"]}
        current, seen = category_id, set()
        while current and current in nodes:
            if current in seen:
                raise ValueError("分类关系存在循环")
            seen.add(current)
            if current in local:
                b = local[current]
                return {
                    "base_tt_id": b[0],
                    "baseTT_no": b[1],
                    "owner_category_id": current,
                    "name": b[3],
                    "revision": b[4],
                    "mode": "physical" if current == category_id else "inherited",
                }
            current = nodes[current][2]
        return {"mode": "missing", "base_tt_id": None, "owner_category_id": None}

    def resolution(self, category_id):
        with self.database.transaction() as c:
            self.category(c, category_id)
            state = self.state(c)
            effective = self.resolve_state(state, category_id)
            effective["owner_path"] = (
                self.category(c, effective["owner_category_id"])
                if effective["owner_category_id"]
                else []
            )
            return {
                "requested_category_id": category_id,
                "effective": effective,
                "local_base": effective if effective["mode"] == "physical" else None,
            }

    def impact(self, before, after):
        result = []
        for kind, items in (
            ("category", [(n[0], n[0], n[3]) for n in before["nodes"]]),
            ("run", before["runs"]),
        ):
            for object_id, category_id, name in items:
                old = self.resolve_state(before, category_id)
                new = self.resolve_state(after, category_id)
                if old != new:
                    result.append(
                        {"kind": kind, "id": object_id, "name": name, "before": old, "after": new}
                    )
        return result

    def _row(self, c, base_id):
        row = c.execute(
            "SELECT "
            "id,base_tt_no,owner_category_id,name,date_base,document,revision "
            "FROM base_timetables WHERE id=?",
            [base_id],
        ).fetchone()
        if not row:
            raise LookupError("基本图不存在")
        return row

    def _detail(self, c, row):
        doc = json.loads(row[5])
        return {
            "id": row[0],
            "base_tt_id": row[0],
            "baseTT_no": row[1],
            "object_type": "base",
            "owner_category_id": row[2],
            "name": row[3],
            "date_base": str(row[4]),
            "revision": row[6],
            "classification_path": self.category(c, row[2]),
            "summary": self.summarize(doc),
            "metadata": {"issues": doc.get("issues", [])},
            "source_files": [
                {
                    "id": r[0],
                    "filename": r[1],
                    "digest": r[2],
                    "managed_path": str((self.sources / r[3]).resolve()),
                }
                for r in c.execute(
                    "SELECT id,filename,digest,managed_name FROM base_tt_sources "
                    "WHERE base_tt_id=?",
                    [row[0]],
                ).fetchall()
            ],
        }

    def detail(self, base_id):
        with self.database.transaction() as c:
            return self._detail(c, self._row(c, base_id))

    def list_bases(self):
        with self.database.transaction() as c:
            return [
                self._detail(c, row)
                for row in c.execute(
                    "SELECT "
                    "id,base_tt_no,owner_category_id,name,date_base,document,revision "
                    "FROM base_timetables ORDER BY name,id"
                ).fetchall()
            ]

    def scope_networks(self, c, owner):
        path = self.category(c, owner)
        network = next((n["id"] for n in path if n["kind"] == "network"), None)
        if network:
            return [network]
        return [
            r[0]
            for r in c.execute(
                "SELECT id FROM catalog_nodes WHERE kind='network' AND parent_id=?", [owner]
            ).fetchall()
        ] or [None]

    def validate_scope(
        self, c, doc, owner, exclude_legacy=None, exclude_base=None, exclude_result=None
    ):
        issues = []
        networks = self.scope_networks(c, owner)
        for network in networks:
            issues.extend(validate_existing(c, doc, network, exclude_legacy))
        # Dataset-local indices must remain compatible within shared networks.
        candidates = {t["train_course_id"]: str(t["train_base_date"]) for t in doc["trains"]}
        for base_id, other_owner, data in c.execute(
            "SELECT id,owner_category_id,document FROM base_timetables ORDER BY id"
        ).fetchall():
            if base_id == exclude_base or not (
                set(networks) & set(self.scope_networks(c, other_owner)) - {None}
            ):
                continue
            other = json.loads(data)
            old_nodes = {n["node_ind"]: n["node_name"] for n in other["nodes"]}
            old_indices = {n["node_name"]: n["node_ind"] for n in other["nodes"]}
            for node in doc["nodes"]:
                if (
                    old_nodes.get(node["node_ind"], node["node_name"]) == node["node_name"]
                    and old_indices.get(node["node_name"], node["node_ind"]) == node["node_ind"]
                ):
                    continue
                issues.append(
                    {
                        "severity": "error",
                        "field": "NODE_IND",
                        **node.get("source", {}),
                        **node_context(node),
                        "message": "与同路网基本图节点索引冲突",
                    }
                )
            old_lines = {int(line["LINE_IND"]): line["LINE_CODE"] for line in other["lines"]}
            old_codes = {line["LINE_CODE"]: int(line["LINE_IND"]) for line in other["lines"]}
            if any(
                old_lines.get(int(line["LINE_IND"]), line["LINE_CODE"]) != line["LINE_CODE"]
                or old_codes.get(line["LINE_CODE"], int(line["LINE_IND"])) != int(line["LINE_IND"])
                for line in doc["lines"]
            ):
                issues.append(
                    {
                        "severity": "error",
                        "field": "LINE_IND",
                        "message": "与同路网基本图线路索引冲突",
                    }
                )
            dates = {t["train_course_id"]: str(t["train_base_date"]) for t in other["trains"]}
            seqs = {(e["train_course_id"], e["node_name"]): e["visit_seq"] for e in other["events"]}
            reverse = {
                (e["train_course_id"], e["visit_seq"]): e["node_name"] for e in other["events"]
            }
            for e in doc["events"]:
                course = e["train_course_id"]
                if (
                    course in candidates
                    and dates.get(course) == candidates[course]
                    and (
                        seqs.get((course, e["node_name"]), e["visit_seq"]) != e["visit_seq"]
                        or reverse.get((course, e["visit_seq"]), e["node_name"]) != e["node_name"]
                    )
                ):
                    issues.append(
                        {
                            "severity": "error",
                            "field": "SEQ",
                            "event_id": e.get("id"),
                            "message": "与同路网同车次同基准日基本图 SEQ 冲突",
                        }
                    )
        issues.extend(self.result_sequence_issues(c, doc, networks, exclude_result))
        return issues

    def result_sequence_issues(self, c, doc, networks, exclude_run=None):
        """Keep ordinary result instances in global SEQ checks after BaseTT separation."""
        dates = {t["train_course_id"]: str(t["train_base_date"]) for t in doc["trains"]}
        issues = []
        for run_id, batch in c.execute(
            "SELECT id,batch_id FROM runs WHERE id NOT IN "
            "(SELECT run_id FROM base_run_data WHERE role='base')"
        ).fetchall():
            if run_id == exclude_run or batch is None:
                continue
            path = self.category(c, batch)
            network = next((n["id"] for n in path if n["kind"] == "network"), None)
            if network not in networks:
                continue
            rows = c.execute(
                "SELECT t.train_course_id,t.train_base_date,e.node_name,e.visit_seq "
                "FROM timetable_events e JOIN run_trains t ON t.id=e.train_id "
                "WHERE e.run_id=?",
                [run_id],
            ).fetchall()
            for event in doc["events"]:
                for course, day, node, seq in rows:
                    if (
                        course == event["train_course_id"]
                        and str(day) == dates.get(course)
                        and (
                            (node == event["node_name"] and seq != event["visit_seq"])
                            or (seq == event["visit_seq"] and node != event["node_name"])
                        )
                    ):
                        issues.append(
                            {
                                "severity": "error",
                                "field": "SEQ",
                                "event_id": event.get("id"),
                                "message": "与同路网普通 run 的同车次同基准日 SEQ 冲突",
                            }
                        )
                        break
        return issues

    def _preview_context(self, c, owner, name):
        self.category(c, owner)
        state = self.state(c)
        old = next((b for b in state["bases"] if b[2] == owner), None)
        changed = dict(state)
        changed["bases"] = [b for b in state["bases"] if b[2] != owner] + [
            (
                old[0] if old else "new",
                old[1] if old else "待分配",
                owner,
                name,
                old[4] + 1 if old else 1,
            )
        ]
        return {
            "preview_token": token(state),
            "replacement": self._detail(c, self._row(c, old[0])) if old else None,
            "effective_before": self.resolve_state(state, owner),
            "impact": self.impact(state, changed),
        }

    def preview(self, content, filename, options: Options):
        if not options.name.strip() or options.date_base.year < 2020:
            raise ValueError("请输入基本图名称及2020年以后的基准日")
        filename = filename.replace("\\", "/").split("/")[-1]
        if not filename.lower().endswith(".xlsx") or len(filename) > 200:
            raise ValueError("请选择 XLSX 文件，文件名不超过200字符")
        job_id = str(uuid4())
        opts = options.model_dump(mode="json") | {"name": options.name.strip()}
        with self.database.transaction() as c:
            self.category(c, options.owner_category_id)
            c.execute(
                "INSERT INTO base_tt_jobs(id,filename,digest,state,options) "
                "VALUES (?,?,?,'uploading',?)",
                [job_id, filename, token_bytes(content), encode(opts)],
            )
        try:
            self.staging.mkdir(parents=True, exist_ok=True)
            self.stage_path(job_id).write_bytes(content)
            report = parse_base(
                content, options.date_base, options.date_mode, options.sheet, track_lists=True
            )
            with self.database.transaction() as c:
                context = self._preview_context(c, options.owner_category_id, opts["name"])
                report.update(context)
                report["issues"].extend(
                    self.validate_scope(
                        c,
                        report,
                        options.owner_category_id,
                        exclude_base=context["replacement"]["id"]
                        if context["replacement"]
                        else None,
                    )
                )
                report["options"] = opts
                report["summary"] = self.summarize(report)
                c.execute(
                    "UPDATE base_tt_jobs SET state='preview',report=? WHERE id=?",
                    [encode(report), job_id],
                )
            self.log_report(job_id, filename, report["issues"])
            return self.job(job_id)
        except Exception as error:
            self.stage_path(job_id).unlink(missing_ok=True)
            with self.database.transaction() as c:
                c.execute(
                    "UPDATE base_tt_jobs SET state='failed',error=? WHERE id=?",
                    [str(error), job_id],
                )
            raise

    def job(self, job_id):
        with self.database.transaction() as c:
            row = c.execute(
                "SELECT filename,state,report,base_tt_id,error FROM base_tt_jobs WHERE id=?",
                [job_id],
            ).fetchone()
        if not row:
            raise LookupError("独立基本图导入任务不存在")
        report = json.loads(row[2]) if row[2] else {}
        if row[1] == "preview" and report and report.get("tracks_schema_version") != 2:
            report.setdefault("issues", []).append(
                {
                    "severity": "error",
                    "field": "tracks_format",
                    "message": (
                        "股道格式规范已更新，请重新上传并预检；"
                        "无正线用[到发线]，有正线用[到发线]/正线号"
                    ),
                    "sheet": "",
                    "row": None,
                    "value": None,
                }
            )
        report["can_commit"] = (
            row[1] == "preview"
            and bool(report)
            and not any(i["severity"] == "error" for i in report.get("issues", []))
        )
        return dict(
            zip(
                ("filename", "state", "report", "base_tt_id", "error"),
                (row[0], row[1], report, row[3], row[4]),
                strict=True,
            ),
            job_id=job_id,
        )

    def jobs(self):
        with self.database.transaction() as c:
            return [
                dict(zip(("job_id", "filename", "state", "base_tt_id", "error"), r, strict=True))
                for r in c.execute(
                    "SELECT id,filename,state,base_tt_id,error FROM base_tt_jobs "
                    "ORDER BY created_at DESC LIMIT 50"
                ).fetchall()
            ]

    def identify(self, c, doc):
        ids = {}
        for n in doc["nodes"]:
            row = c.execute("SELECT id FROM nodes WHERE node_name=?", [n["node_name"]]).fetchone()
            node_id = row[0] if row else str(uuid4())
            if not row:
                c.execute(
                    "INSERT INTO nodes VALUES (?,?,?,?)",
                    [node_id, n["node_name"], n["node_name_chn"], n["node_code"]],
                )
            n["id"] = node_id
            ids[n["node_name"]] = node_id
        trains = {}
        for train in doc["trains"]:
            train.setdefault("id", str(uuid4()))
            trains[train["train_course_id"]] = train["id"]
        for e in doc["events"]:
            e.setdefault("id", str(uuid4()))
            e["node_id"] = ids[e["node_name"]]
            e["train_id"] = trains[e["train_course_id"]]

    def commit(self, job_id, payload: Confirmation):
        with self.database.lock:
            job = self.job(job_id)
            if job["state"] == "committed":
                return self.detail(job["base_tt_id"])
            report = job["report"]
            if not report["can_commit"]:
                raise ImportConflict("存在阻断问题或任务状态不可提交，请重新预检")
            if payload.preview_token != report["preview_token"]:
                raise ImportConflict("确认与预检不一致")
            if (
                any(i["severity"] == "warning" for i in report["issues"])
                and not payload.warnings_confirmed
            ):
                raise ValueError("请确认预检警告")
            if report["replacement"] and not payload.replace_confirmed:
                raise ValueError("请单独确认覆盖本类别已存储的基本图")
            data = self.stage_path(job_id).read_bytes()
            with self.database.transaction() as c:
                digest = c.execute(
                    "SELECT digest FROM base_tt_jobs WHERE id=?", [job_id]
                ).fetchone()[0]
                if token_bytes(data) != digest:
                    raise ImportConflict("暂存文件发生变化，请重新预检")
                c.execute("UPDATE base_tt_jobs SET state='prepared' WHERE id=?", [job_id])
            destination = self.sources / f"{job_id}.xlsx"
            try:
                self.sources.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.stage_path(job_id), destination)
                if token_bytes(destination.read_bytes()) != digest:
                    raise ImportConflict("源文件副本校验失败")
                with self.database.transaction() as c:
                    if token(self.state(c)) != report["preview_token"]:
                        raise ImportConflict("类别、基本图占用或影响范围已变化，请重新预检")
                    opts = report["options"]
                    old = report["replacement"]
                    base_id = old["id"] if old else str(uuid4())
                    issues = self.validate_scope(
                        c, report, opts["owner_category_id"], exclude_base=base_id
                    )
                    if issues:
                        raise ImportConflict(issues[0]["message"])
                    doc = {
                        k: report[k]
                        for k in (
                            "nodes",
                            "trains",
                            "events",
                            "lines",
                            "members",
                            "minimum_run_times",
                            "issues",
                        )
                    }
                    self.identify(c, doc)
                    if old:
                        for (managed,) in c.execute(
                            "SELECT managed_name FROM base_tt_sources WHERE base_tt_id=?", [base_id]
                        ).fetchall():
                            c.execute(
                                "INSERT INTO file_cleanup VALUES (?,NULL) ON CONFLICT DO NOTHING",
                                [managed],
                            )
                        c.execute("DELETE FROM base_tt_sources WHERE base_tt_id=?", [base_id])
                        c.execute(
                            "UPDATE base_tt_jobs SET state='superseded' WHERE base_tt_id=? "
                            "AND state='committed'",
                            [base_id],
                        )
                        c.execute(
                            "UPDATE base_timetables SET "
                            "name=?,date_base=?,document=?,revision=revision+1 WHERE id=?",
                            [opts["name"], opts["date_base"], encode(doc), base_id],
                        )
                    else:
                        c.execute(
                            "INSERT INTO base_timetables VALUES (?,?,?,?,?,?,1)",
                            [
                                base_id,
                                "BTT-" + uuid4().hex,
                                opts["owner_category_id"],
                                opts["name"],
                                opts["date_base"],
                                encode(doc),
                            ],
                        )
                    c.execute(
                        "INSERT INTO base_tt_sources VALUES (?,?,?,?,?,?)",
                        [str(uuid4()), base_id, job_id, job["filename"], digest, destination.name],
                    )
                    c.execute(
                        "UPDATE base_tt_jobs SET "
                        "state='committed',base_tt_id=?,error=NULL WHERE id=?",
                        [base_id, job_id],
                    )
            except Exception as error:
                destination.unlink(missing_ok=True)
                with self.database.transaction() as c:
                    c.execute(
                        "UPDATE base_tt_jobs SET state='preview',error=? WHERE id=?",
                        [str(error), job_id],
                    )
                raise
            try:
                self.stage_path(job_id).unlink(missing_ok=True)
            except OSError:
                pass  # recover() retries; the committed source is already durable.
            self.cleanup_files()
            return self.detail(base_id)

    def cancel(self, job_id):
        with self.database.lock:
            if self.job(job_id)["state"] in {"committed", "superseded", "deleted"}:
                raise ImportConflict("已提交任务不能取消")
            self.stage_path(job_id).unlink(missing_ok=True)
            with self.database.transaction() as c:
                c.execute("UPDATE base_tt_jobs SET state='cancelled' WHERE id=?", [job_id])
        return {"state": "cancelled"}

    def recover(self):
        super().recover()
        with self.database.transaction() as c:
            for job_id, state in c.execute(
                "SELECT id,state FROM base_tt_jobs WHERE state IN "
                "('uploading','prepared','committed')"
            ).fetchall():
                if state != "committed":
                    (self.sources / f"{job_id}.xlsx").unlink(missing_ok=True)
                    c.execute(
                        "UPDATE base_tt_jobs SET "
                        "state='failed',error='导入中断，原基本图未改变，请重新预检' WHERE id=?",
                        [job_id],
                    )
                self.stage_path(job_id).unlink(missing_ok=True)
        self.cleanup_files()

    def move_preview(self, base_id, target):
        with self.database.transaction() as c:
            row = self._row(c, base_id)
            self.category(c, target)
            state = self.state(c)
            after = dict(state)
            after["bases"] = [
                (b[0], b[1], target, b[3], b[4] + 1) if b[0] == base_id else b
                for b in state["bases"]
            ]
            occupied = next(
                (b[0] for b in state["bases"] if b[2] == target and b[0] != base_id), None
            )
            issues = self.validate_scope(c, json.loads(row[5]), target, exclude_base=base_id)
            return {
                "preview_token": token([state, base_id, target]),
                "target_category_id": target,
                "source_path": self.category(c, row[2]),
                "target_path": self.category(c, target),
                "impact": self.impact(state, after),
                "issues": issues,
                "occupied_base_id": occupied,
                "can_move": not occupied and not issues and target != row[2],
            }

    def move(self, base_id, payload: Move):
        with self.database.lock:
            preview = self.move_preview(base_id, payload.target_category_id)
            if preview["preview_token"] != payload.preview_token:
                raise ImportConflict("移动影响已变化，请重新预览")
            if not preview["can_move"]:
                raise ValueError("目标已占用、与当前位置相同或索引不兼容，不能移动")
            with self.database.transaction() as c:
                c.execute(
                    "UPDATE base_timetables SET owner_category_id=?,revision=revision+1 WHERE id=?",
                    [payload.target_category_id, base_id],
                )
        return self.detail(base_id)

    def deletion_preview(self, base_id):
        with self.database.transaction() as c:
            self._row(c, base_id)
            state = self.state(c)
            after = dict(state)
            after["bases"] = [b for b in state["bases"] if b[0] != base_id]
            impact = self.impact(state, after)
            dependents = [
                r for r in impact if r["kind"] == "run" or r["before"]["mode"] == "inherited"
            ]
            return {
                "preview_token": token([state, base_id]),
                "impact": impact,
                "can_delete": not dependents,
                "blocking_dependencies": dependents,
            }

    def delete(self, base_id, payload: Delete):
        with self.database.lock:
            preview = self.deletion_preview(base_id)
            if preview["preview_token"] != payload.preview_token:
                raise ImportConflict("删除影响已变化，请重新预览")
            if not preview["can_delete"]:
                raise ValueError("基本图仍被下级类别或 run 使用，请先处理依赖或移动位置")
            with self.database.transaction() as c:
                for (name,) in c.execute(
                    "SELECT managed_name FROM base_tt_sources WHERE base_tt_id=?", [base_id]
                ).fetchall():
                    c.execute(
                        "INSERT INTO file_cleanup VALUES (?,NULL) ON CONFLICT DO NOTHING", [name]
                    )
                c.execute("DELETE FROM base_tt_sources WHERE base_tt_id=?", [base_id])
                c.execute("DELETE FROM base_timetables WHERE id=?", [base_id])
                c.execute("UPDATE base_tt_jobs SET state='deleted' WHERE base_tt_id=?", [base_id])
            self.cleanup_files()
        return {"deleted_base_tt_id": base_id}


def token_bytes(data):
    return hashlib.sha256(data).hexdigest()
