"""An immutable line axis from NODE_SEQ_OF_LINE and directed PASS/PASS times."""

from app.ingest.base_parser import integer, seconds


def number(value):
    try:
        return integer(value)
    except (ValueError, TypeError, OverflowError):
        return None


def problem(code, message, severity="error", **context):
    return {"code": code, "severity": severity, "message": message, **context}


def build_axis(infrastructure, line_ind):
    definitions = [
        line for line in infrastructure.get("lines", []) if number(line.get("LINE_IND")) == line_ind
    ]
    errors = []
    if len(definitions) != 1:
        return {"stations": [], "intervals": [], "total": 0}, [
            problem("line_definition", "所选线路定义缺失或重复，请核对有效基本图LINE_INFO")
        ]
    known = {node["node_name"]: node for node in infrastructure.get("nodes", [])}
    members = [
        m
        for m in infrastructure.get("members", [])
        if number(m.get("line_ind", m.get("LINE_IND"))) == line_ind
    ]
    stations = []
    for member in members:
        name = member.get("node_name", member.get("NODE_NAME"))
        node = known.get(name, {})
        seq = number(member.get("NODE_SEQ_OF_LINE"))
        if not seq or not node.get("id") or not node.get("node_code"):
            errors.append(
                problem(
                    "station_order",
                    "车站缺少有效站序或稳定节点身份",
                    node_name=name,
                    node_seq_of_line=member.get("NODE_SEQ_OF_LINE"),
                )
            )
            continue
        if (
            member.get("NODE_CODE") != node["node_code"]
            or member.get("NODE_NAME_CHN") != node["node_name_chn"]
        ):
            errors.append(
                problem("station_identity", "线路成员与基本图节点名称/编码不一致", node_name=name)
            )
        stations.append(
            {
                "node_id": node["id"],
                "node_name": name,
                "node_name_chn": node["node_name_chn"],
                "node_code": node["node_code"],
                "node_seq_of_line": seq,
                "y": 0,
            }
        )
    stations.sort(key=lambda station: station["node_seq_of_line"])
    seqs = [station["node_seq_of_line"] for station in stations]
    if len(stations) < 2:
        errors.append(problem("too_few_stations", "该线路有效车站不足两个，未生成运行图"))
    if len({s["node_id"] for s in stations}) != len(stations) or seqs != list(
        range(1, len(stations) + 1)
    ):
        errors.append(
            problem(
                "station_order", "NODE_SEQ_OF_LINE须唯一且连续为1至N；不能用NODE_IND或Excel行序代替"
            )
        )
    intervals = []
    total = 0
    for left, right in zip(stations, stations[1:]):
        records = [
            m
            for m in infrastructure.get("minimum_run_times", [])
            if m.get("LINK_START_NODE_CODE") == left["node_code"]
            and m.get("LINK_END_NODE_CODE") == right["node_code"]
            and m.get("START_ACTIVITY") == "PASS"
            and m.get("END_ACTIVITY") == "PASS"
        ]
        label = f"{left['node_name_chn']} → {right['node_name_chn']}"
        if len(records) != 1:
            errors.append(
                problem("axis_interval", f"{label} 的正向PASS→PASS主最小运行时间缺失或有歧义")
            )
            continue
        record = records[0]
        try:
            duration = seconds(record.get("MINIMUM_RUN_TIME"))
            if duration <= 0 or duration != integer(record.get("MINIMUM_RUN_TIME_SEC")):
                raise ValueError("主时间与秒值须一致且为正")
            if record.get("seconds", duration) != duration:
                raise ValueError("规范化最小运行时间不一致")
        except (ValueError, TypeError, OverflowError) as error:
            errors.append(problem("axis_interval", f"{label}：{error}"))
            continue
        total += duration
        right["y"] = total
        intervals.append(
            {
                "from_node_id": left["node_id"],
                "to_node_id": right["node_id"],
                "seconds": duration,
                "source": {
                    "sheet": record.get("_sheet", "MINIMUM_RUN_TIME"),
                    "row": record.get("_row"),
                },
            }
        )
    axis = {
        "stations": stations if not errors else [],
        "intervals": intervals,
        "total": total,
        "unit": "equivalent_seconds",
        "order_field": "NODE_SEQ_OF_LINE",
    }
    return axis, errors
