"""Preserve SEQ adjacency and missing-value gaps when constructing plot geometry."""

from collections import defaultdict

from app.diagram.axis import number, problem


def build_series(meta, document, axis):
    stations = {station["node_id"]: station for station in axis["stations"]}
    visits = defaultdict(list)
    for event in document["events"]:
        visits[event["train_id"]].append(event)
    series, issues = [], []
    for train in document["trains"]:
        full = sorted(
            visits[train["id"]], key=lambda event: number(event["visit_seq"]) or 2147483648
        )
        selected = [event for event in full if event["node_id"] in stations]
        if not selected:
            continue
        course = train["train_course_id"]
        context = {
            "train_id": train["id"],
            "train_course_id": course,
            "object_type": meta["object_type"],
            "object_id": meta["id"],
        }
        seqs = [number(event["visit_seq"]) for event in full]
        if None in seqs or len(set(seqs)) != len(seqs):
            issues.append(
                problem("sequence", f"{course} 的SEQ缺失或重复，不能确定运行线", **context)
            )
            continue
        order = [stations[event["node_id"]]["node_seq_of_line"] for event in selected]
        signs = {1 if b > a else -1 for a, b in zip(order, order[1:]) if b != a}
        direction = "down" if signs == {1} else "up" if signs == {-1} else "unknown"
        if direction == "unknown":
            issues.append(
                problem(
                    "direction", f"{course} 的方向不能按当前简单站序唯一判断", "warning", **context
                )
            )
        points, segments, event_data = [], [], []
        point_ids = {}
        for index, event in enumerate(full):
            station = stations.get(event["node_id"])
            if not station:
                continue
            if event["node_name"] != station["node_name"]:
                issues.append(
                    problem("event_identity", f"{course} 的节点身份与线路节点不一致", **context)
                )
                continue
            event_data.append(
                {
                    k: event[k]
                    for k in (
                        "id",
                        "node_id",
                        "node_name",
                        "visit_seq",
                        "track_code",
                        "arrival",
                        "departure",
                    )
                }
                | {
                    "node_name_chn": station["node_name_chn"],
                    "source": {
                        k: v
                        for k, v in event.get("source", {}).items()
                        if k in ("sheet", "row", "first_column")
                    },
                }
            )
            if (index > 0 and event["arrival"] is None) or (
                index < len(full) - 1 and event["departure"] is None
            ):
                issues.append(
                    problem(
                        "missing_time",
                        f"{course} 在{station['node_name_chn']}缺少到发时刻，相关线段断开",
                        "warning",
                        event_id=event["id"],
                        **context,
                    )
                )
            for field in ("arrival", "departure"):
                value = event[field]
                if value is None:
                    continue
                seconds = value.get("seconds")
                if type(seconds) is not int or seconds < 0:
                    issues.append(
                        problem(
                            "invalid_time",
                            f"{course} 的到发累计秒无效",
                            event_id=event["id"],
                            **context,
                        )
                    )
                    continue
                point_ids[(event["id"], field)] = len(points)
                points.append(
                    {"event_id": event["id"], "field": field, "seconds": seconds, "y": station["y"]}
                )

        def connect(left, right, kind):
            a, b = point_ids.get(left), point_ids.get(right)
            if a is None or b is None:
                return
            anomaly = points[b]["seconds"] < points[a]["seconds"]
            if anomaly:
                issues.append(
                    problem(
                        "time_order",
                        f"{course} 存在时刻倒置，保留实际点线供核对",
                        "warning",
                        **context,
                    )
                )
            segments.append({"from": a, "to": b, "kind": kind, "anomaly": anomaly})

        for event in selected:
            connect((event["id"], "arrival"), (event["id"], "departure"), "dwell")
        for left, right in zip(full, full[1:]):
            if right["visit_seq"] != left["visit_seq"] + 1:
                issues.append(
                    problem(
                        "sequence_gap",
                        f"{course} 的SEQ不连续，缺口处不连接运行线",
                        "warning",
                        **context,
                    )
                )
                continue
            connect((left["id"], "departure"), (right["id"], "arrival"), "travel")
        series.append(
            {
                "key": f"{meta['object_type']}:{meta['id']}:{train['id']}",
                "object_type": meta["object_type"],
                "object_id": meta["id"],
                "object_name": meta["name"],
                "train_id": train["id"],
                "train_course_id": course,
                "train_base_date": str(train["train_base_date"]),
                "direction": direction,
                "points": points,
                "segments": segments,
                "events": event_data,
            }
        )
    return series, issues
