"""Immutable archive for official external-benchmark raw outputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
from uuid import uuid4


def _component(value: str) -> str:
    safe = "".join(
        character if character.isalnum() or character in {"-", "_", "."} else "_"
        for character in value
    )
    if not safe or safe in {".", ".."}:
        raise ValueError("invalid external archive path component")
    return safe


class ExternalRawArchive:
    """Write-once, checksum-addressed storage for official raw responses."""

    METADATA = "archive.json"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def archive_bytes(
        self, *, benchmark_id: str, run_id: str, filename: str, content: bytes,
    ) -> Path:
        benchmark = _component(benchmark_id)
        run = _component(run_id)
        raw_name = _component(filename)
        target = self.root / benchmark / run
        if target.exists():
            raise FileExistsError(f"external raw archive already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = target.parent / f".{run}.{uuid4().hex}.staging"
        staging.mkdir(exist_ok=False)
        try:
            raw = staging / raw_name
            raw.write_bytes(content)
            digest = hashlib.sha256(content).hexdigest()
            metadata = {
                "schema_version": "external-raw-archive-v1",
                "benchmark_id": benchmark_id,
                "run_id": run_id,
                "filename": raw_name,
                "sha256": digest,
                "size_bytes": len(content),
                "immutable": True,
            }
            (staging / self.METADATA).write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            for path in staging.iterdir():
                path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
            staging.replace(target)
            return target
        except BaseException:
            for path in staging.glob("*"):
                path.chmod(stat.S_IWRITE | stat.S_IREAD)
                path.unlink(missing_ok=True)
            staging.rmdir()
            raise

    @classmethod
    def verify(cls, archive: str | Path) -> bool:
        root = Path(archive)
        try:
            metadata = json.loads(
                (root / cls.METADATA).read_text(encoding="utf-8")
            )
            raw = root / str(metadata["filename"])
            content = raw.read_bytes()
        except (OSError, KeyError, json.JSONDecodeError, TypeError):
            return False
        return (
            metadata.get("immutable") is True
            and metadata.get("size_bytes") == len(content)
            and metadata.get("sha256") == hashlib.sha256(content).hexdigest()
        )
