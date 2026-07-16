"""Isolated PDF-to-text worker invoked by the evidence adapter."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from pypdf import PdfReader


def _apply_resource_limits(memory_mib: int, cpu_seconds: int, output_bytes: int) -> None:
    try:
        import resource
    except ImportError as error:  # pragma: no cover - exercised only on non-POSIX platforms
        raise RuntimeError("safe PDF resource limits are unavailable on this platform") from error
    memory_bytes = memory_mib * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(resource.RLIMIT_FSIZE, (output_bytes, output_bytes))


def extract(
    input_path: Path,
    output_path: Path | None,
    max_pages: int,
    max_output_bytes: int | None = None,
    output_fd: int | None = None,
) -> None:
    reader = PdfReader(input_path, strict=True)
    if reader.is_encrypted:
        raise ValueError("encrypted PDFs are not supported")
    if len(reader.pages) > max_pages:
        raise ValueError(f"PDF exceeds the {max_pages}-page limit")
    pages = []
    for number, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        pages.append({"page": number, "text": text})
    payload = json.dumps({"pages": pages})
    if max_output_bytes is not None and len(payload.encode("utf-8")) > max_output_bytes:
        raise ValueError("PDF extraction exceeds the output byte limit")
    if output_fd is not None:
        with os.fdopen(output_fd, "w", encoding="utf-8", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    elif output_path is not None:
        output_path.write_text(payload, encoding="utf-8")
    else:
        raise ValueError("an extractor output destination is required")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--output-fd", type=int)
    parser.add_argument("--max-pages", type=int, required=True)
    parser.add_argument("--max-memory-mib", type=int, required=True)
    parser.add_argument("--max-cpu-seconds", type=int, required=True)
    parser.add_argument("--max-output-bytes", type=int, required=True)
    args = parser.parse_args()
    _apply_resource_limits(args.max_memory_mib, args.max_cpu_seconds, args.max_output_bytes)
    if (args.output is None) == (args.output_fd is None):
        parser.error("provide exactly one output path or --output-fd")
    extract(
        args.input,
        args.output,
        args.max_pages,
        args.max_output_bytes,
        output_fd=args.output_fd,
    )
    if args.output is not None:
        os.chmod(args.output, 0o600)


if __name__ == "__main__":
    main()
