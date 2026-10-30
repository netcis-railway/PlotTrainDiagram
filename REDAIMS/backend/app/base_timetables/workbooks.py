"""Editable four-sheet workbooks and a durable copy of saved BaseTT working data."""

import copy
import json
import math
import os
import re
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from io import BytesIO
from uuid import uuid4

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.utils import get_column_letter
from pydantic import BaseModel, ConfigDict, Field

from app.base_timetables.service import token, token_bytes
from app.ingest.base_parser import parse_base
from app.ingest.base_service import ImportConflict, encode
from app.ingest.inspection import inspect_workbook

INFRASTRUCTURE = {"LINE_INFO", "NODE_INFO", "MINIMUM_RUN_TIME"}


def format_timetable_times(sheet):
    """Display train times without hiding their stored date or cross-day value."""
    # Worksheet dimensions scan all cells. Resolve them once, rather than once per train.
    last_row = sheet.max_row
    for header in sheet[1]:
        if isinstance(header.value, str) and header.value.endswith(("_A", "_D")):
            for row in sheet.iter_rows(
                min_row=2, max_row=last_row, min_col=header.column, max_col=header.column
            ):
                row[0].number_format = "hh:mm:ss"


class WorkbookCellChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sheet: str = Field(min_length=1, max_length=31)
    row: int = Field(ge=2, le=1048576)
    column: int = Field(ge=1, le=16384)
    value: str | None = Field(max_length=32767)


class WorkbookEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(max_length=100)
    changes: list[WorkbookCellChange] = Field(min_length=1, max_length=50000)


class WorkbookSave(WorkbookEdit):
    validation_token: str
    warnings_confirmed: bool = False
    train_dates_confirmed: bool = False


def workbook_names(book, doc):
    timetables = {e.get("source", {}).get("sheet") for e in doc["events"]}
    names = [s for s in book.sheetnames if s in timetables or s in INFRASTRUCTURE]
    if not INFRASTRUCTURE.issubset(names) or not timetables or not timetables.issubset(names):
        raise ValueError("受管工作簿缺少基本图四表，请核对导入来源")
    return names


def source_content(base, c, base_id, *, kind="base", original=False, required=True):
    table, key, sources = (
        ("base_tt_workbooks", "base_tt_id", "base_tt_sources")
        if kind == "base"
        else ("run_workbooks", "run_id", "source_files")
    )
    row = (
        None
        if original
        else c.execute(
            f"SELECT managed_name,digest FROM {table} WHERE {key}=?", [base_id]
        ).fetchone()
    )
    if not row:
        rows = c.execute(
            f"SELECT managed_name,digest FROM {sources} WHERE {key}=?", [base_id]
        ).fetchall()
        if not rows and not required:
            return None
        if len(rows) != 1:
            raise ValueError("四表编辑需要唯一的受管Excel来源，请先核对或重新导入基本图")
        row = rows[0]
    path = (base.sources / row[0]).resolve()
    if path.parent != base.sources.resolve():
        raise ValueError("非法受管工作簿路径")
    content = path.read_bytes()
    if len(content) > 32 * 1024 * 1024:
        raise ValueError("受管工作簿超过32 MB限制")
    if token_bytes(content) != row[1]:
        raise ImportConflict("受管Excel副本在应用外发生变化，请核对文件后重新导入")
    return content


def materialize(base, c, base_id, doc, day):
    """Keep source rows, columns, extra sheets and styles; apply saved timetable values."""
    content = source_content(base, c, base_id)
    return materialize_content(content, doc, day), token_bytes(content)


def materialize_content(content, doc, day, *, require_infrastructure=True):
    inspect_workbook(content)  # Includes XLSX expansion and table size limits.
    book = load_workbook(BytesIO(content), data_only=False)
    try:
        names = (
            workbook_names(book, doc)
            if require_infrastructure
            else list({e.get("source", {}).get("sheet") for e in doc["events"]})
        )
        if not names or any(name not in book.sheetnames for name in names):
            raise ValueError("受管Excel缺少当前时刻表的原工作表，不能覆盖其他表单")
        if any(book[name].max_row * book[name].max_column > 2_000_000 for name in names):
            raise ValueError("工作表超过200万单元格限制")
        start = datetime.combine(date.fromisoformat(str(day)), time())
        for event in doc["events"]:
            source = event.get("source", {})
            sheet, row, column = source.get("sheet"), source.get("row"), source.get("first_column")
            if sheet not in book.sheetnames or not row or not column:
                raise ValueError("时刻表缺少源单元格定位，不能无损更新Excel副本")
            ws = book[sheet]
            for offset, field in enumerate(("arrival", "departure", "track_code", "visit_seq")):
                cell = ws.cell(row, column + offset)
                expected = f"{event['train_course_id']}_{('A', 'D', 'G', 'SEQ')[offset]}"
                if ws.cell(1, column + offset).value != expected:
                    raise ValueError("受管Excel列车表头与数据库来源不一致，请重新导入")
                value = event[field]
                if field in {"arrival", "departure"}:
                    value = start + timedelta(seconds=value["seconds"]) if value else None
                cell.value = value
        for name in {e["source"]["sheet"] for e in doc["events"]}:
            format_timetable_times(book[name])
        return book
    except Exception:
        book.close()
        raise


def book_bytes(book):
    output = BytesIO()
    book.save(output)
    content = output.getvalue()
    if len(content) > 32 * 1024 * 1024:
        raise ValueError("更新后的Excel超过32 MB限制")
    return content


class WorkingCopyWriter:
    def __init__(self, base):
        self.base = base
        self.created = []

    def save(self, c, base_id, content, *, kind="base"):
        from app.base_timetables.exporting import merge_selected

        original = source_content(self.base, c, base_id, kind=kind, original=True, required=False)
        if kind == "base" and original:
            doc = json.loads(self.base._row(c, base_id)[5])
            titles = sorted({e["source"]["sheet"] for e in doc["events"]})
            data = merge_selected(original, content, titles, keep_layout=True)
            content = merge_selected(data, content, sorted(INFRASTRUCTURE), allow_new=True)
        if len(content) > 32 * 1024 * 1024:
            raise ValueError("更新后的受管Excel超过32 MB限制")
        table, key = (
            ("base_tt_workbooks", "base_tt_id") if kind == "base" else ("run_workbooks", "run_id")
        )
        self.base.sources.mkdir(parents=True, exist_ok=True)
        name = f"workbook-{'run-' if kind == 'run' else ''}{uuid4().hex}.xlsx"
        path = self.base.sources / name
        self.created.append(path)
        with path.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        saved = path.read_bytes()
        if token_bytes(saved) != token_bytes(content):
            raise OSError("Excel工作副本写入校验失败")
        for (old,) in c.execute(
            f"SELECT managed_name FROM {table} WHERE {key}=?", [base_id]
        ).fetchall():
            c.execute("INSERT INTO file_cleanup VALUES (?,NULL) ON CONFLICT DO NOTHING", [old])
        c.execute(
            f"INSERT INTO {table} VALUES (?,?,?) ON CONFLICT({key}) "
            "DO UPDATE SET managed_name=excluded.managed_name,digest=excluded.digest",
            [base_id, name, token_bytes(content)],
        )
        return saved


@contextmanager
def working_copy_write(base):
    with base.database.lock:
        writer = WorkingCopyWriter(base)
        try:
            yield writer
        except Exception:
            for path in writer.created:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass  # Startup recovery retries unreferenced working copies.
            raise
        else:
            base.cleanup_files()


def discard_workbook(c, base_id, *, kind="base"):
    table, key = (
        ("base_tt_workbooks", "base_tt_id") if kind == "base" else ("run_workbooks", "run_id")
    )
    for (name,) in c.execute(
        f"SELECT managed_name FROM {table} WHERE {key}=?", [base_id]
    ).fetchall():
        c.execute("INSERT INTO file_cleanup VALUES (?,NULL) ON CONFLICT DO NOTHING", [name])
    c.execute(f"DELETE FROM {table} WHERE {key}=?", [base_id])


def recover_workbooks(base):
    with base.database.lock, base.database.transaction() as c:
        live = {
            r[0]
            for r in c.execute(
                "SELECT managed_name FROM base_tt_workbooks UNION ALL "
                "SELECT managed_name FROM run_workbooks"
            ).fetchall()
        }
        for path in base.sources.glob("workbook-*.xlsx"):
            if (
                re.fullmatch(r"workbook-(?:run-)?[0-9a-f]{32}\.xlsx", path.name)
                and path.name not in live
            ):
                c.execute(
                    "INSERT INTO file_cleanup VALUES (?,NULL) ON CONFLICT DO NOTHING", [path.name]
                )


def display(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y/%m/%d %H:%M:%S")
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return str(value)


def cell_value(text, original):
    if text is None or text == "":
        return None
    if len(text) > 32767:
        raise ValueError("Excel单元格文本超过32767字符")
    if isinstance(original, bool):
        if text.upper() not in {"TRUE", "FALSE"}:
            raise ValueError("布尔单元格请填写TRUE或FALSE")
        return text.upper() == "TRUE"
    if re.match(r"^\d{4}[-/]\d{2}[-/]\d{2}[ T]", text):
        try:
            value = datetime.fromisoformat(text.replace("/", "-"))
            if value.tzinfo:
                raise ValueError("Excel时刻不支持时区")
            return value
        except ValueError as error:
            raise ValueError("完整日期时刻须为YYYY/MM/DD hh:mm:ss") from error
    if isinstance(original, (int, float)) or original is None:
        try:
            number = float(text)
            if math.isfinite(number):
                return int(number) if number.is_integer() else number
        except ValueError:
            pass
    return text


class WorkbookService:
    def __init__(self, editor):
        self.editor = editor
        self.base = editor.base

    def _snapshot(self, c, base_id):
        meta, doc, _, revision = self.editor._load(c, "base", base_id)
        content = source_content(self.base, c, base_id)
        return meta, doc, content, token([revision, token_bytes(content)])

    def _load(self, c, base_id):
        meta, doc, content, revision = self._snapshot(c, base_id)
        return meta, doc, materialize_content(content, doc, meta["date_base"]), revision

    def read(self, base_id, sheet=None, offset=0, limit=25, column_offset=0, column_limit=40):
        with self.base.database.transaction() as c:
            # Capture a consistent revision and immutable bytes; parsing is read-only and
            # must not hold the shared database lock while other endpoints are waiting.
            meta, doc, content, revision = self._snapshot(c, base_id)
        book = materialize_content(content, doc, meta["date_base"])
        try:
            names = workbook_names(book, doc)
            if sheet is not None and sheet not in names:
                raise ValueError("请选择基本图四表中的工作表")
            ws = book[sheet or names[0]]
            last_row, last_column = ws.max_row, ws.max_column
            if last_row * last_column > 2_000_000:
                raise ValueError("工作表超过200万单元格限制")
            width = max(1, min(column_limit, 100))
            column_offset = min(column_offset, (last_column - 1) // width * width)
            first, last = column_offset + 1, min(last_column, column_offset + width)
            size = max(1, min(limit, 2000 // (last - first + 1)))
            headers = next(ws.iter_rows(min_row=1, max_row=1, min_col=first, max_col=last))
            return {
                "revision": revision,
                "name": meta["name"],
                "date_base": meta["date_base"],
                "sheets": names,
                "sheet": ws.title,
                "headers": [display(cell.value) for cell in headers],
                "columns": [get_column_letter(i) for i in range(first, last + 1)],
                "total_rows": max(0, last_row - 1),
                "total_columns": last_column,
                "column_offset": column_offset,
                "column_limit": width,
                "offset": offset,
                "limit": size,
                "rows": [
                    {
                        "row": offset + 2 + index,
                        "cells": [
                            {
                                "value": display(cell.value),
                                "editable": not isinstance(cell, MergedCell),
                                "bold": bool(cell.font.b),
                                "number_format": cell.number_format,
                            }
                            for cell in row
                        ],
                    }
                    for index, row in enumerate(
                        ws.iter_rows(
                            min_row=offset + 2,
                            max_row=min(last_row, offset + 1 + size),
                            min_col=first,
                            max_col=last,
                        )
                    )
                ],
            }
        finally:
            book.close()

    def _validate(self, c, base_id, payload):
        meta, old, book, revision = self._load(c, base_id)
        try:
            if payload.revision != revision:
                raise ImportConflict("基本图数据、位置或Excel副本已变化，请保留草稿并重新载入")
            names, seen = workbook_names(book, old), set()
            for change in payload.changes:
                location = (change.sheet, change.row, change.column)
                if location in seen:
                    raise ValueError("同一单元格不能重复提交")
                seen.add(location)
                if change.sheet not in names:
                    raise ValueError("只能编辑基本图四表")
                ws = book[change.sheet]
                if change.row > ws.max_row or change.column > ws.max_column:
                    raise ValueError("只能编辑已有数据单元格")
                cell = ws.cell(change.row, change.column)
                if isinstance(cell, MergedCell):
                    raise ValueError("合并区域请编辑左上角单元格")
                cell.value = cell_value(change.value, cell.value)
                if isinstance(cell.value, str):
                    cell.data_type = "s"
            content = book_bytes(book)
        finally:
            book.close()
        timetables = [s for s in names if s not in INFRASTRUCTURE]
        parsed = parse_base(
            content,
            date.fromisoformat(meta["date_base"]),
            "preserve",
            selected_sheet=timetables[0] if len(timetables) == 1 else None,
            track_lists=True,
        )
        issues = parsed["issues"] + self.base.validate_scope(
            c, parsed, meta["owner_category_id"], exclude_base=base_id
        )
        dates = {t["train_course_id"]: str(t["train_base_date"]) for t in old["trains"]}
        date_changes = [
            {
                "train_course_id": t["train_course_id"],
                "before": dates[t["train_course_id"]],
                "after": str(t["train_base_date"]),
            }
            for t in parsed["trains"]
            if t["train_course_id"] in dates
            and dates[t["train_course_id"]] != str(t["train_base_date"])
        ]
        report = {
            "can_save": not any(i["severity"] == "error" for i in issues),
            "issues": issues,
            "train_date_changes": date_changes,
            "change_count": len(seen),
            "summary": self.base.summarize(parsed),
            "validation_token": token(
                [
                    payload.model_dump(include={"revision", "changes"}, mode="json"),
                    issues,
                    date_changes,
                ]
            ),
        }
        return report, parsed, old, content, meta

    def validate(self, base_id, payload):
        with self.base.database.transaction() as c:
            return self._validate(c, base_id, payload)[0]

    def save(self, base_id, payload):
        with working_copy_write(self.base) as writer, self.base.database.transaction() as c:
            report, parsed, old, content, meta = self._validate(c, base_id, payload)
            if report["validation_token"] != payload.validation_token:
                raise ImportConflict("校验结果已过期，请对当前单元格修改重新校验")
            if not report["can_save"]:
                raise ValueError("四表校验存在错误，不能保存")
            if (
                any(i["severity"] == "warning" for i in report["issues"])
                and not payload.warnings_confirmed
            ):
                raise ValueError("请核对并确认四表校验警告")
            if report["train_date_changes"] and not payload.train_dates_confirmed:
                raise ValueError("请核对并确认列车基准日变化")
            doc = {
                key: copy.deepcopy(parsed[key])
                for key in (
                    "nodes",
                    "trains",
                    "events",
                    "lines",
                    "members",
                    "minimum_run_times",
                    "issues",
                )
            }
            trains = {t["train_course_id"]: t["id"] for t in old["trains"]}
            events = {(e["train_course_id"], e["node_name"]): e["id"] for e in old["events"]}
            for train in doc["trains"]:
                if train["train_course_id"] in trains:
                    train["id"] = trains[train["train_course_id"]]
            for event in doc["events"]:
                if (event["train_course_id"], event["node_name"]) in events:
                    event["id"] = events[event["train_course_id"], event["node_name"]]
            self.base.identify(c, doc)
            writer.save(c, base_id, content)
            c.execute(
                "UPDATE base_timetables SET document=?,revision=revision+1 WHERE id=?",
                [encode(doc), base_id],
            )
        return {"saved": True, "owner_category_id": meta["owner_category_id"]}

    def export(self, base_id, revision):
        from app.base_timetables.exporting import ExportService

        with working_copy_write(self.base) as writer, self.base.database.transaction() as c:
            meta, doc, book, current = self._load(c, base_id)
            try:
                if current != revision:
                    raise ImportConflict("数据已变化，请重新载入后导出")
                filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", meta["name"])[:100]
            finally:
                book.close()
            content = ExportService(self.editor)._snapshot(
                c,
                "base",
                base_id,
                meta,
                doc,
                doc,
                ["TTT", "LINE_INFO", "NODE_INFO", "MINIMUM_RUN_TIME"],
                "TTT",
            )
            saved = writer.save(c, base_id, content)
            return saved, f"{filename or '基本图'}_{meta['date_base']}.xlsx"
