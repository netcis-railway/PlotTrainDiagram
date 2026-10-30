"""Fixed experiment membership; catalog ownership never controls member scope."""

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator


class ClassificationEntry(BaseModel):
    id: str
    kind: str
    name: str


class ExperimentRun(BaseModel):
    id: str
    batch_id: str | None
    name: str
    run_no: int
    classification_path: list[ClassificationEntry]
    effective_base: dict[str, JsonValue]
    date_base: str | None
    unavailable_reason: str


class ExperimentDetail(BaseModel):
    id: str
    name: str
    owner_category_id: str
    notes: str
    revision: int
    member_mode: Literal["fixed"]
    classification_path: list[ClassificationEntry]
    member_ids: list[str]
    member_count: int
    members: list[ExperimentRun]
    status: Literal["empty", "ready", "invalid"]
    issues: list[str]
    base_tt_id: str | None
    date_base: str | None


class CreateExperiment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    owner_category_id: str = Field(min_length=1, max_length=200)
    notes: str = Field(default="", max_length=20000)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("实验名称不能为空")
        return value.strip()


class Revision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)


class PatchExperiment(Revision):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    owner_category_id: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=20000)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        return CreateExperiment.clean_name(value) if value is not None else value

    @model_validator(mode="after")
    def check_changes(self):
        changes = self.model_fields_set - {"revision"}
        if not changes or any(getattr(self, key) is None for key in changes):
            raise ValueError("请提供实验名称、备注或存放类别，且不能为null")
        return self


class AddMembers(Revision):
    run_ids: list[str] = Field(default_factory=list, max_length=2000)
    batch_ids: list[str] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def check_selection(self):
        if not self.run_ids and not self.batch_ids:
            raise ValueError("请选择run或批次")
        return self


class RemoveMembers(Revision):
    run_ids: list[str] = Field(min_length=1, max_length=2000)


class DeleteExperiment(Revision):
    confirmed: Literal[True]


class ExperimentConflict(Exception):
    pass


class ExperimentService:
    def __init__(self, database, timetables):
        self.database = database
        self.timetables = timetables

    def _row(self, c, experiment_id, revision=None):
        row = c.execute(
            "SELECT id,name,owner_category_id,notes,revision FROM experiments WHERE id=?",
            [experiment_id],
        ).fetchone()
        if row is None:
            raise LookupError("实验不存在")
        if revision is not None and revision != row[4]:
            raise ExperimentConflict("实验已被修改，请刷新后重试")
        return row

    def _runs(self, c):
        state = self.timetables.state(c)
        base_dates = dict(c.execute("SELECT id,date_base FROM base_timetables").fetchall())
        result = {}
        rows = c.execute(
            "SELECT r.id,r.batch_id,r.name,r.run_no,w.date_base FROM runs r "
            "LEFT JOIN run_working_data w ON w.run_id=r.id WHERE r.id NOT IN "
            "(SELECT run_id FROM base_run_data WHERE role='base') ORDER BY r.name,r.run_no,r.id"
        ).fetchall()
        for run_id, batch_id, name, number, day in rows:
            effective = self.timetables.resolve_state(state, batch_id)
            path = self.timetables.category(c, batch_id) if batch_id else []
            path = path + [{"id": run_id, "kind": "run", "name": name}]
            reason = ""
            if not effective["base_tt_id"]:
                reason = "未分组或无有效基本图"
            elif day is None:
                reason = "缺少已保存的运行基准日"
            elif day != base_dates[effective["base_tt_id"]]:
                reason = "run与基本图的运行基准日不同"
            result[run_id] = {
                "id": run_id,
                "batch_id": batch_id,
                "name": name,
                "run_no": number,
                "classification_path": path,
                "effective_base": effective,
                "date_base": str(day) if day else None,
                "unavailable_reason": reason,
            }
        return result

    @staticmethod
    def compatibility(members):
        issues = [
            f"{m['name']}：{m['unavailable_reason']}" for m in members if m["unavailable_reason"]
        ]
        bases = {m["effective_base"]["base_tt_id"] for m in members}
        days = {m["date_base"] for m in members}
        if len(bases) > 1:
            issues.append("成员使用了不同的实际基本图")
        if len(days) > 1:
            issues.append("成员使用了不同的运行基准日")
        return {
            "status": "invalid" if issues else "ready" if members else "empty",
            "issues": issues,
            "base_tt_id": next(iter(bases)) if len(bases) == 1 else None,
            "date_base": next(iter(days)) if len(days) == 1 else None,
        }

    def _detail(self, c, row, runs):
        ids = [
            r[0]
            for r in c.execute(
                "SELECT run_id FROM experiment_members WHERE experiment_id=? ORDER BY run_id",
                [row[0]],
            ).fetchall()
        ]
        members = [runs[key] for key in ids]
        return {
            "id": row[0],
            "name": row[1],
            "owner_category_id": row[2],
            "notes": row[3],
            "revision": row[4],
            "member_mode": "fixed",
            "classification_path": self.timetables.category(c, row[2]),
            "member_ids": ids,
            "member_count": len(ids),
            "members": members,
            **self.compatibility(members),
        }

    def list(self):
        with self.database.transaction() as c:
            runs = self._runs(c)
            return [
                self._detail(c, row, runs)
                for row in c.execute(
                    "SELECT id,name,owner_category_id,notes,revision "
                    "FROM experiments ORDER BY name,id"
                ).fetchall()
            ]

    def candidates(self):
        with self.database.transaction() as c:
            return list(self._runs(c).values())

    def detail(self, experiment_id):
        with self.database.transaction() as c:
            return self._detail(c, self._row(c, experiment_id), self._runs(c))

    def _name_available(self, c, name, exclude=""):
        if c.execute(
            "SELECT 1 FROM experiments WHERE name=? AND id<>?", [name, exclude]
        ).fetchone():
            raise ExperimentConflict("实验名称已存在（实验名称全局唯一）")

    def create(self, payload):
        with self.database.transaction() as c:
            self.timetables.category(c, payload.owner_category_id)
            self._name_available(c, payload.name)
            experiment_id = str(uuid4())
            c.execute(
                "INSERT INTO experiments (id,name,owner_category_id,notes) VALUES (?,?,?,?)",
                [experiment_id, payload.name, payload.owner_category_id, payload.notes],
            )
            return self._detail(c, self._row(c, experiment_id), {})

    def update(self, experiment_id, payload):
        with self.database.transaction() as c:
            row = self._row(c, experiment_id, payload.revision)
            changes = payload.model_dump(exclude_unset=True)
            name = changes.get("name", row[1])
            owner = changes.get("owner_category_id", row[2])
            self._name_available(c, name, experiment_id)
            self.timetables.category(c, owner)
            c.execute(
                "UPDATE experiments SET name=?,owner_category_id=?,notes=?,revision=revision+1 "
                "WHERE id=?",
                [name, owner, changes.get("notes", row[3]), experiment_id],
            )
            return self._detail(c, self._row(c, experiment_id), self._runs(c))

    def add(self, experiment_id, payload):
        with self.database.transaction() as c:
            self._row(c, experiment_id, payload.revision)
            runs = self._runs(c)
            wanted = set(payload.run_ids)
            for batch_id in set(payload.batch_ids):
                row = c.execute("SELECT kind FROM catalog_nodes WHERE id=?", [batch_id]).fetchone()
                if row is None or row[0] != "batch":
                    raise ValueError("整批加入的目标必须是现存批次")
                wanted.update(r["id"] for r in runs.values() if r["batch_id"] == batch_id)
            if wanted - runs.keys():
                raise ValueError("选择中有不存在的普通run或旧基本图，请刷新列表")
            existing = {
                r[0]
                for r in c.execute(
                    "SELECT run_id FROM experiment_members WHERE experiment_id=?", [experiment_id]
                ).fetchall()
            }
            check = self.compatibility([runs[key] for key in sorted(existing | wanted)])
            if check["status"] == "invalid":
                raise ExperimentConflict("无法加入实验：" + "；".join(check["issues"]))
            for run_id in sorted(wanted - existing):
                c.execute("INSERT INTO experiment_members VALUES (?,?)", [experiment_id, run_id])
            if wanted - existing:
                c.execute("UPDATE experiments SET revision=revision+1 WHERE id=?", [experiment_id])
            return self._detail(c, self._row(c, experiment_id), runs)

    def remove(self, experiment_id, payload):
        with self.database.transaction() as c:
            self._row(c, experiment_id, payload.revision)
            changed = False
            for run_id in set(payload.run_ids):
                rows = c.execute(
                    "DELETE FROM experiment_members WHERE experiment_id=? AND run_id=? "
                    "RETURNING run_id",
                    [experiment_id, run_id],
                ).fetchall()
                changed |= bool(rows)
            if changed:
                c.execute("UPDATE experiments SET revision=revision+1 WHERE id=?", [experiment_id])
            return self._detail(c, self._row(c, experiment_id), self._runs(c))

    def delete(self, experiment_id, payload):
        with self.database.transaction() as c:
            self._row(c, experiment_id, payload.revision)
            c.execute("DELETE FROM experiment_members WHERE experiment_id=?", [experiment_id])
            c.execute("DELETE FROM experiments WHERE id=?", [experiment_id])
        return {"deleted_experiment_id": experiment_id}
