"""Declarative solver detection and explicitly registered local plotting code."""

from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.config import ROOT

CODE_ROOT = Path(__file__).resolve().parent


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_line: int = Field(ge=1, le=100000)
    end_line: int = Field(ge=1, le=100000)
    match: Literal["any", "all"] = "all"
    keywords: list[str] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def valid_range(self):
        if self.end_line < self.start_line or any(
            not s.strip() or len(s) > 500 for s in self.keywords
        ):
            raise ValueError("识别行范围或关键词无效")
        return self


class Solver(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    label: str = Field(min_length=1, max_length=100)
    case_sensitive: bool = False
    conditions: list[Rule] = Field(min_length=1, max_length=50)
    default_plotter: str | None = None


class Plotter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    label: str = Field(min_length=1, max_length=100)
    solver_type: str
    module: str = Field(pattern=r"^[a-zA-Z_]\w*(\.[a-zA-Z_]\w*)*$")
    function: str = Field(pattern=r"^[a-zA-Z_]\w*$")
    source_file: str
    timeout_seconds: int = Field(default=45, ge=1, le=60)

    @model_validator(mode="after")
    def safe_source(self):
        path = PurePosixPath(self.source_file)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in self.source_file
            or ":" in self.source_file
            or path.suffix != ".py"
        ):
            raise ValueError("作图源文件须为solver_visualizers内的相对.py路径")
        return self

    def available(self):
        module = CODE_ROOT.joinpath(*self.module.split(".")).with_suffix(".py")
        source = (CODE_ROOT / self.source_file).resolve()
        return source.is_relative_to(CODE_ROOT) and source.is_file() and module.is_file()


class Configuration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    solvers: list[Solver] = Field(max_length=50)
    plotters: list[Plotter] = Field(max_length=100)

    @model_validator(mode="after")
    def validate_references(self):
        solvers = {s.id: s for s in self.solvers}
        plotters = {p.id: p for p in self.plotters}
        if (
            "unknown" in solvers
            or len(solvers) != len(self.solvers)
            or len(plotters) != len(self.plotters)
        ):
            raise ValueError("求解器/作图函数ID不能重复，unknown为保留值")
        for plotter in self.plotters:
            if plotter.solver_type not in solvers:
                raise ValueError("作图函数引用了不存在的求解器")
        for solver in self.solvers:
            if solver.default_plotter is not None and (
                solver.default_plotter not in plotters
                or plotters[solver.default_plotter].solver_type != solver.id
            ):
                raise ValueError("默认作图函数不存在或不属于该求解器")
        return self

    def public(self):
        return {
            "solvers": [
                {"id": s.id, "label": s.label, "default_plotter": s.default_plotter}
                for s in self.solvers
            ],
            "plotters": [
                {
                    "id": p.id,
                    "label": p.label,
                    "solver_type": p.solver_type,
                    "source_file": p.source_file,
                    "available": p.available(),
                }
                for p in self.plotters
            ],
        }


class ConfigurationError(Exception):
    pass


def read_configuration(path=None):
    path = path or ROOT / "solver_logs.json"
    try:
        if path.stat().st_size > 1024 * 1024:
            raise ValueError("配置超过1MB")
        content = path.read_bytes()
        return Configuration.model_validate_json(content), sha256(content).hexdigest()
    except (OSError, ValueError, ValidationError) as error:
        raise ConfigurationError(f"solver_logs.json配置无效：{error}") from error


def decode_log(content, encoding):
    try:
        return content.decode("utf-8-sig" if encoding == "utf-8" else encoding)
    except UnicodeDecodeError as error:
        raise ValueError("日志不能按所选编码读取，请切换UTF-8或GB18030") from error


def identify(content, configuration, digest, solver_type="auto"):
    text, encoding = None, None
    for candidate in ("utf-8", "gb18030"):
        try:
            text = decode_log(content, candidate)
            encoding = candidate
            break
        except ValueError:
            pass
    if solver_type != "auto":
        solver = next((s for s in configuration.solvers if s.id == solver_type), None)
        if solver_type != "unknown" and solver is None:
            raise ValueError("未配置该求解器类型")
        return {
            "solver_type": solver_type,
            "default_plotter": solver.default_plotter if solver else None,
            "detection": {"mode": "manual", "encoding": encoding, "config_digest": digest},
        }
    lines = text.splitlines() if text is not None else []
    matches, evidence = [], {}
    for solver in configuration.solvers:
        found = []
        for rule in solver.conditions:
            hit = None
            for number in range(rule.start_line - 1, min(rule.end_line, len(lines))):
                line = lines[number] if solver.case_sensitive else lines[number].casefold()
                words = [
                    word
                    for word in rule.keywords
                    if (word if solver.case_sensitive else word.casefold()) in line
                ]
                if words and (rule.match == "any" or len(words) == len(rule.keywords)):
                    hit = {"line": number + 1, "keywords": words}
                    break
            if hit is None:
                break
            found.append(hit)
        if len(found) == len(solver.conditions):
            matches.append(solver)
            evidence[solver.id] = found
    chosen = matches[0] if len(matches) == 1 else None
    return {
        "solver_type": chosen.id if chosen else "unknown",
        "default_plotter": chosen.default_plotter if chosen else None,
        "detection": {
            "mode": "auto",
            "encoding": encoding,
            "config_digest": digest,
            "matched_solvers": [s.id for s in matches],
            "evidence": evidence,
            "reason": "matched" if chosen else "ambiguous" if matches else "no_match",
        },
    }
