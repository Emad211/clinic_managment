"""Owner-only, atomic report-file helpers for clinical migration artifacts."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Mapping


class SecureReportIOError(Exception):
    """Raised when a private report cannot be written safely."""


def ensure_distinct_artifact_paths(
    *,
    inputs: Mapping[str, str | Path],
    outputs: Mapping[str, str | Path | None],
) -> None:
    """Reject output paths that alias an input or another output.

    Equality is checked both lexically (absolute paths) and, when both paths
    already exist, by inode via ``samefile``. This closes accidental overwrite
    through alternative path spellings or hard links. Symlink output targets are
    still rejected by ``write_private_text`` itself.
    """
    normalized_inputs = {
        label: Path(path).expanduser().absolute()
        for label, path in inputs.items()
    }
    normalized_outputs = {
        label: Path(path).expanduser().absolute()
        for label, path in outputs.items()
        if path is not None
    }

    for output_label, output_path in normalized_outputs.items():
        for input_label, input_path in normalized_inputs.items():
            if _paths_alias(output_path, input_path):
                raise SecureReportIOError(
                    f"Output {output_label} must not overwrite input {input_label}: "
                    f"{output_path}"
                )

    output_items = list(normalized_outputs.items())
    for index, (left_label, left_path) in enumerate(output_items):
        for right_label, right_path in output_items[index + 1 :]:
            if _paths_alias(left_path, right_path):
                raise SecureReportIOError(
                    f"Output paths {left_label} and {right_label} must be distinct: "
                    f"{left_path}"
                )


def _paths_alias(left: Path, right: Path) -> bool:
    if left == right:
        return True
    if left.exists() and right.exists():
        try:
            return os.path.samefile(left, right)
        except OSError:
            return False
    return False


def write_private_text(path: str | Path, content: str) -> Path:
    """Atomically replace a regular file using 0700 directories and mode 0600.

    Symlinks and non-regular targets are rejected. The temporary file is created
    in the destination directory so ``os.replace`` remains atomic on one
    filesystem. The caller receives the absolute final path.
    """
    target = Path(path).expanduser().absolute()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if target.is_symlink():
        raise SecureReportIOError(
            f"Refusing to write a private report through a symlink: {target}"
        )
    if target.exists() and not target.is_file():
        raise SecureReportIOError(
            f"Private report path is not a regular file: {target}"
        )

    descriptor: int | None = None
    temporary_name: str | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            text=True,
        )
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, target)
        temporary_name = None
        os.chmod(target, 0o600)
        return target
    except OSError as exc:
        raise SecureReportIOError(f"Failed to write private report: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
