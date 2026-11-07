from pathlib import Path
from PIL import Image, ImageDraw, ImageOps
from comic2video.contracts import Extraction, Layout, Panel, PanelGeometry
from comic2video.geometry import isolate, mask_bbox, original_coordinates, polygon_mask, reading_order
from comic2video.storage import canonical, digest, read_json, write_json
import cv2
import numpy as np


BASELINE_VERSION = "white-components-v1"


def detect_local(page, config):
    with Image.open(page.source_snapshot) as source:
        rgb = np.array(source.convert("RGB"))
    ink = np.uint8(np.min(rgb, axis=2) < config.white_threshold) * 255
    contours, _ = cv2.findContours(ink, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = [c for c in contours if cv2.contourArea(c) >= page.width * page.height * config.minimum_panel_area_fraction]
    contours.sort(key=lambda c: (cv2.boundingRect(c)[1], cv2.boundingRect(c)[0]))
    panels = []
    for index, contour in enumerate(contours):
        polygon = cv2.approxPolyDP(contour, 1.0, True).reshape(-1, 2).astype(float).tolist()
        panels.append(PanelGeometry(key=f"p{index + 1:03d}", layout_polygon=polygon, content_polygons=[polygon], confidence=None, notes=["Geometric component proposal; semantic ownership is unverified."]))
    if not panels:
        raise ValueError(f"No panel candidates for {page.source_file}; manual layout required")
    return Layout(coordinate_system="original_pixels", panels=panels, reading_order=reading_order(panels, page.reading_convention), warnings=["White-gutter baseline can merge panels joined by balloons and split borderless artwork.", "Content ownership and reading order require visual review."])


def load_override(path, page):
    data = read_json(path)
    if data["page_id"] != page.page_id or data["source_sha256"] != page.source_sha256:
        raise ValueError("Override does not match the current source page")
    return Layout.model_validate(data["layout"])


def export_panels(page, layout, config, method, provenance):
    layout = original_coordinates(layout, page.width, page.height)
    signature = digest(canonical({"page": page.source_sha256, "layout": layout.model_dump(mode="json"), "method": method, "provenance": provenance}))[:16]
    folder = config.artifact_dir / "pages" / page.page_id / "extractions" / signature
    manifest = folder / "extraction.json"
    if manifest.exists():
        existing = Extraction.model_validate(read_json(manifest))
        required = [folder / "overlay.jpg", folder / "contact_sheet.jpg"]
        required += [Path(path) for panel in existing.panels for path in (panel.layout_mask, panel.owned_content_mask, panel.source_crop)]
        if all(path.is_file() for path in required):
            return existing, manifest
    folder.mkdir(parents=True, exist_ok=True)
    source = Image.open(page.source_snapshot).convert("RGB")
    overlay = source.copy().convert("RGBA")
    tint = Image.new("RGBA", source.size)
    draw = ImageDraw.Draw(tint)
    outline = ImageDraw.Draw(overlay)
    panels = []
    colors = [(230, 57, 70), (29, 150, 220), (20, 180, 110), (220, 140, 20), (150, 70, 210), (20, 180, 180)]
    geometry = {p.key: p for p in layout.panels}
    for index, key in enumerate(layout.reading_order):
        region = geometry[key]
        structural = polygon_mask([region.layout_polygon], page.width, page.height)
        content = polygon_mask(region.content_polygons, page.width, page.height, region.excluded_polygons)
        x0, y0, x1, y1 = mask_bbox(content)
        panel_id = page.page_id + "_" + key
        layout_path = folder / f"{key}_layout.png"
        content_path = folder / f"{key}_content.png"
        crop_path = folder / f"{key}_isolated.png"
        Image.fromarray(structural).save(layout_path)
        Image.fromarray(content).save(content_path)
        isolate(source, content).save(crop_path)
        color = colors[index % len(colors)]
        draw.polygon(region.layout_polygon, fill=(*color, 45))
        for polygon in region.content_polygons:
            outline.line(polygon + [polygon[0]], fill=(*color, 255), width=4)
        label = f"{index + 1}: {key}"
        outline.rectangle((x0, y0, x0 + 130, y0 + 25), fill=(*color, 255))
        outline.text((x0 + 5, y0 + 5), label, fill="white")
        panels.append(Panel(panel_id=panel_id, page_id=page.page_id, key=key, order_index=index, geometry=region, bbox=(x0, y0, x1, y1), page_to_crop=[[1, 0, -x0], [0, 1, -y0], [0, 0, 1]], layout_mask=str(layout_path), owned_content_mask=str(content_path), source_crop=str(crop_path), review_status="corrected" if method == "manual_override" else "needs_review"))
    Image.alpha_composite(overlay, tint).convert("RGB").save(folder / "overlay.jpg")
    columns = min(3, len(panels))
    rows = (len(panels) + columns - 1) // columns
    contact = Image.new("RGB", (columns * 360, rows * 320), "#dddddd")
    contact_draw = ImageDraw.Draw(contact)
    for index, panel in enumerate(panels):
        x, y = (index % columns) * 360, (index // columns) * 320
        thumb = ImageOps.contain(Image.open(panel.source_crop), (345, 280))
        contact.paste(thumb, (x, y + 28), thumb)
        contact_draw.text((x + 4, y + 6), f"{index + 1}: {panel.key} [needs cleanup]", fill="black")
    contact.save(folder / "contact_sheet.jpg")
    extraction = Extraction(page_id=page.page_id, method=method, layout=layout, panels=panels, provenance=provenance)
    write_json(manifest, extraction.model_dump(mode="json"))
    return extraction, manifest


def extract_local(page, config):
    override_path = config.artifact_dir.parent / "overrides" / (page.page_id + ".json")
    if override_path.exists():
        layout = load_override(override_path, page)
        method = "manual_override"
        provenance = {"source_sha256": page.source_sha256, "override_sha256": digest(override_path.read_bytes())}
    else:
        layout = detect_local(page, config)
        method = BASELINE_VERSION
        provenance = {"source_sha256": page.source_sha256, "white_threshold": config.white_threshold, "minimum_panel_area_fraction": config.minimum_panel_area_fraction}
    extraction, path = export_panels(page, layout, config, method, provenance)
    correction_template = config.artifact_dir / "pages" / page.page_id / "correction_template.json"
    if not correction_template.exists():
        write_json(correction_template, {"page_id": page.page_id, "source_sha256": page.source_sha256, "layout": layout.model_dump(mode="json")})
    return extraction, path
