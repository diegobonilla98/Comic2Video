# Video recovery hierarchy

Run only after a terminal failed/canceled video prediction. Reuse the same reviewed frame images, script text, speaker details, and shot duration. Do not resubmit successful jobs. Keep each provider's content safety settings at their defaults; `prunaai/p-video-2-pro` explicitly receives `enable_safety_filter=true`.

1. `kwaivgi/kling-v3-video`: endpoint frames, native audio, and exact quoted dialogue support; it fits the dialogue shots.
2. `bytedance/seedance-2.5`: endpoint frames and synchronized speech/audio. First/last-frame mode requires `aspect_ratio=adaptive`; it cannot use reference lists in that mode.
3. `kwaivgi/kling-v4.0`: strongest visual candidate per the project's earlier comparison and explicit endpoint frames; the inspected interface does not expose generated audio, so prefer the audio-capable options for dialogue.
4. `prunaai/p-video-2-pro`: first/last-frame control and quality mode. Its inspected Replicate interface does not document a native-audio switch, so confirm the returned stream and mark dialogue unavailable if it is silent. Minimum duration is five seconds, so four-second plans are extended by one second and recorded.
5. `minimax/h3-highspeed`: last resort after H3 Lite returned a terminal content-filter block; its generation and policy behavior may differ, and it is allowed to reject the same input.

Try each model at most once per unresolved shot; stop that shot on the first successful video. A model may reject a shot under its own policy; record that result and advance. Do not switch off filters, alter source imagery to evade a filter, or infer that an error discloses its moderation category beyond what the provider returns. Unknown submission outcomes are resumed by prediction ID and never duplicated. The recovery ceiling is five fallback calls per failed shot and 125 total new predictions for this run, counting the original 83.

Prompt serialization follows the saved, inspected Replicate schemas and `docs/replicate_generation_guide.md`. The current recovery attempt covers only the seven terminal E005 failures from run `test_data_2_20261107_v1`; the 25 successful H3 Lite clips remain cached.

Model interface references: [Kling 3 Video](https://replicate.com/kwaivgi/kling-v3-video/readme), [Seedance 2.5](https://replicate.com/bytedance/seedance-2.5), [P-Video 2 Pro](https://replicate.com/prunaai/p-video-2-pro), [Kling 4.0](https://replicate.com/kwaivgi/kling-v4.0/readme), and [H3 Highspeed](https://replicate.com/minimax/h3-highspeed/readme).
