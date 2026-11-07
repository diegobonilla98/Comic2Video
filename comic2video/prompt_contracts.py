from typing import Literal
from pydantic import Field, model_validator
from comic2video.contracts import Record, Polygon, Layout


class TextRegion(Record):
    text_id: str
    panel_id: str
    polygon: Polygon = Field(min_length=3)
    category: Literal["speech", "thought", "narration", "sound_effect", "scene_text", "unknown"]
    text: str
    order: int = Field(ge=0)
    speaker_id: str | None
    speaker_status: Literal["visible", "off_panel", "unknown", "narrator", "not_speech"]
    uncertain: bool

    @model_validator(mode="after")
    def check_speaker(self):
        if self.category == "narration" and (self.speaker_id is not None or self.speaker_status != "narrator"):
            raise ValueError("Narration must remain separate from character speech")
        if self.speaker_status == "visible" and self.speaker_id is None:
            raise ValueError("Visible speakers need a known character ID")
        if self.speaker_status == "unknown" and self.speaker_id is not None:
            raise ValueError("Unknown speakers cannot be assigned a known identity")
        return self


class CharacterUpdate(Record):
    character_id: str
    name: str | None
    appearance: str
    reference_ids: list[str]
    evidence_ids: list[str] = Field(min_length=1)
    uncertain: bool


class ScriptPlan(Record):
    texts: list[TextRegion]
    character_updates: list[CharacterUpdate]
    warnings: list[str]

    @model_validator(mode="after")
    def unique_ids(self):
        keys = [item.text_id for item in self.texts]
        if len(keys) != len(set(keys)):
            raise ValueError("Text IDs must be unique")
        return self


class CleanupPlan(Record):
    panel_id: str
    remove_text_ids: list[str]
    preserve_text_ids: list[str]
    repairs: list[str]
    requires_review: bool
    warnings: list[str]

    @model_validator(mode="after")
    def disjoint_edits(self):
        if set(self.remove_text_ids) & set(self.preserve_text_ids):
            raise ValueError("Text cannot be removed and preserved simultaneously")
        return self


class DialogueEvent(Record):
    text_id: str
    speaker_id: str | None
    speaker_description: str
    placement: Literal["on_screen", "off_screen", "voiceover"]
    text: str
    delivery: str
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)


class ShotPlan(Record):
    shot_id: str
    panel_ids: list[str] = Field(min_length=1, max_length=3)
    mode: Literal["single", "first_last"]
    continuity: Literal["continuous", "time_jump", "viewpoint_change", "scene_change", "unknown"]
    first_frame_id: str
    last_frame_id: str | None
    duration: int = Field(ge=4, le=15)
    camera: str
    action: str
    invariants: str
    dialogue: list[DialogueEvent]
    sound: str
    transition_in: Literal["cut", "continue"]
    requires_review: bool

    @model_validator(mode="after")
    def compatible_endpoints(self):
        if self.mode == "first_last":
            if self.continuity != "continuous" or not self.last_frame_id or self.last_frame_id == self.first_frame_id:
                raise ValueError("First/last conditioning requires compatible distinct frames and continuous action")
        elif self.last_frame_id is not None:
            raise ValueError("Single-frame shots cannot have an end frame")
        previous_end = 0
        for event in self.dialogue:
            if not previous_end <= event.start_seconds < event.end_seconds <= self.duration:
                raise ValueError("Dialogue must be ordered, nonoverlapping and fit the shot")
            previous_end = event.end_seconds
        return self


class DirectorPlan(Record):
    shots: list[ShotPlan] = Field(min_length=1)
    warnings: list[str]

    @model_validator(mode="after")
    def unique_shots(self):
        ids = [shot.shot_id for shot in self.shots]
        if len(ids) != len(set(ids)):
            raise ValueError("Shot IDs must be unique")
        return self


OUTPUT_CONTRACTS = {"layout": Layout, "script": ScriptPlan, "cleanup": CleanupPlan, "director": DirectorPlan}
