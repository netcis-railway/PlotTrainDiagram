"""Track resources and read-only occupation routes on a selected line."""

from app.diagram.axis import number, problem
from app.ingest.tracks import member_tracks


def track_resources(infrastructure, axis, line_ind):
    resources = []
    for station in axis["stations"]:
        context = {
            "line_ind": line_ind,
            "node_id": station["node_id"],
            "node_name": station["node_name"],
            "node_name_chn": station["node_name_chn"],
        }
        matches = [
            m
            for m in infrastructure.get("members", [])
            if number(m.get("line_ind", m.get("LINE_IND"))) == line_ind
            and m.get("node_name", m.get("NODE_NAME")) == station["node_name"]
        ]
        resource = context | {
            "can_expand": False,
            "tracks": [],
            "track_count": 0,
            "directions": {},
            "issues": [],
        }
        try:
            if len(matches) != 1:
                raise ValueError("所选线路/车站的股道记录缺失或重复，不能借用其他线路或到发场")
            down, up, tracks = member_tracks(matches[0])
            resource["directions"] = {"down": down.public(), "up": up.public()}
            for track in tracks:
                roles = [
                    key
                    for key, applies in (
                        ("down_stop", track in down.stop_tracks),
                        ("down_main", track == down.main_track),
                        ("up_stop", track in up.stop_tracks),
                        ("up_main", track == up.main_track),
                    )
                    if applies
                ]
                resource["tracks"].append({"number": track, "roles": roles})
            resource["track_count"] = len(tracks)
            resource["can_expand"] = bool(tracks)
            if not tracks:
                resource["issues"].append(
                    problem(
                        "track_resources",
                        f"{station['node_name_chn']}：股道集合明确为空，暂无可展开股道",
                        "warning",
                        **context,
                    )
                )
        except ValueError as error:
            resource["issues"].append(
                problem(
                    "track_resources", f"{station['node_name_chn']}：{error}", "warning", **context
                )
            )
        resources.append(resource)
    return resources


def pass_through(train, event, resource, arrival_index, departure_index, warn):
    """Connect equal-time boundaries and mark the assigned track without yita offsets."""
    points = train["points"]
    tracks = [track["number"] for track in resource["tracks"]]
    track = event["track_code"]
    usage = event["track_usage"]
    assigned = type(track) is int and track in tracks
    if assigned:
        level = (len(tracks) - 1) / 2 - tracks.index(track)
        seconds = points[arrival_index]["seconds"]
        usage.update(
            adopted_track=track, start_seconds=seconds, end_seconds=seconds, can_occupy=True
        )
    else:
        main_tracks = {
            direction["main_track"]
            for direction in resource["directions"].values()
            if direction.get("main_track") in tracks
        }
        levels = [(len(tracks) - 1) / 2 - tracks.index(main) for main in main_tracks]
        level = sum(levels) / len(levels) if levels else 0
        warn(
            "track_missing" if track is None else "track_invalid",
            "未指定股道，通过点以红色三角形标记未判定股道"
            if track is None
            else "股道不在所选线路/车站的真实集合中，通过点以红色三角形标记未判定股道",
        )
        if not levels:
            warn("track_main_missing", "本站未配置正线，未判定股道标记显示在股道展开区中心")
    train["segments"].append(
        {"from": arrival_index, "to": departure_index, "kind": "track_pass", "anomaly": False}
    )
    points.append(
        {
            **points[arrival_index],
            "track_offset": level,
            "calculated": True,
            "usage_kind": "pass_track" if assigned else "track_unassigned",
        }
    )


def expand_track_usage(series, resources, requested, yita):
    by_node = {resource["node_id"]: resource for resource in resources}
    unknown = set(requested) - set(by_node)
    if unknown:
        raise ValueError("拟展开车站不属于当前线路，请重新选择")
    issues, expanded = [], []
    for node_id in dict.fromkeys(requested):
        resource = by_node[node_id]
        if resource["can_expand"]:
            expanded.append(node_id)
        issues.extend(resource["issues"])
    for train in series:
        points, segments = train["points"], train["segments"]
        point_ids = {(p["event_id"], p["field"]): i for i, p in enumerate(points)}
        expanded_events = {e["id"] for e in train["events"] if e["node_id"] in expanded}
        # A merged dwell segment must never remain beneath an expanded occupation route.
        train["segments"] = [
            s
            for s in segments
            if not (s["kind"] == "dwell" and points[s["from"]]["event_id"] in expanded_events)
        ]
        for event in train["events"]:
            if event["id"] not in expanded_events:
                continue
            resource = by_node[event["node_id"]]
            tracks = [t["number"] for t in resource["tracks"]]
            context = {
                k: train[k]
                for k in (
                    "object_type",
                    "object_id",
                    "train_id",
                    "train_course_id",
                    "train_base_date",
                )
            }
            context |= {
                "event_id": event["id"],
                "node_id": event["node_id"],
                "node_name": event["node_name"],
                "node_name_chn": event["node_name_chn"],
                "line_ind": resource["line_ind"],
                "visit_seq": event["visit_seq"],
                "source": event["source"],
                "original_track": event["track_code"],
            }

            def warn(code, message, **extra):
                issues.append(
                    problem(
                        code,
                        f"{train['train_course_id']} {event['node_name_chn']}：{message}",
                        "warning",
                        **context,
                        **extra,
                    )
                )

            direction = train["direction"]
            ai, di = (
                point_ids.get((event["id"], "arrival")),
                point_ids.get((event["id"], "departure")),
            )
            passing = (
                ai is not None and di is not None and points[ai]["seconds"] == points[di]["seconds"]
            )
            usage = {
                "direction": direction,
                "passing": passing,
                "original_track": event["track_code"],
                "adopted_track": None,
                "defaulted": False,
                "start_seconds": None,
                "end_seconds": None,
                "can_occupy": False,
            }
            event["track_usage"] = usage
            if direction == "unknown":
                warn("track_direction", "方向未定，保留原始到发点，不猜测上下到发边界")
                if passing:
                    pass_through(train, event, resource, ai, di, warn)
                continue
            half = (len(tracks) + 1) / 2
            offsets = {
                "arrival": -half if direction == "down" else half,
                "departure": half if direction == "down" else -half,
            }
            for field, offset in offsets.items():
                index = point_ids.get((event["id"], field))
                if index is not None:
                    points[index]["track_offset"] = offset
            if passing:
                pass_through(train, event, resource, ai, di, warn)
                continue
            track = event["track_code"]
            if track is None:
                if 1 not in tracks:
                    warn("track_missing", "股道为空且实际集合不含1，仅保留到发点，不虚造股道")
                    continue
                track = 1
                usage["defaulted"] = True
                warn(
                    "track_default",
                    "股道为空，本次绘图采用实际存在的1号股道，不回写数据",
                    adopted_track=1,
                )
            if type(track) is not int or track not in tracks:
                warn(
                    "track_invalid",
                    "股道不在所选线路/车站的真实集合中，仅保留到发点",
                    adopted_track=track,
                )
                continue
            usage["adopted_track"] = track
            start = points[ai]["seconds"] + track * yita if ai is not None else None
            end = points[di]["seconds"] - track * yita if di is not None else None
            usage.update(start_seconds=start, end_seconds=end)
            if start is not None and end is not None and start > end:
                warn(
                    "track_time_order",
                    "按A+k×yita、D−k×yita计算的占用区间倒置，仅保留实际到发点，不交换或补造时间",
                    adopted_track=track,
                    start_seconds=start,
                    end_seconds=end,
                )
                continue
            if ai is None or di is None:
                warn(
                    "track_missing_time",
                    "到达或出发缺失，仅绘制可确定的进路部分，不补造完整占用区间",
                    adopted_track=track,
                )
            level = (len(tracks) - 1) / 2 - tracks.index(track)

            def route_point(original_index, seconds, kind):
                if original_index is None:
                    return None
                p = points[original_index]
                result = len(points)
                points.append(
                    {
                        "event_id": event["id"],
                        "field": p["field"],
                        "seconds": seconds,
                        "y": p["y"],
                        "track_offset": level,
                        "calculated": True,
                        "usage_kind": kind,
                    }
                )
                return result

            entry = route_point(ai, start, "track_entry")
            exit_ = route_point(di, end, "track_exit")
            for left, right, kind in (
                (ai, entry, "track_enter"),
                (entry, exit_, "track_occupancy"),
                (exit_, di, "track_leave"),
            ):
                if left is not None and right is not None:
                    train["segments"].append(
                        {"from": left, "to": right, "kind": kind, "anomaly": False}
                    )
            usage["can_occupy"] = entry is not None and exit_ is not None
    return expanded, issues
