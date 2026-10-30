from pathlib import Path

import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseModel):
    solver_log_config: Path = ROOT / "solver_logs.json"
    database: Path = ROOT / "data/rail_data.duckdb"
    source_files: Path | None = None
    staging: Path | None = None
    logs: Path | None = None
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)


def load_settings(path: Path | None = None) -> Settings:
    path = path or ROOT / "config.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    database = Path(raw.get("storage", {}).get("database", "data/rail_data.duckdb"))
    if not database.is_absolute():
        database = path.parent / database
    paths = {}
    for key in ("source_files", "staging", "logs"):
        value = Path(raw.get("storage", {}).get(key, f"data/{key}"))
        paths[key] = value if value.is_absolute() else path.parent / value
    return Settings(database=database, **paths, **raw.get("server", {}))
