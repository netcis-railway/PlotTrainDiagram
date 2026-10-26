"""Ordinary result imports: TTT only, inherited infrastructure, atomic working-state writes."""

import copy
import json
import shutil
from datetime import date
from typing import Literal
from uuid import uuid4

from app.base_timetables.editing import EditorService
from app.base_timetables.service import Confirmation, token, token_bytes
from app.ingest.base_parser import parse_base
from app.ingest.base_service import ImportConflict, batch_context, encode
from pydantic import BaseModel, ConfigDict, Field


class RunOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: str
    name: str = Field(min_length=1, max_length=200)
    run_no: int | None = Field(default=None, ge=0, le=2147483647)
    date_base: date = date(2026, 1, 1)
    date_mode: Literal["rebase", "preserve"] = "rebase"
    sheet: str | None = None
    write_mode: Literal["create", "replace"] = "create"
    target_run_id: str | None = None


class RunImportService:
    def __init__(self, base):
        self.base = base
        self.database = base.database
        self.editor = EditorService(base)

    def context(self, c, options):
        chain, network, _ = batch_context(c, options["batch_id"])
        effective = self.base.resolve_state(self.base.state(c), options["batch_id"])
        effective["owner_path"] = (
            self.base.category(c, effective["owner_category_id"])
            if effective["owner_category_id"]
            else []
        )
        duplicate = c.execute(
            "SELECT id FROM runs WHERE batch_id=? AND name=? AND run_no=?",
            [options["batch_id"], options["name"], options["run_no"]],
        ).fetchall()
        replacement = None
        if options["write_mode"] == "replace":
            if not options.get("target_run_id"):
                raise ValueError("覆盖必须选择现存的普通run")
            meta, doc, _, revision = self.editor._load(c, "run", options["target_run_id"])
            if (meta["owner_category_id"], meta["name"], meta["run_no"]) != (
                options["batch_id"],
                options["name"],
                options["run_no"],
            ):
                raise ValueError("覆盖必须与原run的所属批次、名称和编号一致")
            replacement = meta | {"revision": revision, "summary": self.base.summarize(doc)}
            if [row[0] for row in duplicate] != [meta["id"]]:
                raise ValueError("同批次同名同编号存在歧义，不能覆盖")
        elif options.get("target_run_id"):
            raise ValueError("新建模式不能指定覆盖目标")
        return {
            "classification_path": list(reversed(chain)),
            "network_id": network,
            "effective_base": effective,
            "duplicate": duplicate[0][0] if duplicate else None,
            "replacement": replacement,
            "preview_token": token([options, chain, effective, duplicate, replacement]),
        }

    def validate(self, c, report, options, context):
        issues = self.base.validate_scope(
            c, report, options["batch_id"], exclude_result=options.get("target_run_id")
        )
        if options["write_mode"] == "create" and context["duplicate"]:
            issues.append(
                {
                    "severity": "error",
                    "field": "run_no",
                    "message": "同批次同名同编号已存在，请修改编号或选择覆盖已有run",
                }
            )
        return issues

    def preview(self, content, filename, options: RunOptions):
        if not options.name.strip() or options.date_base.year < 2020:
            raise ValueError("请输入run名称及2020年以后的基准日")
        if options.write_mode == "replace" and options.run_no is None:
            raise ValueError("覆盖必须明确指定原run编号")
        if len(content) > 32 * 1024 * 1024:
            raise ValueError("文件超过32 MB限制")
        filename = filename.replace("\\", "/").split("/")[-1]
        if not filename.lower().endswith(".xlsx") or len(filename) > 200:
            raise ValueError("请选择XLSX文件，文件名不超过200字符")
        opts = options.model_dump(mode="json") | {"name": options.name.strip(), "role": "result"}
        job_id = str(uuid4())
        with self.database.transaction() as c:
            batch_context(c, options.batch_id)
            if opts["run_no"] is None:
                opts["run_no"] = c.execute(
                    "SELECT coalesce(max(run_no),0)+1 FROM runs WHERE batch_id=?",
                    [options.batch_id],
                ).fetchone()[0]
                if opts["run_no"] > 2147483647:
                    raise ValueError("自动编号超出支持范围")
            context = self.context(c, opts)
            infrastructure = (
                json.loads(self.base._row(c, context["effective_base"]["base_tt_id"])[5])
                if context["effective_base"]["base_tt_id"]
                else {}
            )
            c.execute(
                "INSERT INTO import_jobs(id,filename,digest,state,options) "
                "VALUES (?,?,?,'uploading',?)",
                [job_id, filename, token_bytes(content), encode(opts)],
            )
        try:
            self.base.staging.mkdir(parents=True, exist_ok=True)
            self.base.stage_path(job_id).write_bytes(content)
            report = parse_base(
                content,
                options.date_base,
                options.date_mode,
                options.sheet,
                track_lists=True,
                result_context=infrastructure,
            )
            with self.database.transaction() as c:
                # Infrastructure and the overwrite target must match the snapshot used to parse.
                current = self.context(c, opts)
                if current["preview_token"] != context["preview_token"]:
                    raise ImportConflict("预检期间批次、基本图或目标run已变化，请重新预检")
                report.update(context)
                report["issues"].extend(self.validate(c, report, opts, context))
                if not context["effective_base"]["base_tt_id"]:
                    report["issues"].append(
                        {
                            "severity": "warning",
                            "field": "base_tt_id",
                            "message": (
                                "当前批次未回溯到基本图，可导入TTT，但依赖基础数据的绘图和分析受限"
                            ),
                        }
                    )
                report["options"] = opts
                report["summary"] = self.base.summarize(report)
                c.execute(
                    "UPDATE import_jobs SET state='preview',report=? WHERE id=?",
                    [encode(report), job_id],
                )
            self.base.log_report(job_id, filename, report["issues"])
            return self.job(job_id)
        except Exception as error:
            self.base.stage_path(job_id).unlink(missing_ok=True)
            with self.database.transaction() as c:
                c.execute(
                    "UPDATE import_jobs SET state='failed',error=? WHERE id=?", [str(error), job_id]
                )
            raise

    def job(self, job_id):
        with self.database.transaction() as c:
            row = c.execute(
                "SELECT filename,state,report,run_id,error FROM import_jobs WHERE id=? "
                "AND json_extract_string(options,'$.role')='result'",
                [job_id],
            ).fetchone()
        if not row:
            raise LookupError("普通run导入任务不存在")
        report = json.loads(row[2]) if row[2] else {}
        report["can_commit"] = (
            row[1] == "preview"
            and bool(report)
            and not any(issue["severity"] == "error" for issue in report.get("issues", []))
        )
        return {
            "job_id": job_id,
            "filename": row[0],
            "state": row[1],
            "report": report,
            "run_id": row[3],
            "error": row[4],
        }

    def jobs(self):
        with self.database.transaction() as c:
            return [
                dict(zip(("job_id", "filename", "state", "run_id", "error"), row, strict=True))
                for row in c.execute(
                    "SELECT id,filename,state,run_id,error FROM import_jobs "
                    "WHERE json_extract_string(options,'$.role')='result' "
                    "ORDER BY created_at DESC LIMIT 50"
                ).fetchall()
            ]

    def insert_document(self, c, run_id, network, doc):
        self.base.identify(c, doc)
        for node in doc["nodes"]:
            c.execute(
                "INSERT INTO network_node_maps VALUES (?,?,?) ON CONFLICT DO NOTHING",
                [network, node["node_ind"], node["id"]],
            )
            c.execute("INSERT INTO run_nodes VALUES (?,?,?)", [run_id, node["id"], encode(node)])
        for train in doc["trains"]:
            c.execute(
                "INSERT INTO run_trains VALUES (?,?,?,?,?)",
                [
                    train["id"],
                    run_id,
                    train["train_course_id"],
                    train["train_base_date"],
                    encode(train),
                ],
            )
        names = {node["node_name"]: node["node_name_chn"] for node in doc["nodes"]}
        for event in doc["events"]:
            arrival, departure = event["arrival"] or {}, event["departure"] or {}
            c.execute(
                "INSERT INTO timetable_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    event["id"],
                    run_id,
                    event["train_id"],
                    event["node_id"],
                    event["train_course_id"],
                    event["node_name"],
                    names[event["node_name"]],
                    event["visit_seq"],
                    arrival.get("hms"),
                    arrival.get("seconds"),
                    arrival.get("day_offset"),
                    departure.get("hms"),
                    departure.get("seconds"),
                    departure.get("day_offset"),
                    event["track_code"],
                    encode(event["source"]),
                    encode(event["line_inds"]),
                ],
            )

    def commit(self, job_id, payload: Confirmation):
        with self.database.lock:
            job = self.job(job_id)
            if job["state"] == "committed":
                return self.editor.read("run", job["run_id"])["object"]
            report = job["report"]
            if not report["can_commit"]:
                raise ImportConflict("任务尚未通过预检，不能提交")
            if payload.preview_token != report["preview_token"]:
                raise ImportConflict("预检标识不匹配，请重新预检")
            if (
                any(i["severity"] == "warning" for i in report["issues"])
                and not payload.warnings_confirmed
            ):
                raise ValueError("请阅读并确认预检警告")
            if report["replacement"] and not payload.replace_confirmed:
                raise ValueError("请单独确认覆盖原run时刻表及已有编辑")
            data = self.base.stage_path(job_id).read_bytes()
            with self.database.transaction() as c:
                digest = c.execute(
                    "SELECT digest FROM import_jobs WHERE id=?", [job_id]
                ).fetchone()[0]
                if token_bytes(data) != digest:
                    raise ImportConflict("暂存文件发生变化，请重新预检")
                c.execute("UPDATE import_jobs SET state='prepared' WHERE id=?", [job_id])
            destination = self.base.sources / f"{job_id}.xlsx"
            try:
                self.base.sources.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.base.stage_path(job_id), destination)
                if token_bytes(destination.read_bytes()) != digest:
                    raise ImportConflict("受管源副本校验失败")
                with self.database.transaction() as c:
                    opts = report["options"]
                    try:
                        context = self.context(c, opts)
                    except (ValueError, LookupError) as error:
                        raise ImportConflict("所属批次或覆盖目标已变化，请重新预检") from error
                    if context["preview_token"] != report["preview_token"]:
                        raise ImportConflict("批次、有效基本图或原run已变化，请重新预检")
                    issues = self.validate(c, report, opts, context)
                    if any(i["severity"] == "error" for i in issues):
                        raise ImportConflict(issues[0]["message"])
                    old = context["replacement"]
                    run_id = old["id"] if old else str(uuid4())
                    if old:
                        self.base._clear_run_data(c, run_id)
                        c.execute(
                            "UPDATE import_jobs SET state='superseded' WHERE run_id=? "
                            "AND state='committed'",
                            [run_id],
                        )
                        c.execute(
                            "INSERT INTO run_working_data VALUES (?,?,1) "
                            "ON CONFLICT(run_id) DO UPDATE SET date_base=excluded.date_base,"
                            "revision=run_working_data.revision+1",
                            [run_id, opts["date_base"]],
                        )
                    else:
                        c.execute(
                            "INSERT INTO runs(id,batch_id,name,run_no) VALUES (?,?,?,?)",
                            [run_id, opts["batch_id"], opts["name"], opts["run_no"]],
                        )
                        c.execute(
                            "INSERT INTO run_working_data VALUES (?,?,1)",
                            [run_id, opts["date_base"]],
                        )
                    doc = copy.deepcopy({k: report[k] for k in ("nodes", "trains", "events")})
                    self.insert_document(c, run_id, context["network_id"], doc)
                    c.execute(
                        "INSERT INTO source_files VALUES (?,?,?,?,?,?)",
                        [str(uuid4()), run_id, job_id, job["filename"], digest, destination.name],
                    )
                    c.execute(
                        "UPDATE import_jobs SET state='committed',run_id=?,error=NULL WHERE id=?",
                        [run_id, job_id],
                    )
            except Exception as error:
                destination.unlink(missing_ok=True)
                with self.database.transaction() as c:
                    c.execute(
                        "UPDATE import_jobs SET state='preview',error=? WHERE id=?",
                        [str(error), job_id],
                    )
                raise
            try:
                self.base.stage_path(job_id).unlink(missing_ok=True)
            except OSError:
                pass  # Startup recovery retries cleanup after the durable commit.
            self.base.cleanup_files()
            return self.editor.read("run", run_id)["object"]

    def cancel(self, job_id):
        with self.database.lock:
            if self.job(job_id)["state"] in {"committed", "superseded", "deleted"}:
                raise ImportConflict("已提交或已处理的run任务不能取消")
            self.base.stage_path(job_id).unlink(missing_ok=True)
            with self.database.transaction() as c:
                c.execute("UPDATE import_jobs SET state='cancelled' WHERE id=?", [job_id])
        return {"state": "cancelled"}
