"""Line-scoped track identities: Excel compact fields, separate stored components."""

import json
import re
from dataclasses import dataclass


class TrackFormatError(ValueError):
    def __init__(self, field, message):
        super().__init__(message)
        self.field = field


def positive(value):
    if type(value) is not int or not 1 <= value <= 2147483647:
        raise ValueError("股道编号须为正整数")
    return value


def stop_list(value):
    if not isinstance(value, list):
        raise ValueError("到发线须为方括号编号列表")
    numbers = [positive(item) for item in value]
    if len(numbers) != len(set(numbers)):
        raise ValueError("同一方向到发线列表有重复编号")
    return sorted(numbers)


@dataclass(frozen=True)
class DirectionTracks:
    stop_tracks: tuple[int, ...]
    main_track: int | None

    @property
    def numbers(self):
        return sorted(set(self.stop_tracks) | ({self.main_track} if self.main_track else set()))

    def public(self):
        return {"stop_tracks": list(self.stop_tracks), "main_track": self.main_track}


def parse_direction(value):
    if not isinstance(value, str):
        raise ValueError("股道须为列表字符串 [10,11,12] 或 [10,11,12]/9，不能用数量代替")
    parts = value.strip().split("/")
    if len(parts) > 2 or (len(parts) == 2 and not re.fullmatch(r"[0-9]+", parts[1].strip())):
        raise ValueError("股道格式须为 [10,11,12] 或 [10,11,12]/9；没有正线请省略整个/正线号")
    try:
        items = stop_list(json.loads(parts[0].strip()))
        main = positive(int(parts[1].strip())) if len(parts) == 2 else None
    except (ValueError, TypeError) as error:
        raise ValueError(f"股道格式错误：{error}；须为 [10,11,12] 或 [10,11,12]/9") from error
    # A main track may also appear in stop_tracks; its two roles share one identity.
    return DirectionTracks(tuple(items), main)


def read_direction(member, prefix):
    stop_key, main_key = f"{prefix}_STOP_TRACKS", f"{prefix}_MAIN_TRACK"
    if member.get("TRACKS_SCHEMA_VERSION") == 2:
        if member.get(stop_key) is None:
            raise ValueError(f"{prefix}方向股道信息缺失")
        main = member.get(main_key)
        return DirectionTracks(
            tuple(stop_list(member[stop_key])), positive(main) if main is not None else None
        )
    field = "DB_TRACKS" if prefix == "DB" else "UB_TRACKS"
    value = member.get(field)
    if value is None and prefix == "UB":
        value = member.get("UP_TRACKS")
    if value is None or value == "":
        raise ValueError(f"{prefix}方向股道信息缺失")
    return parse_direction(value)


def member_tracks(member):
    down = read_direction(member, "DB")
    up = read_direction(member, "UB")
    return down, up, sorted(set(down.numbers) | set(up.numbers))


def normalize_track_fields(row):
    result = {"TRACKS_SCHEMA_VERSION": 2}
    if row.get("UB_TRACKS") is None and row.get("UP_TRACKS") is not None:
        row["UB_TRACKS"] = row["UP_TRACKS"]
    for prefix in ("DB", "UB"):
        field = f"{prefix}_TRACKS"
        value = row.get(field)
        if value is None or value == "":
            result[f"{prefix}_STOP_TRACKS"] = None
            result[f"{prefix}_MAIN_TRACK"] = None
            continue
        try:
            direction = parse_direction(value)
            if prefix == "UB" and row.get("UP_TRACKS") is not None:
                try:
                    alias = parse_direction(row["UP_TRACKS"])
                except ValueError as error:
                    raise TrackFormatError("UP_TRACKS", str(error)) from error
                if alias != direction:
                    raise TrackFormatError(
                        "UP_TRACKS", "UP_TRACKS与UB_TRACKS的到发线或正线配置冲突"
                    )
        except TrackFormatError:
            raise
        except ValueError as error:
            raise TrackFormatError(field, str(error)) from error
        result[f"{prefix}_STOP_TRACKS"] = list(direction.stop_tracks)
        result[f"{prefix}_MAIN_TRACK"] = direction.main_track
    return result


def excel_track_field(member, prefix):
    if member.get("TRACKS_SCHEMA_VERSION") != 2:
        return member.get(f"{prefix}_TRACKS")
    if member.get(f"{prefix}_STOP_TRACKS") is None and member.get(f"{prefix}_MAIN_TRACK") is None:
        return None
    direction = read_direction(member, prefix)
    suffix = f"/{direction.main_track}" if direction.main_track is not None else ""
    return json.dumps(list(direction.stop_tracks), separators=(",", ":")) + suffix


def check_event_track(members, node_name, track):
    """OR across all NODE_INFO memberships of this station in the effective BaseTT."""
    matching = [member for member in members if member.get("node_name") == node_name]
    lines = sorted({member["line_ind"] for member in matching})
    known = set()
    incomplete = not matching
    for member in matching:
        for prefix in ("DB", "UB"):
            try:
                known.update(read_direction(member, prefix).numbers)
            except ValueError:
                incomplete = True
    if track in known:
        return "valid", sorted(known), lines
    return ("unknown" if incomplete else "invalid"), sorted(known), lines


def invalid_track_message(track, line_inds, tracks):
    lines = ",".join(str(value) for value in sorted(set(line_inds)))
    sample = "、".join(str(value) for value in tracks[:40]) or "空集合"
    if len(tracks) > 40:
        sample += "等"
    return f"股道{track}不在该站所属线路({lines})的到发线与正线集合中；可用股道：{sample}"
