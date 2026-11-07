from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
from comic2video.storage import read_json, write_json
import base64
import io
import json
import shutil


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"
CANVAS_PATH = OUTPUT_DIRECTORY / "vignette-model-comparison.canvas.tsx"


def embedded_image(path):
    with Image.open(path) as image:
        preview = ImageOps.contain(image.convert("RGB"), (500, 760))
    stream = io.BytesIO()
    preview.save(stream, format="JPEG", quality=78)
    return "data:image/jpeg;base64," + base64.b64encode(stream.getvalue()).decode("ascii")


def main():
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    report = read_json(PROJECT_ROOT / "artifacts" / "model_benchmark" / "comparison.json")
    runs = {name: read_json(data["run_manifest"]) for name, data in report["models"].items()}
    predictions = {name: {item["source_file"]: read_json(item["result_path"]) for item in run["results"]} for name, run in runs.items()}
    labels = read_json(PROJECT_ROOT / "annotations" / "model_benchmark.json")
    fixtures = read_json(PROJECT_ROOT / "artifacts" / "benchmark_fixtures" / "manifest.json")
    references = {p["source_file"]: p for p in labels["pages"]}
    references.update({p["source_file"]: p["reference"] for p in fixtures["inputs"]})
    notes = {
        "1/4.png": "Two balloons cross between the third and fourth panels. Both models find all six regions; their structural outputs misassign crossing dialogue pixels.",
        "1/5.png": "Both separate the two upper panels, but clip the balloon above the second panel. Koharu also duplicates a lower panel.",
        "2/0.webp": "Magi detects the full-page splash. Koharu returns no frame at the recommended confidence threshold.",
        "2/4.webp": "Magi finds all six panels and includes the upper balloon probe. Koharu misses one panel and clips that protruding balloon.",
        "synthetic/nested_inset": "Magi finds outer and inset boxes, but the outer crop includes the inset. Koharu finds only the inset. Synthetic evidence.",
        "synthetic/diagonal_gutter": "Magi finds three boxes but cannot follow the slanted outlines; neighboring art enters both upper crops. Koharu detects no frames. Synthetic evidence.",
        "synthetic/foreground_overlap": "Magi finds three boxes but clips the foreground object from its stipulated owner and imports it into the neighbor. Koharu finds only one frame. The pasted object's ownership is stipulated by construction; this is not a natural ownership benchmark.",
    }
    cases = []
    for source_file, first in predictions["koharu-yolo26s"].items():
        reference = references.get(source_file)
        expected = len(reference["panels"]) if reference else labels["expected_counts"][source_file]
        cases.append({"id": source_file, "kind": first["input"]["kind"], "expected": expected, "source": embedded_image(first["input"]["image_path"]), "images": {name: embedded_image(Path(next(item["result_path"] for item in runs[name]["results"] if item["source_file"] == source_file)).parent / "overlay.jpg") for name in runs}, "counts": {name: len(predictions[name][source_file]["panels"]) for name in runs}, "note": notes.get(source_file, "Panel count checked against the source page. Detailed geometry annotations exist for seven real pages; count agreement alone is not segmentation correctness.")})
    summary = {}
    for name, data in report["models"].items():
        real = data["real_annotated"]
        summary[name] = {"matched": real["box_detection_at_iou_0.5"]["matched"], "f1": real["box_detection_at_iou_0.5"]["f1"], "counts": data["all_real_page_counts"]["exact_count_pages"], "ownership": real["ownership_probes_passed"], "ownershipTotal": real["ownership_probes_total"], "median": data["timing"]["median_seconds_all_real_pages"], "syntheticMatched": data["synthetic_controls"]["detection_at_iou_0.5"]["matched"]}
    payload = {"models": summary, "cases": cases}
    source = '''import { Stack, Row, Grid, H1, H2, Text, Table, Select, Button, Divider, Link, useHostTheme, useState } from "cursor/canvas";
const data = PAYLOAD;
export default function VignetteComparison() {
  const theme = useHostTheme();
  const [selected, setSelected] = useState("synthetic/nested_inset");
  const [zoom, setZoom] = useState(false);
  const current = data.cases.find(item => item.id === selected)!;
  const names = ["koharu-yolo26s", "magiv3"] as const;
  return <Stack gap={20} style={{padding:24,color:theme.text.primary,background:theme.bg.editor,maxWidth:1200,margin:"0 auto"}}>
    <H1>Magi leads on layout; neither solves owned-content segmentation</H1>
    <Text>Executed both requested checkpoints on 17 supplied pages and three controlled synthetic layouts. Seven real pages have provisional polygon annotations covering 34 panels. No video or other model ran.</Text>
    <Table headers={["Measured result", "Koharu YOLO26s", "Magi v3"]} rows={[
      ["Exact panel count · 17 real pages", `${data.models["koharu-yolo26s"].counts}/17`, `${data.models.magiv3.counts}/17`],
      ["Matched panels · 34 annotated real panels · box IoU ≥ 0.5", `${data.models["koharu-yolo26s"].matched}/34`, `${data.models.magiv3.matched}/34`],
      ["Detection F1 · same 34-panel subset", `${(data.models["koharu-yolo26s"].f1*100).toFixed(1)}%`, `${(data.models.magiv3.f1*100).toFixed(1)}%`],
      ["Structural output passes owned-content probes · real pages", `${data.models["koharu-yolo26s"].ownership}/15`, `${data.models.magiv3.ownership}/15`],
      ["Matched regions · 8 synthetic panels · region IoU ≥ 0.5", `${data.models["koharu-yolo26s"].syntheticMatched}/8`, `${data.models.magiv3.syntheticMatched}/8`],
      ["Median inference · RTX 4050 · excludes loading and artifact writes", `${data.models["koharu-yolo26s"].median.toFixed(2)} s/page`, `${data.models.magiv3.median.toFixed(2)} s/page`],
      ["Native panel geometry", "Instance masks", "Bounding boxes only"]
    ]}/>
    <Text size="small" tone="secondary">Source: pinned checkpoint outputs from this project, 2026-11-06. Counts cover all 17 pages; detailed geometry covers seven pages only. Structural output is deliberately tested against content probes to expose the missing ownership layer. Magi rectangles are not learned masks.</Text>
    <Divider/>
    <H2>Inspect source and predictions</H2>
    <Row gap={12} wrap>
      <Select value={selected} onChange={setSelected} options={data.cases.map(item => ({value:item.id,label:`${item.kind === "real" ? "Real" : "Synthetic"} · ${item.id} · ${item.expected} reference panels`}))} style={{minWidth:300}}/>
      <Button onClick={() => setZoom(!zoom)}>{zoom ? "Fit images" : "Enlarge images"}</Button>
    </Row>
    <Text weight="semibold">{current.note}</Text>
    <div style={{overflowX:"auto"}}><Grid columns={3} gap={12} style={{minWidth:zoom ? 1550 : 620}}>
      <Stack gap={8}><Text weight="semibold">Source · {current.expected} panels</Text><img src={current.source} alt={`Source ${current.id}`} style={{width:"100%",height:"auto"}}/></Stack>
      {names.map(name => <Stack gap={8} key={name}><Text weight="semibold">{name} · {current.counts[name]} detected</Text><img src={current.images[name]} alt={`${name} predicted regions for ${current.id}`} style={{width:"100%",height:"auto"}}/></Stack>)}
    </Grid></div>
    <Text size="small" tone="secondary">Blue regions show raw frame output. The display uses rasterized rectangles for Magi, explicitly labeled bounding boxes. Neither output has had ownership refinement, duplicate suppression, manual correction, or a fallback applied.</Text>
    <Divider/>
    <H2>Provisional rating for this pipeline</H2>
    <Text><strong>Magi v3: strong layout detector; incomplete vignette segmenter.</strong> It locates the splash, nested inset, and diagonal-panel regions in this test. Its four-corner boxes cannot remove an inset from its parent or preserve a foreground silhouette crossing a border.</Text>
    <Text><strong>Koharu: fast, but unreliable as the sole panel extractor on these color comics.</strong> Native masks are useful, yet duplicates, misses, and failures on the controlled layouts outweigh that advantage. Its frame mask also omits protruding dialogue.</Text>
    <Text>Use Magi as the provisional layout proposal model. The next measured component should produce precise owned-content masks and separate crossing dialogue and foreground elements. Do not consider either result video-ready.</Text>
    <H2>What this does not establish</H2>
    <Text size="small">Only two supplied color comics were tested. Annotations are approximate coding-agent labels without independent human review. One panel count was corrected after prediction inspection, and that page was then added to the detailed subset. Synthetic pages are diagnostics, not natural comic examples; foreground ownership there is stipulated. No threshold tuning, OCR accuracy, identity quality, native reading-order score, or production-provider deployment was evaluated.</Text>
    <Row gap={20} wrap><Link href="https://huggingface.co/mayocream/koharu-yolo26s">Koharu checkpoint and interface</Link><Link href="https://huggingface.co/ragavsachdeva/magiv3">Magi checkpoint and interface</Link></Row>
  </Stack>;
}
'''.replace("PAYLOAD", json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
    CANVAS_PATH.write_text(source, encoding="utf-8")
    shutil.copyfile(CANVAS_PATH, OUTPUT_DIRECTORY / CANVAS_PATH.name)
    write_json(OUTPUT_DIRECTORY / "vignette_model_metrics.json", report)
    chosen = ["1/4.png", "1/5.png", "2/0.webp", "synthetic/nested_inset", "synthetic/diagonal_gutter", "synthetic/foreground_overlap"]
    montage = Image.new("RGB", (1800, 1180), "white")
    draw = ImageDraw.Draw(montage)
    font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 18)
    for index, key in enumerate(chosen):
        case = next(c for c in cases if c["id"] == key)
        x, y = index % 3 * 600, index // 3 * 590
        draw.text((x + 10, y + 5), f"{key} · reference {case['expected']}", font=font, fill="black")
        for column, name in enumerate(predictions):
            path = Path(next(item["result_path"] for item in runs[name]["results"] if item["source_file"] == key)).parent / "overlay.jpg"
            thumb = ImageOps.contain(Image.open(path).convert("RGB"), (285, 515))
            draw.text((x + column * 300 + 5, y + 32), f"{name}: {case['counts'][name]}", font=font, fill="black")
            montage.paste(thumb, (x + column * 300 + 5, y + 60))
    montage.save(OUTPUT_DIRECTORY / "vignette_model_comparison.jpg", quality=91)
    print("Created visual comparison and metric receipt", flush=True)


if __name__ == "__main__":
    main()
