# RAGdoll Build Week demo narration

The final video is generated from the nine narration segments in
`scripts/build_build_week_video.py`. Provider provenance is explained in the voiceover rather than
repeated in a permanent on-screen strip. The recorded investigation is the documented 2026-07-15
acceptance run using Ollama with `qwen3:4b`. The OpenAI Responses adapter and GPT-5.6 configuration
are real and contract-tested, but no successful paid GPT-5.6 request is represented in the footage.

The generated SRT contains the complete narration transcript for an optional, selectable YouTube
English caption track. Captions are not burned into the video.

Narration uses Microsoft Edge Neural TTS `en-US-AndrewMultilingualNeural` via the pinned
`edge-tts==7.2.8` client. Only these narration sentences are sent to the external speech service.
Set `RAGDOLL_EDGE_VOICE` to regenerate with another available voice.
