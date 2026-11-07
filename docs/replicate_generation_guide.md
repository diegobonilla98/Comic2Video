# Replicate generation integration guide

Verified 2026-11-06 against authenticated, read-only Replicate model metadata and current first-party documentation. No predictions were submitted. All seven exact model IDs exist and their complete versioned schemas are saved under docs/replicate_schemas. Interface support is documented, generation quality and exact dialogue are untested.

## Cleaning selection

Use black-forest-labs/flux-2-dev with the requested go_fast=true, output_format=png and output_quality=100. PNG is lossless: output_quality has no effect for PNG according to the live schema. input_images accepts at most four image URIs. Base64 must be a complete data URI (data:image/png;base64,...) rather than naked base64. Use isolated owned-content panels, never dirty full pages. Extra references should have an explicit role and must not introduce neighboring-panel artwork.

The supplied prompt contains two literal 4:3 references, whereas config.json currently targets 16:9. The offline builder preserves the source file and replaces 4:3 with final_video_ar in the outgoing prompt. Explicitly supply that variable. Full regeneration/outpainting does not guarantee preservation of untouched pixels; this endpoint exposes neither an edit mask nor strength controls. Preserve the original and compare character details, scene text and composition before marking a frame video-ready. Outpainting necessarily invents unseen background; the prompt's prohibition on invented objects cannot guarantee otherwise.

## Replicate calling convention

Use replicate.Client(api_token=token) with the existing ignored .env REPLICATE_API_TOKEN; never print it. For these named endpoints use client.predictions.create(model=model_id, input=payload). This creates a paid job: examples and builders here do NOT invoke it. Persist the returned prediction ID immediately, then poll prediction.reload() until succeeded/failed/canceled; impose a deadline and request cancellation on timeout. A network timeout during submission is an unknown outcome, not authorization to duplicate the job. Record request hash, local media hashes, model/schema version, prompt, settings and returned execution version. Named endpoints may change despite a saved schema snapshot. Download successful remote outputs immediately and validate with media probing; URLs are not a durable cache. Retry transport polling separately from regeneration. Verify audio presence, duration, frame rate, dimensions and timeline alignment locally.

Local files can use SDK file inputs where the endpoint supports them; URI fields can use complete image data URIs. Fields explicitly requiring public reference URLs, notably H3 reference_*_urls, should use accessible hosted media, not arbitrary local paths or assumed data-URI support. Avoid publishing reference media unless authorized; use an appropriately scoped upload mechanism. Do not log access-bearing URLs.

## Director prompt contract

Keep a backend-neutral plan: source panel IDs; single-frame, continuous first/last-frame, or cut; frame and reference roles; action beats; camera; fixed visual invariants; exact ordered dialogue with speaker descriptions; ambient sound, effects and music; duration; and transitions. Serialize it separately per backend. A location/time/viewpoint discontinuity means separate shots, not mandatory morphing between panels. Give one achievable action and camera move per short shot. Identify speakers by visible appearance/location and label off-screen speech explicitly. Put exact speech in double quotes, specify language and delivery, and prevent overlapping dialogue unless intended. Seconds in prose are guidance unless the API has a structured timing field; reference consistency and exact speech are not guarantees.

Suggested original single-shot prompt: Preserve the source comic's ink contours, flat colors, character faces and costumes. One continuous six-second shot. The woman at left turns toward the doorway, then pauses. Gentle camera push-in; the room and other characters stay still. She says in English, quietly: "We leave at sunrise." Her line ends before the final second. Audio: soft room tone and one footstep, no music, no narrator. No captions or speech balloons. End in the supplied final-frame composition without a scene change.

## MiniMax H3 Lite

Frame keys: first_frame_image and last_frame_image. duration is an integer 4–15. resolution is case-sensitive 480P or 768P; ratio is ignored in image-to-video. Reference collections: reference_image_urls up to nine, reference_video_urls up to three and 15 seconds combined, reference_audio_urls up to three; audio references need an image or video reference. Reference video seconds are billed as well as output seconds per the schema. First/last frames and reference modes exist, but do not assume every combination is valid without documented examples. Describe each reference's role explicitly in ordinary prose; the reviewed documentation does not establish a special reference-token grammar. Audio references can guide voice/rhythm, but these readmes and schema do not establish synchronized generated speech output or an audio toggle: treat that requirement as unresolved.

First/last payload pattern: {prompt: director_prompt, first_frame_image: start_uri, last_frame_image: end_uri, duration: 6, resolution: "768P", ratio: final_video_ar}. Reference-mode pattern uses reference_image_urls/reference_video_urls/reference_audio_urls instead, with explicit identity/motion/voice roles.

Source: https://replicate.com/minimax/h3-lite/readme

## MiniMax H3 Highspeed

Uses the same first_frame_image/last_frame_image and reference_*_urls field names and reference counts as Lite. Duration 4–15; output is documented at 768P. Do not send resolution: this endpoint has no resolution input. ratio adds adaptive and is subordinate to image dimensions. Use the same explicit subject/action/camera/audio-role prose as Lite. Speed-versus-quality claims have not been benchmarked here. As with Lite, native generated audio is not established merely by accepting reference audio; verify output capability before selecting it for dialogue-heavy production.

Payload: {prompt: director_prompt, first_frame_image: start_uri, last_frame_image: end_uri, duration: 6, ratio: final_video_ar}. Do not borrow legacy MiniMax camera tokens or prompt_optimizer parameters without documentation for this exact H3 endpoint.

Source: https://replicate.com/minimax/h3-highspeed/readme

## Pruna P-Video-2-Pro

Use image and last_frame_image. Duration 5–15. mode accepts cost/speed/quality; prompt_upsampler accepts off/turbo/max. For a director-controlled baseline, use off to avoid additional prompt expansion; this is an engineering choice, not a measured fidelity improvement. Native generated audio is documented, with no audio-input or generate_audio field. Describe sound and dialogue in the prompt. It cannot bind a persistent voice ID through the inspected interface. Resolution 480p/768p is native; 1080p/2k/4k upscale 768p and retain 24 fps. Do not label these higher settings native high-resolution synthesis. Reference frames determine the canvas.

Payload: {prompt: director_prompt, image: start_uri, last_frame_image: end_uri, duration: 6, mode: "quality", prompt_upsampler: "off", resolution: "768p", aspect_ratio: final_video_ar}. Prompt order: subject, action, scene, camera, lighting/style, audio. No dedicated multi-shot or character-reference collection is exposed by this exact endpoint; do not silently substitute another Pruna model.

Sources: https://replicate.com/prunaai/p-video-2-pro/readme and https://docs.pruna.ai/en/stable/docs_pruna_endpoints/performance_models/p-video-2-pro.html

## Kling v3 Video

Use start_image/end_image, generate_audio=true, mode standard/pro/4k and duration 3–15. End image requires start image. Images: JPEG/PNG, up to 10 MB, minimum 300px; start-image ratio between 1:2.5 and 2.5:1. Prompt and negative_prompt each have a 2500-character limit. aspect_ratio is ignored when start_image is supplied. The readme omits the live schema's 4k mode, so retain the snapshot as the request authority.

Native audio, quoted dialogue, and structured multi-shot control are documented. multi_prompt is a JSON STRING containing an array of {prompt, duration}; at most six shots, each at least one second, sum exactly equal to overall duration. Example: json.dumps([{ "prompt": first_shot_prompt, "duration": 3 }, { "prompt": second_shot_prompt, "duration": 3 }]). Do not send a Python list directly. Whether combined endpoint frames and multi-shot timing behave as desired remains untested; start with separate shots for discontinuities. Native audio toggle defaults false, so set true explicitly. No voice-reference or identity-reference input is exposed here.

Source: https://replicate.com/kwaivgi/kling-v3-video/readme

## Kling v4.0

Use start_image, ordered middle_images, end_image, reference_images, reference_videos and optional base_video. Images share a ten-image total. Reference numbering includes every frame: start, middle frames, end, then references. With start+end+two identity references, start is @image_1, end @image_2, identities @image_3/@image_4. Videos number base_video first, then reference_videos. At most five videos, each 3–30 seconds, combined at most 30 seconds. Input videos are MP4/MOV, at most 300 MB and 700–4553px per side. Images at most 30 MB, minimum 300px, ratios 2:5–5:2. Duration 3–30 and resolution 720p/1080p. Base-video editing inherits its duration and ratio; other supplied frames also override aspect_ratio.

Prompt structure: subject, action, setting, camera, then temporal beats and explicit reference roles. Example: The woman from @image_3 moves from @image_1 to the pose in @image_2, preserving the ink style of @image_4. No multi_prompt, negative_prompt, voice ID, audio-reference or generate_audio field is exposed. Neither the reviewed readme nor schema establishes native generated audio: do not shortlist it as meeting the joint-audio requirement yet.

Source: https://replicate.com/kwaivgi/kling-v4.0/readme

## Seedance 2.5

Two distinct conditioning modes are essential. Endpoint mode uses image plus optional last_frame_image, aspect_ratio="adaptive", generate_audio=true; it cannot be combined with reference_images, reference_videos or reference_audios. Reference mode supports up to thirty images, ten videos (30 seconds combined), and ten audios (30 seconds combined). Audio requires an image or video reference. Tokens are [Image1], [Video1], [Audio1], not Kling's @image_1 syntax. Explicitly state which input controls identity, style, motion and voice. Do not promise voice cloning merely because audio references exist.

Use a structured production brief: style/subjects, setting, camera, chronological action beats, exact quoted dialogue and delivery, audio, preservation constraints. Native synchronized audio is documented. Resolution is 480p or 720p in the inspected Replicate schema. Duration: use documented 4–30 seconds or -1 for automatic duration; the schema minimum -1 alone does not make 0–3 valid. Editing uses duration=-1 and adaptive ratio; extension also needs adaptive. Reference editing and extension are prompt-directed modes, not nonexistent edit_mode fields. Output format mp4/mov; seed exists but reproducibility is explicitly not guaranteed.

Source: https://replicate.com/bytedance/seedance-2.5/readme

## Interface-based shortlist, not a quality ranking

Kling v3 is the clearest documented fit for endpoint frames, native audio and explicit multi-shot timing. Seedance 2.5 offers broad multimedia direction and native audio, but its endpoint/reference mutual exclusion matters for persistent character/voice references. Pruna fits endpoint-plus-generated-audio shots but lacks audio references on this endpoint. H3 variants need audio-output confirmation; Kling v4 has rich keyframe/reference control but unestablished audio. No generation quality, spoken-script accuracy, voice persistence or art-style retention was tested. Keep video selection unset and generation disabled.


## Exact accepted input names: black-forest-labs/flux-2-dev

Observed version: 7bba46bdde863cfd7aaee87649a5aa49f39f368495dbea500998d1fcbb262050

`seed`, `width`, `height`, `prompt`, `go_fast`, `aspect_ratio`, `input_images`, `output_format`, `output_quality`, `disable_safety_checker`


aspect_ratio: ["match_input_image", "custom", "1:1", "16:9", "3:2", "2:3", "4:5", "5:4", "9:16", "3:4", "4:3"]


output_format: ["webp", "jpg", "png"]


## Exact accepted input names: bytedance/seedance-2.5

Observed version: 1e03d92b7dd93bc7af65a7cb37054bfa10610222d089ad5d19725f941675a202

`seed`, `image`, `prompt`, `duration`, `watermark`, `resolution`, `aspect_ratio`, `output_format`, `generate_audio`, `last_frame_image`, `reference_audios`, `reference_images`, `reference_videos`


resolution: ["480p", "720p"]


aspect_ratio: ["16:9", "4:3", "1:1", "3:4", "9:16", "21:9", "adaptive"]


output_format: ["mp4", "mov"]


## Exact accepted input names: kwaivgi/kling-v3-video

Observed version: 53c71d6674222d4cd8aa5ec1c03e42720dfa8c1a67a45a182c5ffa5ccc2bc023

`mode`, `prompt`, `duration`, `end_image`, `start_image`, `aspect_ratio`, `multi_prompt`, `generate_audio`, `negative_prompt`


mode: ["standard", "pro", "4k"]


aspect_ratio: ["16:9", "9:16", "1:1"]


## Exact accepted input names: kwaivgi/kling-v4.0

Observed version: a35865309ecd984e603e640b17001d5731d8ddeda8b1c16fb69fd1de7d8699d8

`prompt`, `duration`, `end_image`, `base_video`, `resolution`, `start_image`, `aspect_ratio`, `middle_images`, `reference_images`, `reference_videos`


resolution: ["720p", "1080p"]


aspect_ratio: ["16:9", "9:16", "1:1", "21:9"]


## Exact accepted input names: minimax/h3-highspeed

Observed version: d821ddb42f6a24bae190fb1aae9414e00561ebf6dfcca20c2c42278842f61b45

`ratio`, `prompt`, `duration`, `last_frame_image`, `first_frame_image`, `reference_audio_urls`, `reference_image_urls`, `reference_video_urls`


ratio: ["adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"]


duration: [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]


## Exact accepted input names: minimax/h3-lite

Observed version: a9968d26d2043f0bd2a55e3cbe7caaa7e02976a3881a22e56343f663403a1816

`ratio`, `prompt`, `duration`, `resolution`, `last_frame_image`, `first_frame_image`, `reference_audio_urls`, `reference_image_urls`, `reference_video_urls`


ratio: ["21:9", "16:9", "4:3", "1:1", "3:4", "9:16"]


duration: [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]


resolution: ["480P", "768P"]


## Exact accepted input names: prunaai/p-video-2-pro

Observed version: 7fc65104affa38f28b544b3549506e52f6519d752f528944f4eae2f94cd384b6

`mode`, `seed`, `image`, `prompt`, `duration`, `resolution`, `aspect_ratio`, `last_frame_image`, `prompt_upsampler`, `enable_safety_filter`


mode: ["quality", "speed", "cost"]


resolution: ["480p", "768p", "1080p", "2k", "4k"]


aspect_ratio: ["16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "1:1"]


prompt_upsampler: ["off", "turbo", "max"]
