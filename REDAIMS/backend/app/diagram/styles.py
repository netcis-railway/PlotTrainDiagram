"""Reload a local style JSON while keeping the last valid configuration."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import ROOT
from app.diagram.axis import problem

Color = str


class TrainStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    color: Color | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    width: float | None = Field(default=None, ge=0.5, le=8)
    dashed: bool = False


class PlotStyles(BaseModel):
    model_config = ConfigDict(extra="forbid")
    down: Color = Field(default="#d64444", pattern=r"^#[0-9a-fA-F]{6}$")
    up: Color = Field(default="#287ac4", pattern=r"^#[0-9a-fA-F]{6}$")
    unknown: Color = Field(default="#8c67c6", pattern=r"^#[0-9a-fA-F]{6}$")
    base: Color = Field(default="#172438", pattern=r"^#[0-9a-fA-F]{6}$")
    base_dark: Color = Field(default="#d7e2f1", pattern=r"^#[0-9a-fA-F]{6}$")
    grid: Color = Field(default="#5baf79", pattern=r"^#[0-9a-fA-F]{6}$")
    highlight: Color = Field(default="#f5c842", pattern=r"^#[0-9a-fA-F]{6}$")
    width: float = Field(default=1.5, ge=0.5, le=8)
    point_radius: float = Field(default=2.5, ge=1, le=6)
    grid_minutes: int = Field(default=10, ge=1, le=60)
    font_size: int = Field(default=12, ge=8, le=24)
    track_gap: float = Field(default=1, ge=0.5, le=12)
    track_yita_seconds: float = Field(default=1, ge=0, le=3600)
    train_styles: dict[str, TrainStyle] = Field(default_factory=dict)


class StyleLoader:
    def __init__(self, path: Path | None = None):
        self.path = path or ROOT / "diagram_styles.json"
        self.current = PlotStyles()

    def read(self):
        issues = []
        if self.path.is_file():
            try:
                if self.path.stat().st_size > 1024 * 1024:
                    raise ValueError("样式文件超过1MB")
                self.current = PlotStyles.model_validate_json(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError, ValidationError) as error:
                issues.append(
                    problem(
                        "style_config",
                        f"绘图样式配置未通过校验，沿用上次有效样式：{error}",
                        "warning",
                    )
                )
        return self.current.model_dump(), issues
