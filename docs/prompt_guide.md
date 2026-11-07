# Active models and concise prompts

Updated 2026-11-07. Video default: `minimax/h3-lite`, 768P, normally six seconds. Reasoning default: `openai/gpt-5.6-terra` through Replicate. Cleaning: `black-forest-labs/flux-2-dev`. Active selections are consistent in `config.json` and `generation_research_config.json`. This guide describes prompt construction; generation is performed only by the explicit generation and recovery entry points.

## Prompt files

- `prompts/common.system.txt`: JSON-only output, source evidence, explicit uncertainty and untrusted image/text handling.
- `prompts/layout.system.txt`: original-pixel polygons, reading order, nested panels, exclusions and protruding content. Use when resolving layout proposals, not as an extra mandatory detector pass.
- `prompts/script.system.txt`: transcription, panel/speaker association and incremental character updates in one local call.
- `prompts/cleanup.system.txt`: edit planning for a single panel, preserving scene writing. Skip this call when deterministic text classification already resolves the edit plan.
- `prompts/director.system.txt`: one local audiovisual director, continuous endpoints versus independent cuts, exact source dialogue, descriptive voices, action/camera/audio.
- `prompts/repair.system.txt`: one optional schema-repair attempt; retain the original stage schema and relevant images. Do not loop until a speculative answer appears. Missing factual evidence needs review.
- `prompts/h3_lite.prompt.txt`: ordinary scene prose for the video model, not an LLM system message or JSON output demand.
- `vignette_cleaning_prompt.txt`: short FLUX image-edit instruction; `{aspect_ratio}` is filled by the cleaning builder. The prior full-length prompt is retained in `work/vignette_cleaning_prompt.original.txt`.

Magi's existing detection method keeps its published built-in prompt. Ingestion, mask rasterization, ordering mechanics, media checks, caching and assembly do not need new LLM prompts. No global director or video-critic loop is added.

## Replicate-specific request builders

All builders are offline and return `{model, input}` only. They do not submit requests or change execution permissions.

`comic2video.prompting.build_llm_request(root, stage, context, image_paths)` loads common plus stage system instructions and the typed output contract. `stage` is layout/script/cleanup/director. `context` contains only the current page or at most three neighboring panels, relevant script, selected registry entries, user corrections and backend capabilities. For layout, include the page's original width/height, reading convention and proposal IDs. `image_paths` maps meaningful image IDs to local paths in the desired input order; the builder adds an explicit index-to-ID map. Select at most four relevant images. Pass original panels to transcription and clean frames to direction, labeling roles in context.

Terra uses Replicate's actual `system_prompt`, `prompt`, `image_input`, `verbosity`, `reasoning_effort`, `max_completion_tokens` keys. Do not combine these with `messages`, which overrides prompt/system_prompt on this endpoint. Do not add unsupported temperature, response_format or native JSON-schema parameters. The compact schema travels in the user prompt and `parse_llm_response(stage, output)` validates the returned JSON locally; this is not native constrained decoding. Failed/truncated JSON must not silently become a success.

Output contracts are in `comic2video/prompt_contracts.py`; layout reuses the existing Layout contract. Default verbosity is low and reasoning effort low. Completion caps are 4096 for layout/script, 1024 for cleanup, 2048 for director/repair. Caps include reasoning tokens, so an empty or truncated response needs explicit handling, not a fabricated fallback. These are starting budgets, not measured optimal limits. No chain-of-thought instruction, repeated examples, full-book context or repeated registry is included. Compact JSON input avoids pretty-print overhead; schema and required evidence still consume tokens.

`build_cleaning_request(root, panel_paths, final_video_ar)` uses the active short prompt, image data URIs and requested FLUX settings. It accepts one source plus at most three references. Image 1 should be the owned panel; supply only relevant same-scene references. The endpoint has no edit-mask or strength field: prompt instructions cannot guarantee unchanged pixels. Verify output fidelity and scene lettering before approving a frame.

`build_video_request(root, shot, frames, script)` validates a ShotPlan and ScriptPlan, then deterministically renders the H3 template; there is no extra prompt-writing LLM call. `frames` maps frame IDs to records containing `path`, `panel_id` and `video_ready`. Readiness must come from upstream review, not an unchecked model assertion. Transparent extraction masks and mismatched endpoint aspect ratios are rejected. Missing/changed source dialogue, unknown speakers, wrong on-screen placement for narration, discontinuous endpoint pairs and unresolved shots are rejected. H3 receives `first_frame_image`, optional `last_frame_image`, integer duration 4–15 and `resolution="768P"`. It has no system_prompt, negative_prompt, seed or generate_audio input. Audio is directed in ordinary prose; no music by default. Descriptive voices and second-based dialogue timing are soft guidance, not guaranteed voice binding or forced alignment. Native audio tracks were observed in the authorized comparison.

After approval to execute a specific request, use the existing Replicate provider, passing media paths as source_files. It handles its normal execution/budget gates and prediction records. The builder alone does not make the full pipeline automatic. Text regions, registry retrieval, mask ownership, cleanup quality and complete timeline integration remain separate unfinished stages. Mechanical schema tests do not establish model output quality; no fresh inference was run for this change.

## Evidence

The exact Terra schema is saved in `docs/replicate_schemas/openai_gpt-5.6-terra.json`. Model-specific fields were verified using Replicate's authenticated read-only metadata. Existing H3 and FLUX snapshots govern their request validation.

Prompt style follows brief, direct instructions and explicit output constraints from [official OpenAI reasoning guidance](https://developers.openai.com/api/docs/guides/reasoning-best-practices), while retaining the requested [GPT-5.6 Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra) model. Replicate is the provider, so no direct OpenAI API or new key was introduced. Interfaces: [Terra on Replicate](https://replicate.com/openai/gpt-5.6-terra/readme), [H3 Lite](https://replicate.com/minimax/h3-lite/readme).
