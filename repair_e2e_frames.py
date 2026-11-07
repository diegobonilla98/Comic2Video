from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
from comic2video.cleaning import build_cleaning_request
from comic2video.e2e_jobs import RunJobs, download_output
from comic2video.storage import read_json, write_json
import shutil


ROOT = Path(__file__).resolve().parent
CONFIG = read_json(ROOT / "e2e_run_config.json")
RUN = ROOT / CONFIG["artifact_dir"]
REPAIRS = {
    "p01_03": "Fill the entire 16:9 canvas. Extend the existing pale blue sky upward and the snowy mountain scene downward. No white horizontal bars, blank margins, added figures or cropping. Preserve the distant flying hero at left and the close mechanical device and beige-jacketed man's shoulder at right.",
    "p02_02": "Remove the huge outlined THOOM letters across the upper background completely. Keep the erupting snow and debris, with a flat pale peach sky behind it. No lettering, symbols, subtitles, new characters or blank border.",
    "p02_06": "Keep the low-flying hero above the snowy landscape. Preserve and extend the snow crater and scattered ice at left and the pale blue mountain-and-snow background across the full canvas. Remove the speech balloon. No white studio backdrop or isolated character cutout.",
    "p03_02": "Remove the BANG BANG sound-effect lettering beside the woman's raised hand; fill that area with the same flat brown wall. Exactly one woman in a pink top, one head and one face. Preserve doorway, raised fist, jewelry and expression. No added text.",
    "p03_04": "Exactly ONE woman, ONE head, ONE face. Keep the original woman's face, bun, hoop earring and pink neckline. Remove the two speech balloons. Outpaint only the plain brown wall on both sides. Never duplicate her face or add a second person, reflection or ghost image.",
    "p05_01": "Fill the entire 16:9 canvas by extending the school facade, sky and pavement naturally at the top and bottom. No blank white bars. Preserve the crowded school entrance, yellow bus and all people. Remove the dialogue balloon only; preserve the original school-sign lettering without inventing new words."
}


def repair(jobs, key, instruction):
    folder = RUN / "frames" / key
    archive = folder / "clean.first_pass.png"
    if not archive.exists():
        shutil.copyfile(folder / "clean.png", archive)
    request = build_cleaning_request(ROOT, [folder / "isolated_rgb.png"], CONFIG["target_aspect_ratio"])
    request["input"]["prompt"] += " " + instruction
    record, job_folder = jobs.run("cleaning_repair", key, request, [folder / "isolated_rgb.png"])
    target = folder / "clean.repaired.png"
    download_output(record, target)
    with Image.open(target) as image:
        image.verify()
    shutil.copyfile(target, folder / "clean.png")
    write_json(folder / "repair.json", {"instruction": instruction, "original": str(archive), "repaired": str(target), "prediction": str(job_folder / "prediction.json"), "reason": "Coding-agent visual review identified a specific first-pass cleanup defect"})


if __name__ == "__main__":
    jobs = RunJobs(ROOT, CONFIG)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(repair, jobs, key, instruction) for key, instruction in REPAIRS.items()]
        for future in as_completed(futures):
            future.result()
