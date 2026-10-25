---
name: qa-narrate
description: Voice narration for videos and reports - use to add a natural voice (English or Arabic) and .srt captions to a video, narrate a QA result for non-technical people, or build a narrated slide video from screenshots.
---
# Narrate
- Spoken summary of a run: `python ${CLAUDE_PLUGIN_ROOT}/scripts/narrator.py report <run> --lang en|ar` -> `summary-<lang>.mp3` + `.srt`.
- Voice over an existing video (its own audio is ducked): `narrator.py mix video.mp4 lines.json` with `[{"t": 1.5, "text": "..."}]`.
- Slides from screenshots: `slides_video.py scenes.json --out demo.mp4` (labels LIVE / SIMULATED / REGRESSION / ILLUSTRATION).

Voice profiles: `narrator.voices` in `qa.config.yaml` names each voice (provider `edge` | `openai` | `elevenlabs`, a voice id, an optional `lang`); `narrator.default_voice` picks the default and `--voice <profile>` picks one per run (`record.py`, `slides_video.py`, `narrator.py report|mix`). An ElevenLabs voice id is literal or `{env: ELEVENLABS_VOICE_ID_<NAME>}`; API keys (OPENAI_API_KEY, ELEVENLABS_API_KEY) come only from `scripts/keys.py`, and each user brings their own. `narrator.py voices` lists the profiles.
If a paid provider refuses (no key, HTTP 402 "paid plan required" for library voices, offline), the free edge voice speaks instead, one warning line is printed and `results.json` `narration_note` says why. Nothing crashes.

**Consent**: only use a cloned voice whose owner agreed to it narrating these videos. Make one profile per team member who said yes; never clone or select anyone else's voice. Narration stays synthetic: say so where the video is shared.
Voices: en-US-AndrewNeural; Arabic ar-EG-ShakirNeural or ar-EG-SalmaNeural. Clips are cached and validated with ffprobe, so a broken clip heals itself.
