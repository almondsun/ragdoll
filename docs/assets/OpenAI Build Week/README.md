# OpenAI Build Week submission archive

This directory preserves the published submission media and its production material:

- `gallery/` — seven numbered Devpost images plus their captions.
- `video/` — final YouTube MP4, thumbnail, and optional SRT caption track.
- `copy/` — archived Devpost copy, YouTube metadata, and narration notes.
- `production/frames/` — reproducible captures from the real saved RAGdoll investigation.
- `source/gallery/` — editable SVGs, product captures, and generated background source.

Nothing under `production/` or `source/` was uploaded directly.

Published submission:

- Devpost: https://devpost.com/software/ragdoll-xfwzms
- YouTube: https://www.youtube.com/watch?v=aytzIq-5S5k
- Repository: https://github.com/almondsun/ragdoll

## Published video archive

- `video/ragdoll-build-week-demo.mp4`
- `video/youtube-thumbnail.png`
- `video/ragdoll-build-week-demo.srt` (selectable English captions; not burned in)

The video uses the natural `en-US-AndrewMultilingualNeural` voice through Edge Neural TTS. Only the
narration text is sent to that speech service.

Rebuild the real product frames with `uv run python scripts/capture_build_week_demo.py`, then build
the final video with `uv run python scripts/build_build_week_video.py`.

## Gallery order and captions

1. `gallery/01-ragdoll-cover.png` — **RAGdoll turns an ambiguous research question into an explainable,
   cited literature dossier—from the terminal.**
2. `gallery/02-real-workspace.png` — **The working Textual interface keeps plans, papers, evidence, dossiers,
   and grounded answers in one keyboard-first research timeline.**
3. `gallery/03-auditable-workflow.png` — **The model proposes; the researcher approves; the application
   preserves every query, source, score, staging decision, and cited passage.**
4. `gallery/04-human-control.png` — **Search approval, paper curation, full-text consent, and evidence
   inspection are separate product boundaries.**
5. `gallery/05-passage-evidence.png` — **Every accepted citation resolves to a passage supplied to the model,
   with evidence level and page locator preserved.**
6. `gallery/06-system-architecture.png` — **Model reasoning stays behind Pydantic contracts while narrow
   adapters own validation, retrieval, storage, and permissions.**
7. `gallery/07-audited-result.png` — **A recorded acceptance run produced a seven-section dossier from 307
   page-aware chunks; 23 of 25 claims were directly supported in a manual passage audit.**

The same captions are available as one-line copy in `gallery/CAPTIONS.txt`.

## Official Build Week facts used

- Theme: explore GPT-5.6 and Codex.
- RAGdoll's recommended category: **Work & Productivity**. It is a scholarly knowledge-work tool;
  Education is a credible alternative, but the product is not limited to students or teachers.
- Video: public YouTube, under three minutes, with a clear working demo and audio explaining how
  both Codex and GPT-5.6 were used.
- Judging: technological implementation, design, potential impact, and quality of the idea are
  equally weighted.
- Judges may rely only on the description, images, and video, so this gallery deliberately tells a
  complete story without requiring a local installation.

Official sources checked on 2026-07-18:

- https://openai.devpost.com/
- https://openai.devpost.com/rules

## Accuracy note

The gallery deliberately excludes unverified claims about a live GPT-5.6 product run. Add model-
specific media only after the recorded behavior and submission wording can be supported honestly.
