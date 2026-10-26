"""Explicit legacy migration with an inspectable plan and rollback backup."""

import json
import shutil
from uuid import uuid4

from app.base_timetables.service import token, token_bytes
from app.ingest.base_service import BaseImportService, ImportConflict, encode


class MigrationService:
    def __init__(self, service, settings):
        self.service = service
        self.database = service.database
        self.legacy = BaseImportService(self.database, settings)

    def list_legacy(self):
        return self.legacy.list_runs()

    def document(self, c, old_id):
        self.legacy._base_snapshot(c, old_id)
        doc = {
            key: []
            for key in ("nodes", "trains", "events", "lines", "members", "minimum_run_times")
        }
        snapshots = {}
        for table in (
            "runs",
            "base_run_data",
            "run_nodes",
            "run_trains",
            "timetable_events",
            "infrastructure_records",
            "source_files",
            "import_jobs",
        ):
            column = "id" if table == "runs" else "run_id"
            cursor = c.execute(f"SELECT * FROM {table} WHERE {column}=?", [old_id])
            names = [d[0] for d in cursor.description]
            snapshots[table] = [dict(zip(names, r, strict=True)) for r in cursor.fetchall()]
        for n in snapshots["run_nodes"]:
            doc["nodes"].append(json.loads(n["data"]) | {"id": n["node_id"]})
        for t in snapshots["run_trains"]:
            doc["trains"].append(json.loads(t["data"]) | {"id": t["id"]})
        for e in snapshots["timetable_events"]:

            def time_value(prefix):
                return (
                    None
                    if e[prefix + "_seconds"] is None
                    else {
                        "hms": e[prefix + "_hms"],
                        "seconds": e[prefix + "_seconds"],
                        "day_offset": e[prefix + "_day_offset"],
                    }
                )

            doc["events"].append(
                {
                    k: e[k]
                    for k in (
                        "id",
                        "train_id",
                        "node_id",
                        "train_course_id",
                        "node_name",
                        "visit_seq",
                        "track_code",
                    )
                }
                | {
                    "arrival": time_value("arrival"),
                    "departure": time_value("departure"),
                    "source": json.loads(e["source"]),
                    "line_inds": json.loads(e["line_inds"]),
                }
            )
        for r in snapshots["infrastructure_records"]:
            doc[r["kind"]].append(json.loads(r["data"]))
        doc["issues"] = json.loads(snapshots["base_run_data"][0]["metadata"]).get("issues", [])
        snapshots["bindings"] = c.execute(
            "SELECT scope_id,base_run_id FROM base_bindings WHERE scope_id=? "
            "OR base_run_id=? ORDER BY scope_id",
            [old_id, old_id],
        ).fetchall()
        return doc, snapshots

    def preview(self, old_id, target):
        with self.database.transaction() as c:
            original = self.legacy._base_snapshot(c, old_id)
            doc, snapshot = self.document(c, old_id)
            state = self.service.state(c)
            path = self.service.category(c, target)
            occupied = next((b for b in state["bases"] if b[2] == target), None)
            issues = self.service.validate_scope(c, doc, target, exclude_legacy=old_id)
            for file in snapshot["source_files"]:
                source = (self.service.sources / file["managed_name"]).resolve()
                if (
                    source.parent != self.service.sources.resolve()
                    or not source.is_file()
                    or token_bytes(source.read_bytes()) != file["digest"]
                ):
                    issues.append(
                        {"severity": "error", "message": "旧受管源文件缺失或摘要不符，须先修复"}
                    )
            after = dict(state)
            after["bases"] = state["bases"] + [("migrated", "待分配", target, original["name"], 1)]
            # Display old references, including branches that will lose access.
            changes = []
            for scope, base in c.execute(
                "SELECT scope_id,base_run_id FROM base_bindings WHERE "
                "base_run_id=? ORDER BY scope_id",
                [old_id],
            ).fetchall():
                resolved = self.service.resolve_state(after, scope)
                changes.append({"scope_id": scope, "old_base_run_id": base, "after": resolved})
            return {
                "old_run_id": old_id,
                "original": original,
                "target_path": path,
                "target_category_id": target,
                "occupied": bool(occupied),
                "issues": issues,
                "legacy_binding_changes": changes,
                "impact": self.service.impact(state, after),
                "can_migrate": not occupied and not issues,
                "preview_token": token([state, snapshot, target]),
            }

    def commit(self, old_id, payload):
        with self.database.lock:
            preview = self.preview(old_id, payload.target_category_id)
            if preview["preview_token"] != payload.preview_token:
                raise ImportConflict("旧数据、来源、分类或占用已变化，请重新预览迁移")
            if not preview["can_migrate"]:
                raise ValueError("迁移目标已占用或存在阻断问题")
            # All DB connections are closed here. Copy the DB plus managed sources for rollback.
            backup = self.database.path.parent / "migration_backups" / str(uuid4())
            backup.mkdir(parents=True)
            shutil.copy2(self.database.path, backup / self.database.path.name)
            wal = self.database.path.with_name(self.database.path.name + ".wal")
            if wal.exists():
                shutil.copy2(wal, backup / wal.name)
            if self.service.sources.exists():
                shutil.copytree(self.service.sources, backup / "source_files")
            latest = self.preview(old_id, payload.target_category_id)
            if latest["preview_token"] != payload.preview_token or not latest["can_migrate"]:
                raise ImportConflict("备份期间来源或迁移条件变化，未提交迁移，请重新预览")
            with self.database.transaction() as c:
                doc, snapshot = self.document(c, old_id)
                base_id = str(uuid4())
                c.execute(
                    "INSERT INTO base_timetables VALUES (?,?,?,?,?,?,1)",
                    [
                        base_id,
                        "BTT-" + uuid4().hex,
                        payload.target_category_id,
                        preview["original"]["name"],
                        preview["original"]["date_base"],
                        encode(doc),
                    ],
                )
                for file in snapshot["source_files"]:
                    c.execute(
                        "INSERT INTO base_tt_sources VALUES (?,?,?,?,?,?)",
                        [
                            file["id"],
                            base_id,
                            file["job_id"],
                            file["filename"],
                            file["digest"],
                            file["managed_name"],
                        ],
                    )
                c.execute(
                    "INSERT INTO base_tt_migrations(old_run_id,base_tt_id,snapshot) VALUES (?,?,?)",
                    [
                        old_id,
                        base_id,
                        encode(
                            {"records": snapshot, "backup_path": str(backup), "preview": preview}
                        ),
                    ],
                )
                for table in (
                    "base_run_data",
                    "run_nodes",
                    "run_trains",
                    "timetable_events",
                    "infrastructure_records",
                    "source_files",
                ):
                    c.execute(f"DELETE FROM {table} WHERE run_id=?", [old_id])
                c.execute(
                    "DELETE FROM base_bindings WHERE scope_id=? OR base_run_id=?", [old_id, old_id]
                )
                c.execute("UPDATE import_jobs SET state='migrated' WHERE run_id=?", [old_id])
                c.execute("DELETE FROM runs WHERE id=?", [old_id])
            return {"base": self.service.detail(base_id), "backup_path": str(backup)}
