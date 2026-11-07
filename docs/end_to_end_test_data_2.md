# Ordered end-to-end run: test_data/2

Run ID: `test_data_2_20261107_v1`. Executed on 7 November 2026 using the `python311` conda environment. This is an agent-assisted run, not proof of unattended automation.

The seven source pages `0.webp` through `6.webp` contain 34 verified panels. Cached Magi detections were reused after checking source hashes. Page understanding combined geometry, transcription, incremental identities and bounded local shot plans in one Terra request per page. Independent FLUX and H3 jobs ran four at a time. Three compatible panel pairs shared endpoint-conditioned video shots; one long news panel required two shots. The final timeline contains 32 shots and lasts 218.13 seconds.

## Actual model execution

- Terra: 11 calls, all terminal successful at the provider. Seven accepted current-page understandings; four earlier two-image context results were rejected because the model analyzed the context image. The runner now supplies only the current page.
- FLUX: 34 initial cleaning calls and six targeted repair calls, all successful. One additional small wall repair used local inpainting without another model call.
- H3 Lite: 32 calls, 25 successful and seven failed with E005, "input or output was flagged as sensitive."
- Kling 3 fallback: seven calls for only those failed shots; all seven succeeded with the same reviewed frame images and dialogue inputs.
- Total: 90 new predictions. No new Magi inference, separate TTS, lip-sync, or model critic.

H3 Lite blocked `page0_s01`, `page1_s03`, `page2_s01`, `page2_s04`, `page2_s05`, `page2_s06`, and `page3_s03`. Kling 3 generated all seven, so the final movie contains 32 generated clips and no still placeholders. All seven fallback clips have audio streams; exact dialogue and voice quality still need listening review.

## Corrections and limitations

Visual inspection found incorrect Terra coordinate scales, cropped owned content, invented or changed dialogue, uncertain scene lettering, duplicate character IDs, and some unsuitable shot boundaries. Reviewed JSON preserves the original responses separately. Important OCR fixes include the mother's "comic book" line and the news broadcast's "defender of democracy" wording. These changes are recorded in `agent_review_corrections.json` and the failure receipts.

FLUX repairs addressed retained sound-effect letters, white margins, lost snow background and a duplicated face. A hallucinated mirror was removed with saved local inpainting mask and receipt. Minor defects remain: white strips on `p05_01`, overly detailed outpainted mountains, and drift in environmental lettering. This does not establish general segmentation or restoration accuracy.

All generated clips contain audio streams. This is a technical check; exact spoken wording, voice consistency, lip synchronization and absence of music have not been established by a listening audit. The preview contact sheet checks representative visual frames, not complete motion quality.

## Artifacts and rebuild

Full working artifacts live under `artifacts/end_to_end/test_data_2_20261107_v1`. Each model job stores request settings, input hashes, source paths, prediction ID, returned model version, output, logs, error, timestamps and timing metrics. Original pages, layout masks, crops, raw and reviewed understandings, clean frames, repairs, shot plans, clips, probes and normalization logs are retained.

The private delivery folder contains the final movie, `review.html`, individual clips, source/cleaned comparisons, original pages, contact sheets, timeline, traceability manifest, metadata archive and decode validation receipt. Source scans and per-job artifacts are excluded from this public repository.

`e2e_run_config.json` selects `assemble`. Assembly stops before encoding if any generated clip is missing; it does not create still placeholders. The earlier placeholder movie was removed from delivery after recovery. Running `build_e2e_review.py` rebuilds the review bundle offline. Do not rerun `review_e2e_inputs.py` to rebuild media: it is the recorded initial correction procedure and later voice directions were added to the reviewed manifests.

`recover_failed_videos.py` implements the saved fallback order. Kling 3 was first because these shots contain dialogue and its Replicate interface supports endpoint frames and native audio ([Kling 3 interface](https://replicate.com/kwaivgi/kling-v3-video/readme)). It succeeded on all seven targets, so subsequent models were not called. Safety filters stayed at provider defaults. The 25 successful H3 Lite clips were reused. The hierarchy favors models with documented native audio before video-first models; Kling 4 remains the highest visual fallback from the prior comparison.

The final export uses 1280×720 H.264 at 24 fps with AAC stereo. Frames are scaled proportionally and padded. Audio is padded to the source container duration; trailing audio is preserved. Dialogue loudness is normalized; effects-only clips are limited. The full movie decoded with FFmpeg exit code zero and no error output. All 34 panels are covered in original reading order. The offline suite passed 59 tests before the fallback hierarchy changes. The final movie and review bundle were then independently checked: all media links resolve, the trace archive is intact with unique paths, all clips have audio streams, and FFmpeg decoded the complete movie without errors.
