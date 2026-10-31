"""Read-only delays against the effective base, with explicit unmatched cells."""

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from app.base_timetables.ordering import editor_order


def calculate_delays(meta, document, base_meta, base_document, stations, revision):
    trains = defaultdict(list)
    for train in base_document["trains"]:
        trains[(train["train_course_id"], str(train["train_base_date"]))].append(train)
    base_visits = defaultdict(list)
    run_visits = defaultdict(list)
    for event in base_document["events"]:
        base_visits[event["train_id"]].append(event)
    for event in document["events"]:
        run_visits[event["train_id"]].append(event)
    cells, rows, issues, endpoints = [], {}, [], []
    station_by_id = {s["id"]: s for s in stations}
    time_base = datetime.combine(date.fromisoformat(str(meta["date_base"])), time())
    offset = (
        date.fromisoformat(str(meta["date_base"])) - date.fromisoformat(str(base_meta["date_base"]))
    ).days * 86400
    for train in document["trains"]:
        candidates = trains[(train["train_course_id"], str(train["train_base_date"]))]
        matched = candidates[0] if len(candidates) == 1 else None
        lookup = {}
        base_order = []
        if matched:
            counts = defaultdict(int)
            events = base_visits[matched["id"]]
            if len({e["visit_seq"] for e in events}) != len(events):
                issues.append(f"{train['train_course_id']} 基本图SEQ重复，不能确定经停匹配")
            else:
                base_order = sorted(events, key=lambda e: e["visit_seq"])
                for event in base_order:
                    counts[event["node_name"]] += 1
                    lookup[(event["node_name"], counts[event["node_name"]])] = event
        else:
            issues.append(
                f"{train['train_course_id']} · {train['train_base_date']} 未找到唯一基本图列车"
            )
        events = run_visits[train["id"]]
        ambiguous = len({e["visit_seq"] for e in events}) != len(events)
        counts = defaultdict(int)
        ordered = sorted(events, key=lambda e: e["visit_seq"])
        boundary = {
            "train_id": train["id"],
            "origin_row_key": None,
            "terminal_row_key": None,
            "origin_departure": None,
            "terminal_arrival": None,
            "origin_reason": "无可匹配的完整始发访问",
            "terminal_reason": "无可匹配的完整终到访问",
        }
        for index, event in enumerate(ordered):
            counts[event["node_name"]] += 1
            occurrence = counts[event["node_name"]]
            other = lookup.get((event["node_name"], occurrence)) if not ambiguous else None
            station = station_by_id.get(event["node_id"], {"node_name_chn": event["node_name"]})
            row_key = f"{event['node_id']}:{occurrence}"
            rows[row_key] = {
                "key": row_key,
                "station_id": event["node_id"],
                "occurrence": occurrence,
                "node_name": event["node_name"],
                "node_name_chn": station["node_name_chn"],
            }
            cell = {"row_key": row_key, "train_id": train["id"], "visit_seq": event["visit_seq"]}
            for field in ("arrival", "departure"):
                actual = event[field]
                planned = other[field] if other else None
                cell[field + "_time"] = (
                    (time_base + timedelta(seconds=actual["seconds"])).isoformat()
                    if actual is not None
                    else None
                )
                cell[field] = (
                    actual["seconds"] + offset - planned["seconds"]
                    if actual is not None and planned is not None
                    else None
                )
                cell[field + "_reason"] = (
                    "SEQ重复，无法匹配"
                    if ambiguous
                    else "基本图列车未唯一匹配"
                    if not matched
                    else "基本图无对应经停"
                    if other is None
                    else "run缺少时刻"
                    if actual is None
                    else "基本图缺少时刻"
                    if planned is None
                    else ""
                )
            cells.append(cell)
            if not ambiguous and other is not None and base_order:
                for is_boundary, expected, prefix, field in (
                    (index == 0, base_order[0], "origin", "departure"),
                    (index == len(ordered) - 1, base_order[-1], "terminal", "arrival"),
                ):
                    if is_boundary and other is expected:
                        boundary[prefix + "_row_key"] = row_key
                        boundary[prefix + "_" + field] = cell[field]
                        boundary[prefix + "_reason"] = cell[field + "_reason"]
        endpoints.append(boundary)
    order = {s["id"]: i for i, s in enumerate(stations)}
    return {
        "version": 1,
        "object": meta,
        "base": base_meta,
        "revision": revision,
        "unit": "seconds",
        "stations": stations,
        "trains": document["trains"],
        "rows": sorted(
            rows.values(), key=lambda r: (order.get(r["station_id"], 100000), r["occurrence"])
        ),
        "cells": cells,
        "endpoints": endpoints,
        "issues": list(dict.fromkeys(issues)),
        "method": "run到发绝对时刻−绑定基本图到发绝对时刻；车次+列车基准日、车站+第几次经停匹配",
    }


def read_delays(editor, run_id):
    with editor.database.transaction() as c:
        meta, doc, infra, revision = editor._load(c, "run", run_id)
        base_id = meta["effective_base"]["base_tt_id"]
        if not base_id:
            raise ValueError("当前run未绑定有效基本图，暂不能计算延误")
        if not meta["date_base"]:
            raise ValueError("当前run尚无正式时刻数据和基准日期")
        base_meta, base_doc, _, _ = editor._load(c, "base", base_id)
        stations, order = editor_order(c, editor.base, "run", run_id, doc, infra)
        train_order = {tid: i for i, tid in enumerate(order["trains"])}
        doc["trains"].sort(key=lambda train: train_order.get(train["id"], len(train_order)))
    return calculate_delays(meta, doc, base_meta, base_doc, stations, revision)
