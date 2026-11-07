from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
import math


Point = tuple[float, float]
Polygon = list[Point]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Config(Record):
    provider: Literal["replicate"]
    input_dir: Path
    artifact_dir: Path
    reading_convention: Literal["ltr", "rtl"] = "ltr"
    target_aspect_ratio: Literal["16:9", "9:16"] = "16:9"
    target_resolution: tuple[int, int]
    layout_model: str
    video_model: str
    layout_settings: dict
    llm_model: str
    llm_settings: dict = Field(default_factory=dict)
    prompt_completion_limits: dict[str, int] = Field(default_factory=dict)
    video_settings: dict = Field(default_factory=dict)
    allow_model_execution: bool = False
    max_new_predictions: int = Field(ge=0, default=0)
    prediction_timeout_seconds: int = Field(gt=0, default=300)
    poll_seconds: float = Field(gt=0, default=2)
    minimum_panel_area_fraction: float = Field(gt=0, lt=1, default=0.025)
    white_threshold: int = Field(ge=0, le=255, default=235)
    development_pages: list[str]


class PanelGeometry(Record):
    key: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    layout_polygon: Polygon = Field(min_length=3)
    content_polygons: list[Polygon] = Field(min_length=1)
    excluded_polygons: list[Polygon] = Field(default_factory=list)
    overlap_keys: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_geometry(self):
        for polygon in [self.layout_polygon, *self.content_polygons, *self.excluded_polygons]:
            if len(polygon) < 3 or any(not math.isfinite(v) for point in polygon for v in point):
                raise ValueError("Polygons require at least three finite points")
            area = abs(sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(polygon, polygon[1:] + polygon[:1]))) / 2
            if area <= 0:
                raise ValueError("Polygon has zero area")
        return self


class Layout(Record):
    schema_version: Literal["1.0"] = "1.0"
    coordinate_system: Literal["original_pixels", "normalized_1000"]
    panels: list[PanelGeometry] = Field(min_length=1)
    reading_order: list[str] = Field(min_length=1)
    uncertain_order_pairs: list[tuple[str, str]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_order(self):
        keys = [panel.key for panel in self.panels]
        if len(set(keys)) != len(keys) or len(self.reading_order) != len(keys) or set(keys) != set(self.reading_order):
            raise ValueError("Reading order must contain every unique panel key exactly once")
        for pair in self.uncertain_order_pairs:
            if pair[0] == pair[1] or not set(pair).issubset(keys):
                raise ValueError("Uncertain order pairs must reference two distinct panels")
        for panel in self.panels:
            if not set(panel.overlap_keys).issubset(set(keys) - {panel.key}):
                raise ValueError("Overlaps must reference other panels")
        return self


class Page(Record):
    schema_version: Literal["1.0"] = "1.0"
    page_id: str
    sequence_index: int
    source_file: str
    source_sha256: str
    source_snapshot: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    reading_convention: Literal["ltr", "rtl"]


class Panel(Record):
    panel_id: str
    page_id: str
    key: str
    order_index: int
    geometry: PanelGeometry
    bbox: tuple[int, int, int, int]
    page_to_crop: list[list[float]]
    layout_mask: str
    owned_content_mask: str
    source_crop: str
    text_region_ids: list[str] = Field(default_factory=list)
    cleaned_frame: str | None = None
    review_status: Literal["needs_review", "corrected"] = "needs_review"


class Extraction(Record):
    schema_version: Literal["1.0"] = "1.0"
    page_id: str
    method: str
    layout: Layout
    panels: list[Panel]
    provenance: dict
    video_ready: Literal[False] = False
