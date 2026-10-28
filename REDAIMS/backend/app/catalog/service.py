import hashlib
import json
from typing import Literal
from uuid import uuid4

from app.storage.database import Database
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Kind = Literal["user", "network", "scenario", "case", "algorithm", "batch"]
PARENTS = {
    "user": None,
    "network": "user",
    "scenario": "network",
    "case": "scenario",
    "algorithm": "case",
    "batch": "algorithm",
}


class CatalogCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Kind
    parent_id: str | None = None
    name: str = Field(min_length=1, max_length=200)
    notes: str = Field(default="", max_length=20000)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("名称不能为空")
        return value


class CatalogPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=20000)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str:
        if value is None or not value.strip():
            raise ValueError("名称不能为空")
        return value.strip()

    @model_validator(mode="after")
    def require_changes(self):
        if not self.model_fields_set:
            raise ValueError("请提供名称或备注")
        if "notes" in self.model_fields_set and self.notes is None:
            raise ValueError("备注不能为null，请使用空字符串清空备注")
        return self


class CatalogDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["delete", "ungroup", "move"]
    target_batch_id: str | None = None
    preview_token: str
    confirmed: Literal[True]


class StalePreviewError(Exception):
    pass


class CatalogService:
    def __init__(self, database: Database):
        self.database = database

    def list_nodes(self):
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT id, kind, parent_id, name, notes FROM catalog_nodes ORDER BY created_at, id"
            ).fetchall()
        keys = ("id", "kind", "parent_id", "name", "notes")
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def create(self, payload: CatalogCreate):
        with self.database.transaction() as connection:
            expected = PARENTS[payload.kind]
            if expected is None:
                if payload.parent_id is not None:
                    raise ValueError("用户节点不能有父节点")
            else:
                parent = connection.execute(
                    "SELECT kind FROM catalog_nodes WHERE id = ?", [payload.parent_id]
                ).fetchone()
                if parent is None or parent[0] != expected:
                    raise ValueError(f"父节点必须为 {expected}")
            duplicate = connection.execute(
                "SELECT id FROM catalog_nodes WHERE parent_id IS NOT DISTINCT FROM ? "
                "AND kind = ? AND name = ?",
                [payload.parent_id, payload.kind, payload.name],
            ).fetchone()
            if duplicate:
                raise FileExistsError("同一父节点下名称已存在")
            node_id = str(uuid4())
            connection.execute(
                "INSERT INTO catalog_nodes (id, kind, parent_id, name, notes) "
                "VALUES (?, ?, ?, ?, ?)",
                [node_id, payload.kind, payload.parent_id, payload.name, payload.notes],
            )
        return {"id": node_id, **payload.model_dump()}

    def update(self, node_id: str, payload: CatalogPatch):
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT id,kind,parent_id,name,notes FROM catalog_nodes WHERE id=?", [node_id]
            ).fetchone()
            if row is None:
                raise LookupError("分类节点不存在")
            changes = payload.model_dump(exclude_unset=True)
            name, notes = changes.get("name", row[3]), changes.get("notes", row[4])
            if (
                name != row[3]
                and connection.execute(
                    "SELECT 1 FROM catalog_nodes WHERE parent_id IS NOT DISTINCT FROM ? "
                    "AND kind=? AND name=? AND id<>?",
                    [row[2], row[1], name, node_id],
                ).fetchone()
            ):
                raise FileExistsError("同一父节点下名称已存在")
            connection.execute(
                "UPDATE catalog_nodes SET name=?,notes=? WHERE id=?", [name, notes, node_id]
            )
        return {"id": node_id, "kind": row[1], "parent_id": row[2], "name": name, "notes": notes}

    def _impact(self, connection, node_id: str):
        nodes = connection.execute(
            "SELECT id, kind, parent_id, name, notes FROM catalog_nodes ORDER BY id"
        ).fetchall()
        by_id = {row[0]: row for row in nodes}
        if node_id not in by_id:
            raise LookupError("分类节点不存在")
        affected = {node_id}
        while True:
            descendants = {row[0] for row in nodes if row[2] in affected}
            if descendants <= affected:
                break
            affected |= descendants
        runs = connection.execute(
            "SELECT id, batch_id, name, run_no, origin_path FROM runs ORDER BY id"
        ).fetchall()
        affected_runs = [row for row in runs if row[1] in affected]
        bindings = connection.execute(
            "SELECT scope_id,base_run_id FROM base_bindings ORDER BY scope_id"
        ).fetchall()
        physical = connection.execute(
            "SELECT id,owner_category_id,name,revision FROM base_timetables ORDER BY id"
        ).fetchall()
        snapshot = [[row for row in nodes if row[0] in affected], affected_runs, bindings, physical]
        token = hashlib.sha256(json.dumps(snapshot, ensure_ascii=False).encode()).hexdigest()
        return by_id, affected, affected_runs, token

    def deletion_preview(self, node_id: str):
        with self.database.transaction() as connection:
            by_id, affected, runs, token = self._impact(connection, node_id)
            physical = [
                {"id": r[0], "owner_category_id": r[1], "name": r[2]}
                for r in connection.execute(
                    "SELECT id,owner_category_id,name FROM base_timetables ORDER BY id"
                ).fetchall()
                if r[1] in affected
            ]
            legacy = [
                r[0]
                for r in runs
                if connection.execute(
                    "SELECT 1 FROM base_run_data WHERE run_id=? AND role='base'", [r[0]]
                ).fetchone()
            ]
        return {
            "physical_base_timetables": physical,
            "legacy_base_ids": legacy,
            "can_delete": not physical and not legacy,
            "node_count": len(affected),
            "run_count": len(runs),
            "preview_token": token,
            "nodes": [
                {"id": key, "name": by_id[key][3], "kind": by_id[key][1]}
                for key in sorted(affected)
            ],
            "runs": [{"id": row[0], "name": row[2], "run_no": row[3]} for row in runs],
            "eligible_batches": [
                {"id": row[0], "name": row[3]}
                for row in by_id.values()
                if row[1] == "batch" and row[0] not in affected
            ],
        }

    def delete(self, node_id: str, payload: CatalogDelete):
        with self.database.transaction() as connection:
            by_id, affected, runs, token = self._impact(connection, node_id)
            physical = connection.execute(
                "SELECT owner_category_id FROM base_timetables"
            ).fetchall()
            if any(r[0] in affected for r in physical):
                raise ValueError("范围内存在物理基本图，请先移动或单独删除，run 去向不适用于基本图")
            if any(
                connection.execute(
                    "SELECT 1 FROM base_run_data WHERE run_id=? AND role='base'", [r[0]]
                ).fetchone()
                for r in runs
            ):
                raise ValueError("范围内有旧基本图，请先通过迁移入口明确实际存储类别")
            if payload.preview_token != token:
                raise StalePreviewError("分类或 run 已变化，请重新预览后确认")
            if payload.action != "move" and payload.target_batch_id is not None:
                raise ValueError("仅转移操作允许指定目标批次")
            if payload.action == "move":
                target = by_id.get(payload.target_batch_id)
                if target is None or target[1] != "batch" or target[0] in affected:
                    raise ValueError("目标必须是删除范围外的现存批次")
                keys = set()
                existing = connection.execute(
                    "SELECT name, run_no FROM runs WHERE batch_id = ?",
                    [payload.target_batch_id],
                ).fetchall()
                keys.update(existing)
                for row in runs:
                    key = (row[2], row[3])
                    if key in keys:
                        raise FileExistsError("目标批次存在同名同编号 run，或待转移 run 互相重名")
                    keys.add(key)
            run_ids = {r[0] for r in runs}
            scopes = affected | run_ids
            bindings = connection.execute(
                "SELECT scope_id,base_run_id FROM base_bindings"
            ).fetchall()
            if payload.action == "delete" and any(
                base in run_ids and scope not in scopes for scope, base in bindings
            ):
                raise ValueError("待删除基本图仍被范围外对象绑定，请先重绑或解除")
            if payload.action == "move":
                from app.ingest.base_service import batch_context

                _, target_network, _ = batch_context(connection, payload.target_batch_id)
                for run_id in run_ids:
                    row = connection.execute(
                        "SELECT network_id FROM base_run_data WHERE run_id=?", [run_id]
                    ).fetchone()
                    if (
                        not row
                        and connection.execute(
                            "SELECT 1 FROM timetable_events WHERE run_id=? LIMIT 1", [run_id]
                        ).fetchone()
                    ):
                        old_path = next(r[1] for r in runs if r[0] == run_id)
                        _, original_network, _ = batch_context(connection, old_path)
                        if original_network != target_network:
                            raise ValueError("run跨路网转移需映射确认，请选择同路网批次")
                    if row and row[0] != target_network:
                        raise ValueError(
                            "已导入run跨路网转移须先校验索引映射，目前请选同路网批次或未分组"
                        )
            for scope in affected:
                connection.execute("DELETE FROM base_bindings WHERE scope_id=?", [scope])
            for row in runs:
                if payload.action == "delete":
                    for (managed,) in connection.execute(
                        "SELECT managed_name FROM source_files WHERE run_id=?", [row[0]]
                    ).fetchall():
                        connection.execute(
                            "INSERT INTO file_cleanup VALUES (?,NULL) ON CONFLICT DO NOTHING",
                            [managed],
                        )
                    for table in (
                        "timetable_events",
                        "run_trains",
                        "run_nodes",
                        "infrastructure_records",
                        "source_files",
                        "base_run_data",
                        "run_working_data",
                        "run_solver_logs",
                        "run_diagram_views",
                        "run_analysis_nodes",
                    ):
                        connection.execute(f"DELETE FROM {table} WHERE run_id=?", [row[0]])
                    connection.execute("DELETE FROM base_bindings WHERE scope_id=?", [row[0]])
                    connection.execute(
                        "UPDATE import_jobs SET state='deleted',run_id=NULL WHERE run_id=?",
                        [row[0]],
                    )
                    connection.execute("DELETE FROM runs WHERE id = ?", [row[0]])
                    continue
                path = []
                current = row[1]
                while current is not None:
                    node = by_id[current]
                    path.append({"id": node[0], "kind": node[1], "name": node[3]})
                    current = node[2]
                origin = (
                    row[4] if json.loads(row[4]) else json.dumps(path[::-1], ensure_ascii=False)
                )
                connection.execute(
                    "UPDATE runs SET batch_id = ?, origin_path = ? WHERE id = ?",
                    [payload.target_batch_id if payload.action == "move" else None, origin, row[0]],
                )
            for key in affected:
                connection.execute("DELETE FROM catalog_nodes WHERE id = ?", [key])
        return {
            "deleted_nodes": len(affected),
            "affected_runs": len(runs),
            "action": payload.action,
        }

    def ungrouped_runs(self):
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT id, name, run_no, origin_path FROM runs WHERE batch_id IS "
                "NULL AND id NOT IN (SELECT run_id FROM base_run_data WHERE "
                "role='base') ORDER BY id"
            ).fetchall()
        return [
            {"id": row[0], "name": row[1], "run_no": row[2], "origin_path": json.loads(row[3])}
            for row in rows
        ]
