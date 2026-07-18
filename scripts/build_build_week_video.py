"""Build the narrated OpenAI Build Week demo and selectable captions."""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

EDGE_TTS_VERSION = "7.2.8"
DEFAULT_VOICE = "en-US-AndrewMultilingualNeural"
TRANSITION_SECONDS = 0.25


@dataclass(frozen=True)
class Scene:
    image: str
    narration: str
    contain: bool = False


SCENES = (
    Scene(
        "gallery/01-ragdoll-cover.png",
        "Research assistants can produce polished answers while hiding how they searched, what "
        "they actually read, and which decisions belonged to the researcher. RAGdoll was built "
        "to keep those receipts.",
        True,
    ),
    Scene(
        "production/frames/01-resumed-investigation.png",
        "This is the real RAGdoll terminal, resuming a documented acceptance investigation about "
        "video generation models. The recorded run was completed locally with Ollama and Qwen "
        "three, four B. No OpenAI API call is simulated in this recording.",
    ),
    Scene(
        "production/frames/02-approved-plan.png",
        "RAGdoll turns an ambiguous question into a structured research brief and an executable "
        "search plan. The researcher can inspect every axis, query family, inclusion rule, and "
        "source before approving discovery. Search never starts silently.",
    ),
    Scene(
        "production/frames/03-curated-papers.png",
        "Approved queries run through scholarly source adapters. Results are deduplicated and "
        "ranked with visible score components and reasons. This run retrieved twenty four "
        "candidates, but the human selected the six papers that entered the evidence workflow.",
    ),
    Scene(
        "production/frames/04-evidence-sources.png",
        "Paper selection and evidence acquisition are separate approvals. RAGdoll records the "
        "source, retrieval state, evidence level, and page count. Five papers supplied open full "
        "text and one used an explicitly labeled abstract fallback.",
    ),
    Scene(
        "production/frames/05-cited-dossier.png",
        "The resulting dossier contains seven checkpointed sections and twenty five cited claims. "
        "It states its evidence boundary instead of claiming exhaustive coverage or novelty. Every "
        "accepted citation identifier had to be present in the bounded evidence supplied for that "
        "section.",
    ),
    Scene(
        "production/frames/06-exact-passage.png",
        "A citation is not decorative. From any claim, the researcher can inspect the exact "
        "indexed passage, paper identifier, page locator, and evidence level. Unsupported "
        "questions fail closed instead of inviting the model to guess.",
    ),
    Scene(
        "gallery/06-system-architecture.png",
        "Model output crosses Pydantic validation before entering domain logic, while narrow "
        "adapters own retrieval, storage, and permissions. Codex accelerated repository analysis, "
        "implementation, testing, and security review. RAGdoll also contains a real Responses API "
        "adapter configured for GPT five point six. It is contract tested, not presented as live "
        "in this capture.",
        True,
    ),
    Scene(
        "gallery/07-audited-result.png",
        "The acceptance run indexed three hundred seven page-aware chunks. A manual passage audit "
        "found twenty three of twenty five claims directly supported, preserving the two failures "
        "as evidence that citation integrity is not automatic entailment. RAGdoll helps "
        "researchers move faster without giving up judgment, provenance, or the ability to check "
        "the receipts.",
        True,
    ),
)


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def speech_command() -> list[str]:
    configured = os.getenv("RAGDOLL_EDGE_TTS")
    if configured:
        return [configured]
    return ["uvx", "--from", f"edge-tts=={EDGE_TTS_VERSION}", "edge-tts"]


def audio_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def srt_time(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"


def caption_cues(text: str, start: float, duration: float, first_index: int) -> list[str]:
    words = text.split()
    groups = [words[index : index + 9] for index in range(0, len(words), 9)]
    available = duration - 0.3
    seconds_per_word = available / len(words)
    cues: list[str] = []
    cursor = start
    for offset, group in enumerate(groups):
        end = cursor + len(group) * seconds_per_word
        cues.extend(
            [
                str(first_index + offset),
                f"{srt_time(cursor)} --> {srt_time(end)}",
                " ".join(group),
                "",
            ]
        )
        cursor = end
    return cues


def video_filter(contain: bool) -> str:
    if not contain:
        return "scale=1920:1080:flags=lanczos,setsar=1,format=yuv420p"
    return (
        "scale=1920:1080:force_original_aspect_ratio=decrease:flags=lanczos,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x0f141b,"
        "drawbox=x=128:y=64:w=2:h=952:color=0x56cfe1@0.55:t=fill,"
        "drawbox=x=1790:y=64:w=2:h=952:color=0x9b5de5@0.55:t=fill,"
        "setsar=1,format=yuv420p"
    )


def transition_filter(durations: list[float]) -> tuple[str, str, str]:
    video_label = "0:v"
    audio_label = "0:a"
    filters: list[str] = []
    elapsed = durations[0]
    for index in range(1, len(durations)):
        next_video = f"v{index}"
        next_audio = f"a{index}"
        offset = elapsed - TRANSITION_SECONDS
        filters.append(
            f"[{video_label}][{index}:v]xfade=transition=fade:"
            f"duration={TRANSITION_SECONDS}:offset={offset:.3f}[{next_video}]"
        )
        filters.append(
            f"[{audio_label}][{index}:a]acrossfade=d={TRANSITION_SECONDS}:"
            f"c1=tri:c2=tri[{next_audio}]"
        )
        video_label = next_video
        audio_label = next_audio
        elapsed += durations[index] - TRANSITION_SECONDS
    filters.append(f"[{audio_label}]loudnorm=I=-16:TP=-1.5:LRA=11[aout]")
    return ";".join(filters), video_label, "aout"


def build(root: Path) -> Path:
    assets = root / "docs/assets/OpenAI Build Week"
    video = assets / "video"
    video.mkdir(parents=True, exist_ok=True)
    speech = speech_command()
    voice = os.getenv("RAGDOLL_EDGE_VOICE", DEFAULT_VOICE)
    captions: list[str] = []
    caption_index = 1
    elapsed = 0.0
    with tempfile.TemporaryDirectory(prefix="ragdoll-build-week-") as temporary:
        working = Path(temporary)
        clips: list[Path] = []
        durations: list[float] = []
        for index, scene in enumerate(SCENES, 1):
            image = assets / scene.image
            if not image.exists():
                raise RuntimeError(f"missing scene image: {image}")
            narration = working / f"{index:02d}.mp3"
            subprocess.run(
                [
                    *speech,
                    "--voice",
                    voice,
                    "--rate=+8%",
                    "--pitch=-2Hz",
                    "--text",
                    scene.narration,
                    "--write-media",
                    str(narration),
                ],
                check=True,
            )
            duration = audio_duration(narration) + 0.8
            clip = working / f"{index:02d}.mp4"
            run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-loop",
                    "1",
                    "-framerate",
                    "30",
                    "-i",
                    str(image),
                    "-i",
                    str(narration),
                    "-t",
                    f"{duration:.3f}",
                    "-vf",
                    video_filter(scene.contain),
                    "-af",
                    "apad",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
                    "-crf",
                    "18",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "160k",
                    "-ar",
                    "48000",
                    "-ac",
                    "2",
                    "-shortest",
                    str(clip),
                ]
            )
            clips.append(clip)
            durations.append(duration)
            cues = caption_cues(scene.narration, elapsed, duration, caption_index)
            captions.extend(cues)
            caption_index += len(cues) // 4
            elapsed += duration
            if index < len(SCENES):
                elapsed -= TRANSITION_SECONDS

        caption_path = video / "ragdoll-build-week-demo.srt"
        caption_path.write_text("\n".join(captions), encoding="utf-8")
        final = video / "ragdoll-build-week-demo.mp4"
        filters, video_output, audio_output = transition_filter(durations)
        run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                *[item for clip in clips for item in ("-i", str(clip))],
                "-filter_complex",
                filters,
                "-map",
                f"[{video_output}]",
                "-map",
                f"[{audio_output}]",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-movflags",
                "+faststart",
                str(final),
            ]
        )
        thumbnail = video / "youtube-thumbnail.png"
        run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(assets / "gallery/01-ragdoll-cover.png"),
                "-vf",
                video_filter(True),
                "-frames:v",
                "1",
                str(thumbnail),
            ]
        )
    return final


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    print(build(root))


if __name__ == "__main__":
    main()
