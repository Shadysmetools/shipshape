---
name: qa-narrate
description: Voice narration for videos and reports - use to add a natural voice (English or Arabic) and .srt captions to a video, narrate a QA result for non-technical people, or build a narrated slide video from screenshots.
---
# Narrate
- Spoken summary of a run: `python ${CLAUDE_PLUGIN_ROOT}/scripts/narrator.py report <run> --lang en|ar` -> `summary-<lang>.mp3` + `.srt`.
- Voice over an existing video (its own audio is ducked): `narrator.py mix video.mp4 lines.json` with `[{"t": 1.5, "text": "..."}]`.
- Slides from screenshots: `slides_video.py scenes.json --out demo.mp4` (labels LIVE / SIMULATED / REGRESSION / ILLUSTRATION).

Providers: `edge` (default, free), `openai` (OPENAI_API_KEY), `elevenlabs` (ELEVENLABS_API_KEY + ELEVENLABS_VOICE_ID). A missing key falls back to edge.
Voices: en-US-AndrewNeural; Arabic ar-EG-ShakirNeural or ar-EG-SalmaNeural. Clips are cached and validated with ffprobe, so a broken clip heals itself.
