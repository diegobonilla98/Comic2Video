from pathlib import Path
from copy import deepcopy
from PIL import Image
from comic2video.e2e_contracts import PageUnderstanding
from comic2video.extraction import detect_local
from comic2video.geometry import polygon_mask
from comic2video.evaluation import match_masks
from comic2video.contracts import Page
from comic2video.storage import load_config, read_json, write_json
import numpy as np


ROOT = Path(__file__).resolve().parent
RUN = ROOT / "artifacts/end_to_end/test_data_2_20261107_v1"
TEXT_CORRECTIONS = {
    "page3_t07": "WELL, YOU NEED TO STOP READING THAT COMIC BOOK AND START GETTING READY.",
    "page4_t07": "...USING A DRAGON-LIKE MONSTER TO ENSLAVE A PORTION OF TAIWAN. NEW REPORTS REVEAL THE BLURRED FIGURE SEEN IN THIS AMATEUR PHOTOGRAPH TO BE NONE OTHER THAN OMNI-MAN, DEFENDER OF DEMOCRACY.",
    "page4_t08": "EYEWITNESS REPORTS ARE THAT THE BATTLE HAS BEEN RAGING FOR NEARLY TEN HOURS, DESTROYING PORTIONS OF THE TOWN IN ITS WAKE. STAY TUNED TO CHANNEL SIX, ACTION NEWS FOR ANY FURTHER INFORMATION.",
    "page5_t05": "NO CAN DO, PAL. I'VE GOT TO BE AT BURGER MART IN ABOUT TWENTY MINUTES!",
    "page5_t06": "OH, YEAH. FORGOT ABOUT YOU HAVING THE JOB... SUCKS TO BE YOU.",
}
IDENTITY_MERGES = {"page3_char02": "page0_char01", "page4_char01": "page0_char01", "page6_char01": "page0_char01", "page4_char02": "page3_char01"}


def main():
    manifest = read_json(RUN / "run_manifest.json")
    config = load_config(ROOT)
    logs = []
    for index, page_data in enumerate(manifest["pages"]):
        page = Page.model_validate(page_data)
        path = RUN / "pages" / f"{index:02d}" / "understanding.json"
        original = read_json(path)
        data = deepcopy(original)
        if index:
            local = detect_local(page, config)
            with Image.open(page.source_snapshot) as image:
                width, height = image.size
            targets = data["layout"]["panels"]
            context = read_json(path.parent / "context.json")
            proposals = {p["key"]: p["bbox"] for p in context["proposals"]}
            ref_masks = []
            for target in targets:
                x0, y0, x1, y1 = proposals[target["key"]]
                ref_masks.append(polygon_mask([[(x0, y0), (x1, y0), (x1, y1), (x0, y1)]], width, height))
            candidate_masks = [polygon_mask(p.content_polygons, width, height) for p in local.panels]
            matches = match_masks(ref_masks, candidate_masks, 0.6)
            if len(matches) != len(targets) or len(local.panels) != len(targets):
                raise ValueError(f"Local masks do not match verified page {index} panels")
            for target_index, local_index, score in matches:
                target = targets[target_index]
                x0, y0, x1, y1 = proposals[target["key"]]
                target["layout_polygon"] = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
                target["content_polygons"] = local.panels[local_index].content_polygons
                target["excluded_polygons"] = []
                target["notes"] = ["Structural proposal from cached Magi; owned-content contour from original-pixel connected component, matched one-to-one and visually inspected."]
            logs.append({"page": index, "change": "Use original-pixel local contours with verified Magi panel identities", "matched_iou": [score for _, _, score in matches]})
        if index in {3, 6}:
            for text in data["script"]["texts"]:
                text["polygon"] = [[min(993, x * 1528 / 1024), min(1527, y * 1528 / 1024)] for x, y in text["polygon"]]
            logs.append({"page": index, "change": "Correct Terra coordinates grounded in the resized 1024px-long-side image rather than original 994x1528 pixels", "scale": 1528 / 1024})
        for text in data["script"]["texts"]:
            if text["text_id"] in TEXT_CORRECTIONS:
                replacement = TEXT_CORRECTIONS[text["text_id"]]
                logs.append({"page": index, "text_id": text["text_id"], "before": text["text"], "after": replacement, "evidence": page.source_snapshot, "method": "coding-agent visual transcription from source"})
                text["text"] = replacement
            text["speaker_id"] = IDENTITY_MERGES.get(text["speaker_id"], text["speaker_id"])
            if text["text_id"] == "page5_t01":
                text["text"] = "REGINALD / ...ELJOHNSON / ...GH SCHOOL"
                text["uncertain"] = True
            if text["text_id"] == "page6_t02":
                text["text"] = "MALL / TOYS ..."
                text["uncertain"] = True
        script = {t["text_id"]: t for t in data["script"]["texts"]}
        for character in data["script"]["character_updates"]:
            character["character_id"] = IDENTITY_MERGES.get(character["character_id"], character["character_id"])
            character["appearance"] = character["appearance"].replace(", and a black cape", "").replace(", black cape", "").replace("black cape, ", "")
        for shot in data["director"]["shots"]:
            shot["invariants"] = shot["invariants"].replace(", black cape", "").replace("black cape, ", "")
            for event in shot["dialogue"]:
                event["text"] = script[event["text_id"]]["text"]
                event["speaker_id"] = script[event["text_id"]]["speaker_id"]
                if event["text_id"] in {"page4_t07", "page4_t08"}:
                    event["placement"] = "voiceover"
                    event["speaker_description"] = "the unseen television newsreader"
                    event["delivery"] = "Clear brisk broadcast delivery"
        if index == 1:
            first, second, *rest = data["director"]["shots"]
            combined = deepcopy(second)
            combined.update(shot_id="page1_s01_02", panel_ids=["p01_01", "p01_02"], mode="first_last", continuity="continuous", first_frame_id="p01_01_frame", last_frame_id="p01_02_frame", duration=6, action="The hero loosens his hold as the other man rotates away, then moves his forearm into the defensive ending pose; maintain a fixed sky camera.")
            data["director"]["shots"] = [combined, *rest]
        if index == 6:
            a, b, c, d, e, f, g = data["director"]["shots"]
            throwing = deepcopy(d)
            throwing.update(shot_id="page6_s04_05", panel_ids=["p06_04", "p06_05"], mode="first_last", continuity="continuous", last_frame_id="p06_05_frame", duration=5, action="He tosses the light-colored object upward; his arm follows through toward the final pose and the object recedes into the sky.")
            reaction = deepcopy(g)
            reaction.update(shot_id="page6_s06_07", panel_ids=["p06_06", "p06_07"], mode="first_last", continuity="continuous", first_frame_id="p06_06_frame", last_frame_id="p06_07_frame", duration=6, action="His surprised expression softens into the pleased smile of the final frame as he speaks.")
            data["director"]["shots"] = [a, b, c, throwing, reaction]
        data["script"]["warnings"].append("Agent-reviewed source corrections and identity merges are logged separately; original model output is retained.")
        PageUnderstanding.model_validate(data)
        write_json(path.parent / "understanding.reviewed.json", data)
    logs.append({"identity_merges": IDENTITY_MERGES, "evidence": "Source face/hair continuity across hero/civilian/work clothing; Mark named on page5, mother addressed as Mom on page3, William named on page5. Descriptive voice continuity remains approximate."})
    write_json(RUN / "agent_review_corrections.json", logs)
    write_json(RUN / "failures" / "grounding_and_transcription.json", {"stage": "understanding", "coordinate_failures": [3, 6], "transcription_failures": list(TEXT_CORRECTIONS), "details": str(RUN / "agent_review_corrections.json"), "automatic_pipeline": False, "note": "Coding-agent review repaired these errors before paying for image/video generation; raw responses remain immutable."})
    print("Saved reviewed understanding for all seven pages; source corrections preserved", flush=True)


if __name__ == "__main__":
    main()
