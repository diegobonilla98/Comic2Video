from pydantic import model_validator
from comic2video.contracts import Record, Layout
from comic2video.prompt_contracts import ScriptPlan, DirectorPlan


class PageUnderstanding(Record):
    layout: Layout
    script: ScriptPlan
    director: DirectorPlan

    @model_validator(mode="after")
    def source_consistency(self):
        panels = self.layout.reading_order
        texts = {item.text_id: item for item in self.script.texts}
        spoken = [item.text_id for item in sorted(self.script.texts, key=lambda t: t.order) if item.category in {"speech", "thought", "narration"}]
        events = []
        anchors = []
        for text in self.script.texts:
            if text.panel_id not in panels:
                raise ValueError("Text references an unknown panel")
        for shot in self.director.shots:
            indices = [panels.index(key) for key in shot.panel_ids]
            if indices != sorted(indices) or indices[-1] - indices[0] != len(indices) - 1:
                raise ValueError("Shot references must be ordered adjacent panels")
            anchors.append(indices[0])
            if shot.first_frame_id != shot.panel_ids[0] + "_frame":
                raise ValueError("First frame must belong to the first source panel")
            if shot.last_frame_id is not None and shot.last_frame_id != shot.panel_ids[-1] + "_frame":
                raise ValueError("Last frame must belong to the last source panel")
            for event in shot.dialogue:
                source = texts.get(event.text_id)
                if source is None or event.text != source.text or event.speaker_id != source.speaker_id or source.panel_id not in shot.panel_ids:
                    raise ValueError("Dialogue must match its source text, speaker and panel")
                events.append(event.text_id)
        if anchors != sorted(anchors):
            raise ValueError("Shots changed panel reading order")
        if set(panels) != {key for shot in self.director.shots for key in shot.panel_ids}:
            raise ValueError("Every source panel must appear in the timeline")
        if events != spoken:
            raise ValueError("Every spoken text must occur exactly once and in reading order")
        return self
