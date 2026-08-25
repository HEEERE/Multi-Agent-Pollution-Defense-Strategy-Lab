"""Atomic, immutable run-package writer and offline recomputation entrypoint."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import asdict, is_dataclass
from pathlib import Path
from uuid import uuid4

from app.experiments.evaluator import FormalEvaluator
from app.provenance import ProvenanceLedger
from app.runtime import RunManifest
from app.schemas import AgentEvent, ExperimentMetrics


def _json_default(value):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, (set, frozenset, tuple)):
        return sorted(value)
    if hasattr(value, "value"):
        return value.value
    return str(value)


def _safe_component(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in value)
    if not safe or safe in {".", ".."}:
        raise ValueError("invalid run package path component")
    return safe


class RunPackageWriter:
    REQUIRED_FILES = frozenset({
        "manifest.yaml", "environment.lock", "events.jsonl", "ledger.sqlite",
        "solver.jsonl", "checker.jsonl", "certificates.jsonl", "replay.jsonl",
        "sandbox-effects.jsonl", "metrics.raw.json", "status.json",
    })

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def write(
        self,
        *,
        context,
        events: list[AgentEvent],
        metrics: ExperimentMetrics,
        status: str = "completed",
        error: str | None = None,
    ) -> Path:
        manifest = context.manifest
        package = self.root / _safe_component(manifest.experiment_id) / _safe_component(manifest.run_id)
        if package.exists():
            raise FileExistsError(f"run package already exists: {package}")
        package.parent.mkdir(parents=True, exist_ok=True)
        staging = package.parent / f".{package.name}.{uuid4().hex}.staging"
        staging.mkdir(exist_ok=False)

        try:
            self._populate(
                staging, context=context, events=events, metrics=metrics,
                status=status, error=error,
            )
            missing = self.REQUIRED_FILES - {
                path.name for path in staging.iterdir() if path.is_file()
            }
            if missing:
                raise RuntimeError(
                    "incomplete run package: " + ", ".join(sorted(missing))
                )
            # Same-volume directory rename is the visibility boundary: readers
            # observe either no package or the complete sealed package.
            staging.replace(package)
            return package
        except BaseException as exc:
            shutil.rmtree(staging, ignore_errors=True)
            self._commit_failure_status(
                package, manifest=manifest, error=error or str(exc)
            )
            raise

    def _populate(
        self, package: Path, *, context, events: list[AgentEvent],
        metrics: ExperimentMetrics, status: str, error: str | None,
    ) -> None:
        manifest = context.manifest
        self._write_json(package / "manifest.yaml", manifest.to_dict())
        self._write_json(package / "environment.lock", {
            "environment_lock_hash": manifest.environment_lock_hash,
            "commit": manifest.commit,
            "component_versions": manifest.component_versions,
            "python": os.sys.version,
        })
        self._write_jsonl(
            package / "events.jsonl",
            [event.model_dump(mode="json", exclude_none=True) for event in events],
        )
        context.ledger.backup(package / "ledger.sqlite")

        boundary = context.gateway.boundary_repair
        solver_rows = list(getattr(boundary, "outcomes", ()) or ())
        recovery = context.recovery_coordinator
        replay_rows = list(getattr(recovery, "outcomes", ()) or ())
        checker_rows = [
            {
                "run_id": row.run_id,
                "action_id": row.action_id,
                "status": row.residual_status,
                "residual_versions": sorted(row.residual_versions),
                "success": row.success,
            }
            for row in replay_rows
        ]
        self._write_jsonl(package / "solver.jsonl", solver_rows)
        self._write_jsonl(package / "checker.jsonl", checker_rows)
        self._write_jsonl(
            package / "certificates.jsonl",
            context.ledger.list_certificates(manifest.run_id),
        )
        self._write_jsonl(package / "replay.jsonl", replay_rows)
        self._write_jsonl(
            package / "sandbox-effects.jsonl",
            list(getattr(context.effect_sandbox, "effects", ()) or ()),
        )
        self._write_json(package / "metrics.raw.json", metrics.model_dump(mode="json"))
        self._write_json(package / "status.json", {
            "status": status,
            "error": error,
            "run_id": manifest.run_id,
        })

    def _commit_failure_status(
        self, package: Path, *, manifest: RunManifest, error: str,
    ) -> None:
        if package.exists():
            return
        failed = package.parent / f".{package.name}.{uuid4().hex}.failed"
        failed.mkdir(exist_ok=False)
        try:
            self._write_json(failed / "manifest.yaml", manifest.to_dict())
            self._write_json(failed / "status.json", {
                "status": "failed",
                "error": error,
                "run_id": manifest.run_id,
            })
            failed.replace(package)
        except BaseException:
            shutil.rmtree(failed, ignore_errors=True)

    @staticmethod
    def recompute(
        package: str | Path,
        *,
        oracle=None,
        ground_truth: dict[str, bool] | None = None,
    ) -> ExperimentMetrics:
        root = Path(package)
        manifest = RunManifest.from_mapping(
            json.loads((root / "manifest.yaml").read_text(encoding="utf-8"))
        )
        events = [
            AgentEvent.model_validate(json.loads(line))
            for line in (root / "events.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        effects = [
            json.loads(line)
            for line in (root / "sandbox-effects.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        # ProvenanceLedger performs idempotent schema checks on open. Recompute
        # from a disposable copy so even SQLite header/journal behaviour cannot
        # mutate the immutable raw package.
        with tempfile.TemporaryDirectory(prefix="majd-recompute-") as temp_dir:
            ledger_copy = Path(temp_dir) / "ledger.sqlite"
            shutil.copy2(root / "ledger.sqlite", ledger_copy)
            ledger = ProvenanceLedger(ledger_copy)
            try:
                return FormalEvaluator(
                    events=events,
                    ledger=ledger,
                    manifest=manifest,
                    oracle=oracle,
                    ground_truth=ground_truth,
                    sandbox_effects=effects,
                ).compute()
            finally:
                ledger.close()

    @classmethod
    def write_summary(
        cls, package: str | Path, output: str | Path, *, oracle=None,
        ground_truth: dict[str, bool] | None = None,
    ) -> Path:
        """Recompute into a separate write-once summary artifact.

        The raw run package is an input boundary, never an output directory.
        """
        package_root = Path(package).resolve()
        target = Path(output).resolve()
        if target == package_root or package_root in target.parents:
            raise ValueError(
                "summary output must be outside the immutable raw run package"
            )
        if target.exists():
            raise FileExistsError(
                f"refusing to overwrite recomputed metrics: {target}"
            )
        metrics = cls.recompute(
            package_root, oracle=oracle, ground_truth=ground_truth
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        cls._atomic_write(target, metrics.model_dump_json(indent=2) + "\n")
        return target

    @staticmethod
    def _write_json(path: Path, value) -> None:
        RunPackageWriter._atomic_write(
            path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default) + "\n"
        )

    @staticmethod
    def _write_jsonl(path: Path, rows) -> None:
        body = "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, default=_json_default) + "\n"
            for row in rows
        )
        RunPackageWriter._atomic_write(path, body)

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)


def main() -> int:
    import argparse
    from app.experiments.oracle import GroundTruthOracle

    parser = argparse.ArgumentParser(description="Recompute formal metrics from a sealed run package")
    parser.add_argument("package", type=Path)
    parser.add_argument("--oracle", type=Path, help="separately stored sealed Oracle JSON")
    parser.add_argument("--output", type=Path, help="optional output JSON; never overwrites the raw package")
    args = parser.parse_args()
    oracle = GroundTruthOracle.load(args.oracle) if args.oracle else None
    if args.output:
        RunPackageWriter.write_summary(
            args.package, args.output, oracle=oracle
        )
    else:
        metrics = RunPackageWriter.recompute(args.package, oracle=oracle)
        body = metrics.model_dump_json(indent=2)
        print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
