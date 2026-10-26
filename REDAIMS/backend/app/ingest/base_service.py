import hashlib
import json
import logging
import shutil
from datetime import date
from typing import Literal
from uuid import uuid4

from app.core.config import Settings
from app.ingest.base_parser import parse_base
from app.ingest.issues import node_context
from app.storage.database import Database
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("redams.ingest")


def encode(value):
    return json.dumps(value, ensure_ascii=False, default=str)


class ImportOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: str
    name: str = Field(min_length=1, max_length=200)
    run_no: int | None = Field(default=0, ge=0)
    date_base: date = date(2026, 1, 1)
    date_mode: Literal["rebase", "preserve"] = "rebase"
    sheet: str | None = None
    write_mode: Literal["create", "replace"] = "create"


class CommitImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: Literal[True]
    date_confirmed: Literal[True]
    train_dates_confirmed: Literal[True]
    warnings_confirmed: bool = False
    bind_scope_id: str | None = None
    binding_token: str | None = None
    replace_confirmed: bool = False
    replace_token: str | None = None


class BindingChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_run_id: str | None
    confirmed: Literal[True]
    preview_token: str


class BaseDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: Literal[True]
    preview_token: str


class ImportConflict(Exception):
    pass


def ancestry(connection, scope_id):
    result = []
    run = connection.execute("SELECT batch_id FROM runs WHERE id=?", [scope_id]).fetchone()
    if run:
        result.append({"id": scope_id, "kind": "run"})
        scope_id = run[0]
    visited = set()
    while scope_id:
        if scope_id in visited:
            raise ValueError("分类关系存在循环")
        visited.add(scope_id)
        row = connection.execute(
            "SELECT id, kind, parent_id, name FROM catalog_nodes WHERE id=?", [scope_id]
        ).fetchone()
        if not row:
            raise ValueError("目标分类不存在")
        result.append({"id": row[0], "kind": row[1], "name": row[3]})
        scope_id = row[2]
    return result


def batch_context(connection, batch_id):
    chain = ancestry(connection, batch_id)
    if not chain or chain[0]["kind"] != "batch":
        raise ValueError("请选择现存批次作为导入目标")
    network = next((n["id"] for n in chain if n["kind"] == "network"), None)
    user = next((n["id"] for n in chain if n["kind"] == "user"), None)
    if not network or not user:
        raise ValueError("目标批次缺少路网或研究员归属")
    return chain, network, user


def validate_existing(connection, bundle, network_id, exclude_run_id=None):
    issues = []
    for node in bundle["nodes"]:
        identity = (node["node_name"], node["node_name_chn"], node["node_code"])
        rows = connection.execute(
            "SELECT id,node_name,node_name_chn,node_code FROM nodes "
            "WHERE node_name=? OR node_name_chn=? OR node_code=?",
            identity,
        ).fetchall()
        if any(tuple(row[1:]) != identity for row in rows):
            issues.append(
                {
                    "severity": "error",
                    **node["source"],
                    **node_context(node),
                    "field": "node",
                    "cell": str(node["source"]["row"]),
                    "value": identity[0],
                    "message": "与已有全局节点三字段映射冲突",
                }
            )
        mapping = connection.execute(
            "SELECT n.node_name, m.node_ind FROM network_node_maps m "
            "JOIN nodes n ON n.id=m.node_id "
            "WHERE m.network_id=? AND (m.node_ind=? OR n.node_name=?)",
            [network_id, node["node_ind"], node["node_name"]],
        ).fetchall()
        if any(row != (node["node_name"], node["node_ind"]) for row in mapping):
            issues.append(
                {
                    "severity": "error",
                    **node["source"],
                    **node_context(node),
                    "field": "NODE_IND",
                    "cell": str(node["source"]["row"]),
                    "value": node["node_ind"],
                    "message": "与已有路网节点索引冲突",
                }
            )
    for line in bundle["lines"]:
        rows = connection.execute(
            "SELECT line_ind,line_code FROM network_lines WHERE network_id=? "
            "AND (line_ind=? OR line_code=?)",
            [network_id, line["LINE_IND"], line["LINE_CODE"]],
        ).fetchall()
        if any(row != (int(line["LINE_IND"]), line["LINE_CODE"]) for row in rows):
            issues.append(
                {
                    "severity": "error",
                    "sheet": "LINE_INFO",
                    "row": line["_row"],
                    "field": "LINE_IND",
                    "cell": str(line["_row"]),
                    "message": "与已有路网线路索引/编码冲突",
                }
            )
    candidates = {t["train_course_id"]: t["train_base_date"] for t in bundle["trains"]}
    for event in bundle["events"]:
        base = candidates.get(event["train_course_id"])
        if not base:
            continue
        rows = connection.execute(
            "SELECT e.node_name,e.visit_seq FROM timetable_events e "
            "JOIN run_trains t ON t.id=e.train_id JOIN base_run_data b ON b.run_id=e.run_id "
            "WHERE b.network_id=? AND t.train_course_id=? AND t.train_base_date=? "
            "AND (e.node_name=? OR e.visit_seq=?) AND (? IS NULL OR e.run_id<>?)",
            [
                network_id,
                event["train_course_id"],
                base,
                event["node_name"],
                event["visit_seq"],
                exclude_run_id,
                exclude_run_id,
            ],
        ).fetchall()
        if any(row != (event["node_name"], event["visit_seq"]) for row in rows):
            issues.append(
                {
                    "severity": "error",
                    "sheet": event["source"]["sheet"],
                    "row": event["source"]["row"],
                    "field": "SEQ",
                    "cell": str(event["source"]["row"]),
                    "message": "与已有同路网、同车次、同列车基准日的全局SEQ冲突",
                }
            )
    return issues


class BaseImportService:
    def __init__(self, database: Database, settings: Settings):
        self.database = database
        self.sources = settings.source_files or database.path.parent / "source_files"
        self.staging = settings.staging or database.path.parent / "staging"
        self.logs = settings.logs or database.path.parent / "logs"

    def stage_path(self, job_id):
        # Never accept a caller-supplied filesystem path.
        from uuid import UUID

        return self.staging / f"{UUID(job_id)}.xlsx"

    def summarize(self, bundle):
        return {
            "nodes": len(bundle["nodes"]),
            "lines": len(bundle["lines"]),
            "members": len(bundle["members"]),
            "events": len(bundle["events"]),
            "trains": len(bundle["trains"]),
            "minimum_run_times": len(bundle["minimum_run_times"]),
        }

    def preview(self, content: bytes, filename: str, options: ImportOptions):
        if options.write_mode == "replace" and options.run_no is None:
            raise ValueError("覆盖必须明确指定原 run 编号，不能使用自动编号")
        if not options.name.strip():
            raise ValueError("run名称不能为空")
        if options.date_base.year < 2020:
            raise ValueError("请设置2020年以后的运行基准日")
        filename = filename.replace("\\", "/").split("/")[-1]
        if not filename.lower().endswith(".xlsx") or len(filename) > 200:
            raise ValueError("请选择 XLSX 文件，文件名不超过200字符")
        job_id = str(uuid4())
        digest = hashlib.sha256(content).hexdigest()
        with self.database.transaction() as connection:
            chain, network, _ = batch_context(connection, options.batch_id)
            number = options.run_no
            if number is None:
                number = connection.execute(
                    "SELECT coalesce(max(run_no),0)+1 FROM runs WHERE batch_id=?",
                    [options.batch_id],
                ).fetchone()[0]
            effective = {
                **options.model_dump(mode="json"),
                "name": options.name.strip(),
                "run_no": number,
                "target_path": chain,
            }
            connection.execute(
                "INSERT INTO import_jobs (id,filename,digest,state,options) "
                "VALUES (?,?,?,'uploading',?)",
                [job_id, filename, digest, encode(effective)],
            )
        try:
            self.staging.mkdir(parents=True, exist_ok=True)
            self.stage_path(job_id).write_bytes(content)
            bundle = parse_base(content, options.date_base, options.date_mode, options.sheet)
            with self.database.transaction() as connection:
                duplicate = connection.execute(
                    "SELECT r.id,b.role FROM runs r LEFT JOIN base_run_data b ON b.run_id=r.id "
                    "WHERE r.batch_id=? AND r.name=? AND r.run_no=?",
                    [options.batch_id, effective["name"], number],
                ).fetchone()
                bundle["duplicate"] = (
                    {"run_id": duplicate[0], "is_base": duplicate[1] == "base"}
                    if duplicate
                    else None
                )
                bundle["replacement"] = None
                problem = None
                if options.write_mode == "replace":
                    if not duplicate or duplicate[1] != "base":
                        problem = (
                            "覆盖目标必须是同批次、同名、同编号的现存基本图；"
                            "不能跨层级覆盖或覆盖普通 run"
                        )
                    else:
                        info = self._base_snapshot(connection, duplicate[0])
                        if not info["hierarchy_matches"]:
                            problem = (
                                "原基本图归属与其路网/研究员配置不一致，不能覆盖；"
                                "请核对后删除并重新添加"
                            )
                        else:
                            bundle["replacement"] = info
                elif duplicate:
                    problem = "同批次同名同编号已存在；可修改名称/编号，或选择覆盖模式后重新预检"
                if problem:
                    bundle["issues"].append(
                        {
                            "severity": "error",
                            "sheet": "",
                            "row": 0,
                            "field": "name",
                            "code": "duplicate_run"
                            if options.write_mode == "create"
                            else "replace_target",
                            "message": problem,
                        }
                    )
                replacement_id = bundle["replacement"]["run_id"] if bundle["replacement"] else None
                bundle["issues"].extend(
                    validate_existing(connection, bundle, network, replacement_id)
                )
                bundle["summary"] = self.summarize(bundle)
                bundle["options"] = effective
                connection.execute(
                    "UPDATE import_jobs SET state='preview',report=? WHERE id=?",
                    [encode(bundle), job_id],
                )
            self.log_report(job_id, filename, bundle["issues"])
            return self.job(job_id)
        except Exception as error:
            self.stage_path(job_id).unlink(missing_ok=True)
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE import_jobs SET state='failed',error=? WHERE id=?", [str(error), job_id]
                )
            raise

    def log_report(self, job_id, filename, issues):
        try:
            self.logs.mkdir(parents=True, exist_ok=True)
            with (self.logs / "log_datamanagement.md").open("a", encoding="utf-8") as handle:
                handle.write(f"\n## Import {job_id} · {filename}\n")
                for item in issues:
                    handle.write(
                        f"- {item['severity']} | {item.get('sheet', '')} "
                        f"{item.get('cell', item.get('row', ''))} | "
                        f"{item['message']}\n"
                    )
        except OSError:
            logger.exception("Management log write failed; full report remains in import_jobs")

    def job(self, job_id):
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT filename,state,report,run_id,error FROM import_jobs WHERE id=?", [job_id]
            ).fetchone()
        if not row:
            raise LookupError("导入任务不存在")
        report = json.loads(row[2]) if row[2] else {}
        report["can_commit"] = (
            bool(report)
            and row[1] == "preview"
            and not any(i["severity"] == "error" for i in report.get("issues", []))
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
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT id,filename,state,run_id,error FROM import_jobs "
                "ORDER BY created_at DESC LIMIT 50"
            ).fetchall()
        return [
            dict(zip(("job_id", "filename", "state", "run_id", "error"), r, strict=True))
            for r in rows
        ]

    def _base_snapshot(self, connection, run_id):
        row = connection.execute(
            "SELECT r.id,r.batch_id,r.name,r.run_no,b.user_id,b.network_id,b.date_base,b.metadata "
            "FROM runs r JOIN base_run_data b ON b.run_id=r.id WHERE r.id=? AND b.role='base'",
            [run_id],
        ).fetchone()
        if not row:
            raise LookupError("基本图不存在")
        chain = ancestry(connection, run_id)
        path = [node for node in reversed(chain) if node["kind"] != "run"]
        configured = connection.execute(
            "SELECT scope_id,base_run_id FROM base_bindings ORDER BY scope_id"
        ).fetchall()
        references = []
        for scope_id, base_id in configured:
            if base_id != run_id:
                continue
            scope_path = list(reversed(ancestry(connection, scope_id)))
            if scope_path and scope_path[-1]["kind"] == "run":
                scope_path[-1]["name"] = connection.execute(
                    "SELECT name FROM runs WHERE id=?", [scope_id]
                ).fetchone()[0]
            references.append({"scope_id": scope_id, "path": scope_path})
        affected = []
        for other_id, name in connection.execute("SELECT id,name FROM runs ORDER BY id").fetchall():
            resolved = self._resolve(connection, other_id)
            if resolved and resolved["base_run_id"] == run_id:
                affected.append({"id": other_id, "name": name})
        scope_ids = {node["id"] for node in chain}
        relevant = [r for r in configured if r[0] in scope_ids or r[1] == run_id]
        sources = connection.execute(
            "SELECT id,digest,managed_name FROM source_files WHERE run_id=? ORDER BY id", [run_id]
        ).fetchall()
        token = hashlib.sha256(
            encode([row, chain, relevant, references, affected, sources]).encode()
        ).hexdigest()
        return {
            "run_id": run_id,
            "batch_id": row[1],
            "name": row[2],
            "run_no": row[3],
            "date_base": str(row[6]),
            "summary": json.loads(row[7])["summary"],
            "classification_path": path,
            "bindings": references,
            "affected_runs": affected,
            "hierarchy_matches": bool(row[1])
            and any(n["id"] == row[4] and n["kind"] == "user" for n in chain)
            and any(n["id"] == row[5] and n["kind"] == "network" for n in chain),
            "preview_token": token,
        }

    def _clear_run_data(self, connection, run_id):
        # Queue old managed copies only within the transaction that replaces/deletes their data.
        for (managed,) in connection.execute(
            "SELECT managed_name FROM source_files WHERE run_id=?", [run_id]
        ).fetchall():
            connection.execute(
                "INSERT INTO file_cleanup VALUES (?,NULL) ON CONFLICT DO NOTHING", [managed]
            )
        for table in (
            "timetable_events",
            "run_trains",
            "run_nodes",
            "infrastructure_records",
            "source_files",
            "base_run_data",
        ):
            connection.execute(f"DELETE FROM {table} WHERE run_id=?", [run_id])

    def deletion_preview(self, run_id):
        with self.database.transaction() as connection:
            result = self._base_snapshot(connection, run_id)
        result["blocking_bindings"] = [b for b in result["bindings"] if b["scope_id"] != run_id]
        result["can_delete"] = not result["blocking_bindings"]
        return result

    def delete_base(self, run_id, payload: BaseDelete):
        with self.database.lock:
            with self.database.transaction() as connection:
                preview = self._base_snapshot(connection, run_id)
                if payload.preview_token != preview["preview_token"]:
                    raise ImportConflict("基本图内容、归属或绑定已变化，请重新预览删除影响")
                if any(b["scope_id"] != run_id for b in preview["bindings"]):
                    raise ValueError(
                        "基本图仍被其他分类或 run 绑定，请先在查看编辑中解除或重新绑定"
                    )
                self._clear_run_data(connection, run_id)
                connection.execute("DELETE FROM base_bindings WHERE scope_id=?", [run_id])
                connection.execute(
                    "UPDATE import_jobs SET state='deleted',run_id=NULL WHERE run_id=?", [run_id]
                )
                connection.execute("DELETE FROM runs WHERE id=?", [run_id])
            self.cleanup_files()
        return {"deleted_run_id": run_id, "name": preview["name"]}

    def commit(self, job_id: str, payload: CommitImport):
        # Guard concurrent commits and serialize filesystem transitions with local DB writes.
        with self.database.lock:
            job = self.job(job_id)
            if job["state"] == "committed":
                return self.run(job["run_id"])
            if job["state"] != "preview" or not job["report"]["can_commit"]:
                raise ImportConflict("导入任务尚未通过预检，不能提交")
            report = job["report"]
            if (
                any(i["severity"] == "warning" for i in report["issues"])
                and not payload.warnings_confirmed
            ):
                raise ValueError("请核对并确认预检警告")
            options = report["options"]
            replacing = options.get("write_mode", "create") == "replace"
            replacement = report.get("replacement")
            if replacing:
                if not replacement or not payload.replace_confirmed:
                    raise ValueError("请单独确认覆盖原基本图内容及其引用影响")
                if payload.replace_token != replacement["preview_token"]:
                    raise ImportConflict("覆盖确认与预检不一致，请重新预检")
                if payload.bind_scope_id is not None or payload.binding_token is not None:
                    raise ValueError("覆盖必须保留原有层级与绑定配置，不能在覆盖时修改绑定")
            elif payload.replace_confirmed or payload.replace_token:
                raise ValueError("当前任务不是覆盖预检，不能通过提交参数改成覆盖")
            content = self.stage_path(job_id).read_bytes()
            with self.database.transaction() as connection:
                row = connection.execute(
                    "SELECT digest FROM import_jobs WHERE id=?", [job_id]
                ).fetchone()
                if hashlib.sha256(content).hexdigest() != row[0]:
                    raise ImportConflict("暂存文件已变化，请重新上传预检")
                digest = row[0]
                connection.execute("UPDATE import_jobs SET state='prepared' WHERE id=?", [job_id])
            managed_name = f"{job_id}.xlsx"
            destination = self.sources / managed_name
            try:
                self.sources.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.stage_path(job_id), destination)
                if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                    raise ImportConflict("源文件副本校验失败，请重新上传预检")
                run_id = replacement["run_id"] if replacing else str(uuid4())
                with self.database.transaction() as connection:
                    chain, network, user = batch_context(connection, options["batch_id"])
                    if chain != options["target_path"]:
                        raise ImportConflict("目标分类路径已变化，请重新预检")
                    if replacing:
                        try:
                            latest = self._base_snapshot(connection, run_id)
                        except LookupError as error:
                            raise ImportConflict("原基本图已删除，请重新预检") from error
                        if (
                            latest["preview_token"] != replacement["preview_token"]
                            or not latest["hierarchy_matches"]
                            or latest["batch_id"] != options["batch_id"]
                            or latest["name"] != options["name"]
                            or latest["run_no"] != options["run_no"]
                        ):
                            raise ImportConflict(
                                "原基本图内容、归属、绑定或引用范围已变化，请重新预检"
                            )
                    conflicts = validate_existing(
                        connection, report, network, run_id if replacing else None
                    )
                    if conflicts:
                        raise ImportConflict(conflicts[0]["message"] + "，请重新预检")
                    duplicate = connection.execute(
                        "SELECT id FROM runs WHERE batch_id=? AND name=? AND run_no=?",
                        [options["batch_id"], options["name"], options["run_no"]],
                    ).fetchone()
                    if (not replacing and duplicate) or (replacing and duplicate != (run_id,)):
                        raise ImportConflict("同批次同名同编号目标已变化，请重新预检选择新建或覆盖")
                    if payload.bind_scope_id:
                        scope = next((n for n in chain if n["id"] == payload.bind_scope_id), None)
                        if not scope or scope["kind"] == "user":
                            raise ValueError(
                                "导入时绑定目标必须为本路径的批次、算法、案例、场景或路网"
                            )
                        info = self._binding_preview(connection, payload.bind_scope_id)
                        if payload.binding_token != info["preview_token"]:
                            raise ImportConflict("基本图绑定或影响范围已变化，请重新预览绑定")
                    if replacing:
                        self._clear_run_data(connection, run_id)
                        connection.execute(
                            "UPDATE import_jobs SET state='superseded' "
                            "WHERE run_id=? AND state='committed'",
                            [run_id],
                        )
                    else:
                        connection.execute(
                            "INSERT INTO runs(id,batch_id,name,run_no) VALUES (?,?,?,?)",
                            [run_id, options["batch_id"], options["name"], options["run_no"]],
                        )
                    metadata = {
                        "summary": report["summary"],
                        "date_mode": report["date_mode"],
                        "source_date_origin": report["source_date_origin"],
                        "date_system": report["date_system"],
                        "sources": report["sources"],
                        "issues": report["issues"],
                        "confirmed": payload.model_dump(),
                    }
                    connection.execute(
                        "INSERT INTO base_run_data VALUES (?,'base',?,?,?,?)",
                        [run_id, user, network, options["date_base"], encode(metadata)],
                    )
                    node_ids = {}
                    for node in report["nodes"]:
                        existing = connection.execute(
                            "SELECT id FROM nodes WHERE node_name=?", [node["node_name"]]
                        ).fetchone()
                        node_id = existing[0] if existing else str(uuid4())
                        if not existing:
                            connection.execute(
                                "INSERT INTO nodes VALUES (?,?,?,?)",
                                [
                                    node_id,
                                    node["node_name"],
                                    node["node_name_chn"],
                                    node["node_code"],
                                ],
                            )
                        node_ids[node["node_name"]] = node_id
                        connection.execute(
                            "INSERT INTO network_node_maps VALUES (?,?,?) ON CONFLICT DO NOTHING",
                            [network, node["node_ind"], node_id],
                        )
                        connection.execute(
                            "INSERT INTO run_nodes VALUES (?,?,?)", [run_id, node_id, encode(node)]
                        )
                    for line in report["lines"]:
                        connection.execute(
                            "INSERT INTO network_lines VALUES (?,?,?,?) ON CONFLICT DO NOTHING",
                            [network, line["LINE_IND"], str(uuid4()), line["LINE_CODE"]],
                        )
                    for key in ("lines", "members", "minimum_run_times"):
                        for item in report[key]:
                            connection.execute(
                                "INSERT INTO infrastructure_records VALUES (?,?,?,?)",
                                [str(uuid4()), run_id, key, encode(item)],
                            )
                    train_ids = {}
                    for train in report["trains"]:
                        train_id = str(uuid4())
                        train_ids[train["train_course_id"]] = train_id
                        connection.execute(
                            "INSERT INTO run_trains VALUES (?,?,?,?,?)",
                            [
                                train_id,
                                run_id,
                                train["train_course_id"],
                                train["train_base_date"],
                                encode(train),
                            ],
                        )
                    names = {n["node_name"]: n["node_name_chn"] for n in report["nodes"]}
                    for event in report["events"]:
                        a, d = event["arrival"] or {}, event["departure"] or {}
                        connection.execute(
                            "INSERT INTO timetable_events VALUES "
                            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            [
                                str(uuid4()),
                                run_id,
                                train_ids[event["train_course_id"]],
                                node_ids[event["node_name"]],
                                event["train_course_id"],
                                event["node_name"],
                                names[event["node_name"]],
                                event["visit_seq"],
                                a.get("hms"),
                                a.get("seconds"),
                                a.get("day_offset"),
                                d.get("hms"),
                                d.get("seconds"),
                                d.get("day_offset"),
                                event["track_code"],
                                encode(event["source"]),
                                encode(event["line_inds"]),
                            ],
                        )
                    connection.execute(
                        "INSERT INTO source_files VALUES (?,?,?,?,?,?)",
                        [str(uuid4()), run_id, job_id, job["filename"], digest, managed_name],
                    )
                    if payload.bind_scope_id:
                        connection.execute(
                            "INSERT INTO base_bindings VALUES (?,?) "
                            "ON CONFLICT(scope_id) DO UPDATE SET base_run_id=excluded.base_run_id",
                            [payload.bind_scope_id, run_id],
                        )
                    connection.execute(
                        "UPDATE import_jobs SET state='committed',run_id=?,error=NULL WHERE id=?",
                        [run_id, job_id],
                    )
            except Exception as error:
                destination.unlink(missing_ok=True)
                with self.database.transaction() as connection:
                    connection.execute(
                        "UPDATE import_jobs SET state='preview',error=? WHERE id=?",
                        [str(error), job_id],
                    )
                raise
            # A completed DB commit remains successful even if temporary-file cleanup needs retry.
            try:
                self.stage_path(job_id).unlink(missing_ok=True)
            except OSError:
                logger.warning("Committed import staging cleanup pending: %s", job_id)
            self.cleanup_files()
            return self.run(run_id)

    def list_runs(self):
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT r.id,r.batch_id,r.name,r.run_no,b.date_base,b.metadata "
                "FROM runs r JOIN base_run_data b ON b.run_id=r.id ORDER BY r.name,r.run_no"
            ).fetchall()
        return [
            {
                "id": r[0],
                "batch_id": r[1],
                "name": r[2],
                "run_no": r[3],
                "role": "base",
                "date_base": str(r[4]),
                "summary": json.loads(r[5])["summary"],
            }
            for r in rows
        ]

    def run(self, run_id):
        run = next((r for r in self.list_runs() if r["id"] == run_id), None)
        if not run:
            raise LookupError("基本图 run 不存在")
        with self.database.transaction() as connection:
            run["metadata"] = json.loads(
                connection.execute(
                    "SELECT metadata FROM base_run_data WHERE run_id=?", [run_id]
                ).fetchone()[0]
            )
            run["trains"] = [
                json.loads(r[0])
                for r in connection.execute(
                    "SELECT data FROM run_trains WHERE run_id=? ORDER BY train_course_id", [run_id]
                ).fetchall()
            ]
            run["source_files"] = [
                {
                    "id": r[0],
                    "filename": r[1],
                    "digest": r[2],
                    "managed_path": str((self.sources / r[3]).resolve()),
                }
                for r in connection.execute(
                    "SELECT id,filename,digest,managed_name FROM source_files WHERE run_id=?",
                    [run_id],
                ).fetchall()
            ]
            run["classification_path"] = [
                node for node in reversed(ancestry(connection, run_id)) if node["kind"] != "run"
            ]
            run["origin_path"] = json.loads(
                connection.execute("SELECT origin_path FROM runs WHERE id=?", [run_id]).fetchone()[
                    0
                ]
            )
            run["effective_binding"] = self._resolve(connection, run_id)
        return run

    def catalog_bindings(self):
        """Resolve tree references in one snapshot without a query per category."""
        with self.database.transaction() as connection:
            nodes = {
                row[0]: {"id": row[0], "kind": row[1], "parent_id": row[2]}
                for row in connection.execute(
                    "SELECT id,kind,parent_id FROM catalog_nodes ORDER BY id"
                ).fetchall()
            }
            direct = {
                row[0]: {"base_run_id": row[1], "name": row[2]}
                for row in connection.execute(
                    "SELECT b.scope_id,b.base_run_id,r.name FROM base_bindings b "
                    "JOIN base_run_data d ON d.run_id=b.base_run_id "
                    "JOIN runs r ON r.id=b.base_run_id"
                ).fetchall()
            }
        result = []
        for node in nodes.values():
            if node["kind"] == "user":
                continue
            effective = None
            ancestor = node
            visited = set()
            while ancestor and ancestor["kind"] != "user" and ancestor["id"] not in visited:
                scope_id = ancestor["id"]
                visited.add(scope_id)
                if scope_id in direct:
                    effective = {
                        **direct[scope_id],
                        "scope_id": scope_id,
                        "scope_kind": ancestor["kind"],
                        "state": "working_unarchived",
                    }
                    break
                ancestor = nodes.get(ancestor["parent_id"])
            result.append(
                {
                    "scope_id": node["id"],
                    "current_direct": direct.get(node["id"], {}).get("base_run_id"),
                    "effective": effective,
                }
            )
        return result

    def _resolve(self, connection, scope_id):
        chain = ancestry(connection, scope_id)
        for node in chain:
            if node["kind"] == "user":
                continue
            row = connection.execute(
                "SELECT b.base_run_id,r.name FROM base_bindings b "
                "JOIN base_run_data d ON d.run_id=b.base_run_id JOIN runs r ON r.id=b.base_run_id "
                "WHERE b.scope_id=?",
                [node["id"]],
            ).fetchone()
            if row:
                return {
                    "base_run_id": row[0],
                    "name": row[1],
                    "scope_id": node["id"],
                    "scope_kind": node["kind"],
                    "state": "working_unarchived",
                }
        return None

    def _binding_preview(self, connection, scope_id):
        chain = ancestry(connection, scope_id)
        if not chain or chain[0]["kind"] == "user":
            raise ValueError("研究员级不支持基本图绑定")
        affected = []
        all_runs = connection.execute("SELECT id,name FROM runs ORDER BY id").fetchall()
        for run_id, name in all_runs:
            path = ancestry(connection, run_id)
            index = next((i for i, n in enumerate(path) if n["id"] == scope_id), None)
            if index is None:
                continue
            overridden = any(
                connection.execute(
                    "SELECT 1 FROM base_bindings WHERE scope_id=?", [n["id"]]
                ).fetchone()
                for n in path[:index]
            )
            if not overridden:
                affected.append({"id": run_id, "name": name})
        current = connection.execute(
            "SELECT base_run_id FROM base_bindings WHERE scope_id=?", [scope_id]
        ).fetchone()
        token = hashlib.sha256(encode([chain, current, affected]).encode()).hexdigest()
        return {
            "scope_id": scope_id,
            "current_direct": current[0] if current else None,
            "effective": self._resolve(connection, scope_id),
            "affected_runs": affected,
            "preview_token": token,
        }

    def binding_preview(self, scope_id):
        with self.database.transaction() as connection:
            return self._binding_preview(connection, scope_id)

    def bind(self, scope_id, payload: BindingChange):
        with self.database.transaction() as connection:
            preview = self._binding_preview(connection, scope_id)
            if preview["preview_token"] != payload.preview_token:
                raise ImportConflict("绑定影响范围已变化，请重新预览")
            if payload.base_run_id is not None:
                if not connection.execute(
                    "SELECT 1 FROM base_run_data WHERE run_id=? AND role='base'",
                    [payload.base_run_id],
                ).fetchone():
                    raise ValueError("请选择现存基本图 run")
                connection.execute(
                    "INSERT INTO base_bindings VALUES (?,?) "
                    "ON CONFLICT(scope_id) DO UPDATE SET base_run_id=excluded.base_run_id",
                    [scope_id, payload.base_run_id],
                )
            else:
                connection.execute("DELETE FROM base_bindings WHERE scope_id=?", [scope_id])
        return self.binding_preview(scope_id)

    def cancel(self, job_id):
        with self.database.lock:
            job = self.job(job_id)
            if job["state"] in {"committed", "superseded", "deleted"}:
                raise ImportConflict("已提交或已处理的任务不能取消，请通过基本图管理操作")
            self.stage_path(job_id).unlink(missing_ok=True)
            with self.database.transaction() as connection:
                connection.execute("UPDATE import_jobs SET state='cancelled' WHERE id=?", [job_id])
        return {"state": "cancelled"}

    def recover(self):
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT id,state FROM import_jobs "
                "WHERE state IN ('uploading','prepared','committed')"
            ).fetchall()
            for job_id, state in rows:
                if state != "committed":
                    (self.sources / f"{job_id}.xlsx").unlink(missing_ok=True)
                    self.stage_path(job_id).unlink(missing_ok=True)
                    connection.execute(
                        "UPDATE import_jobs SET state='failed',error=? WHERE id=?",
                        ["上次导入中断，原有run未改变，请重新上传", job_id],
                    )
                else:
                    try:
                        self.stage_path(job_id).unlink(missing_ok=True)
                    except OSError:
                        logger.warning("Staging cleanup pending: %s", job_id)
        self.cleanup_files()

    def cleanup_files(self):
        with self.database.transaction() as connection:
            for (name,) in connection.execute("SELECT managed_name FROM file_cleanup").fetchall():
                try:
                    candidate = (self.sources / name).resolve()
                    if candidate.parent != self.sources.resolve():
                        raise ValueError("非法受管文件路径")
                    candidate.unlink(missing_ok=True)
                    connection.execute("DELETE FROM file_cleanup WHERE managed_name=?", [name])
                except (ValueError, OSError) as error:
                    connection.execute(
                        "UPDATE file_cleanup SET error=? WHERE managed_name=?", [str(error), name]
                    )
