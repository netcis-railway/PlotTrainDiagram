"""Read explicit final result labels without confusing incumbent values with bounds."""

import math
import re

from app.solver_visualizers.configuration import decode_log

NUMBER = r"[+-]?(?:\d{1,3}(?:,\d{3})+(?:\.\d*)?|\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
VALUE = re.compile(rf"^(?:{NUMBER})$")
OBJECTIVE = re.compile(
    r"^\s*(?:Best objective|Final objective(?: value)?|Objective(?: value)?|"
    r"最优目标(?:函数)?值|目标函数(?:最优)?值|目标值)(?:\s*[:=：]\s*|\s+)(.+?)"
    r"(?:,\s*best bound\b.*)?$",
    re.IGNORECASE,
)
GUROBI_TIME = re.compile(rf"^\s*Explored\b.*\bin\s+({NUMBER})\s+seconds?\b", re.I)
TIME = re.compile(
    rf"^\s*(?:Solving|Solve|Solution|Total solve|Optimization|Total solution)\s+time"
    rf"(?:\s*\((?:s|sec|seconds?)\))?\s*[:=：]\s*({NUMBER})"
    rf"\s*(milliseconds?|ms|seconds?|secs?|s|minutes?|mins?|min|hours?|hrs?|h)?\s*$",
    re.I,
)
CHINESE_TIME = re.compile(
    rf"^\s*(?:求解时间|求解耗时|总求解时间)\s*[:=：]\s*({NUMBER})\s*(毫秒|秒|分钟|小时)?\s*$"
)


def finite_number(text):
    text = text.strip()
    if not VALUE.fullmatch(text):
        return None
    value = float(text.replace(",", ""))
    return value if math.isfinite(value) else None


def extract_results(content, encoding):
    result = {"best_objective": None, "solve_seconds": None}
    evidence = {"version": 1, "encoding": encoding, "objective_line": None, "time_line": None}
    if encoding:
        for number, line in enumerate(decode_log(content, encoding).splitlines(), 1):
            if re.match(r"^\s*(?:Gurobi Optimizer version|Optimize a model with)\b", line):
                result.update(best_objective=None, solve_seconds=None)
                evidence.update(objective_line=None, time_line=None)
            if re.search(
                r"\b(?:Infeasible model|Model is infeasible|Unbounded model|"
                r"No feasible solution)\b",
                line,
                re.I,
            ):
                result["best_objective"] = None
                evidence["objective_line"] = number
            match = OBJECTIVE.search(line)
            if match:
                # A later explicit missing result clears an earlier optimization result.
                result["best_objective"] = finite_number(match[1])
                evidence["objective_line"] = number
            match = GUROBI_TIME.search(line) or TIME.search(line) or CHINESE_TIME.search(line)
            if match:
                value = finite_number(match[1])
                unit = (match[2] if match.lastindex == 2 else "seconds") or "seconds"
                factor = (
                    0.001
                    if unit.lower() in {"ms", "millisecond", "milliseconds", "毫秒"}
                    else (
                        60
                        if unit.lower() in {"min", "mins", "minute", "minutes", "分钟"}
                        else (
                            3600
                            if unit.lower() in {"h", "hr", "hrs", "hour", "hours", "小时"}
                            else 1
                        )
                    )
                )
                value = value * factor if value is not None else None
                result["solve_seconds"] = (
                    value if value is not None and value >= 0 and math.isfinite(value) else None
                )
                evidence["time_line"] = number
    return {
        **result,
        "objective_source": "solver-log" if result["best_objective"] is not None else "unavailable",
        "time_source": "solver-log" if result["solve_seconds"] is not None else "unavailable",
        "result_extraction": evidence,
    }
