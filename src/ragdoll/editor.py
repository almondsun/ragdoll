"""Safe external-editor integration for multiline terminal prompts."""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path

MAX_EDITOR_BYTES = 1024 * 1024


class ExternalEditorError(ValueError):
    """Raised when the configured editor cannot safely return a prompt."""


def edit_text(initial: str, environment: Mapping[str, str] | None = None) -> str:
    """Edit text with ``$VISUAL``/``$EDITOR`` without invoking a shell."""
    if len(initial.encode("utf-8")) > MAX_EDITOR_BYTES:
        raise ExternalEditorError("Prompt exceeds the 1 MiB editor limit.")
    env = os.environ if environment is None else environment
    editor = env.get("VISUAL") or env.get("EDITOR")
    if not editor:
        raise ExternalEditorError("Set VISUAL or EDITOR before using Ctrl+G.")
    try:
        argv = shlex.split(editor)
    except ValueError as error:
        raise ExternalEditorError(f"Invalid editor command: {error}") from error
    if not argv or any("\x00" in argument for argument in argv):
        raise ExternalEditorError("The editor command is empty or invalid.")

    descriptor, raw_path = tempfile.mkstemp(prefix="ragdoll-prompt-", suffix=".md")
    path = Path(raw_path)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(initial)
        result = subprocess.run([*argv, str(path)], check=False, shell=False)
        if result.returncode != 0:
            raise ExternalEditorError(f"Editor exited with status {result.returncode}.")
        with path.open("rb") as handle:
            edited = handle.read(MAX_EDITOR_BYTES + 1)
        if len(edited) > MAX_EDITOR_BYTES:
            raise ExternalEditorError("Edited prompt exceeds the 1 MiB limit.")
        try:
            return edited.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ExternalEditorError("Edited prompt is not valid UTF-8.") from error
    except OSError as error:
        raise ExternalEditorError(f"Could not use external editor: {error}") from error
    finally:
        path.unlink(missing_ok=True)
