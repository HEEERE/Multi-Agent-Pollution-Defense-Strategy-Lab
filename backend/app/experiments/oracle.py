"""Offline ground-truth Oracle.

Labels live here, keyed by event id, and are readable only after a run finishes.
Nothing under the online runtime may import this module; the boundary is asserted
by ``tests/test_research_isolation.py``.

Why this exists: labels used to travel inside ``AgentEvent.metadata`` as
``ground_truth_threat``, and ``SemanticDetector`` read that field to auto-tune its
own thresholds during the run. An online detector consuming the label invalidates
every detection metric it then produces, so the label has to be structurally out
of reach rather than merely unused by convention.

The runtime never references this class. Instead the harness hands the runner a
``label_sink`` callback, so the producer of a label does not need to know where
labels are stored (v4 plan section 6.7).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

#: Signature the simulation runner accepts. ``(event_id, is_threat, kind)``.
LabelSink = Callable[[str, bool, str], None]


@dataclass
class GroundTruthOracle:
    """Hidden labels for one experiment.

    Deliberately not a singleton and not reachable from a RunContext: an online
    component must not be able to find it.
    """

    experiment_id: str = ""
    labels: dict[str, bool] = field(default_factory=dict)
    kinds: dict[str, str] = field(default_factory=dict)

    _sealed: bool = field(default=False, repr=False)

    # -- write side (run time) ---------------------------------------------

    def sink(self) -> LabelSink:
        """A callback the harness can hand to the runner.

        Write-only by construction: the closure exposes no way to read a label
        back, so passing it into the runtime cannot leak ground truth into a
        detector.
        """

        def record(event_id: str, is_threat: bool, kind: str = "") -> None:
            if self._sealed:
                raise RuntimeError(
                    "oracle is sealed; the run has ended and labels are frozen"
                )
            self.labels[event_id] = bool(is_threat)
            if kind:
                self.kinds[event_id] = kind

        return record

    def seal(self) -> None:
        """Close the write side. Called when the run terminates."""
        self._sealed = True

    @property
    def sealed(self) -> bool:
        return self._sealed

    # -- read side (evaluation time only) ----------------------------------

    def label_for(self, event_id: str) -> bool | None:
        """Look up one label. Only valid after :meth:`seal`."""
        if not self._sealed:
            raise RuntimeError(
                "refusing to read ground truth before the run has ended; "
                "reading labels mid-run is what invalidates the metrics"
            )
        return self.labels.get(event_id)

    def all_labels(self) -> dict[str, bool]:
        if not self._sealed:
            raise RuntimeError("refusing to read ground truth before seal()")
        return dict(self.labels)

    @property
    def threat_count(self) -> int:
        return sum(1 for v in self.labels.values() if v)

    # -- persistence -------------------------------------------------------

    def to_json(self) -> str:
        return json.dumps(
            {
                "experiment_id": self.experiment_id,
                "labels": self.labels,
                "kinds": self.kinds,
            },
            indent=2,
        )

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "GroundTruthOracle":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        oracle = cls(
            experiment_id=data.get("experiment_id", ""),
            labels={k: bool(v) for k, v in (data.get("labels") or {}).items()},
            kinds=dict(data.get("kinds") or {}),
        )
        oracle.seal()
        return oracle
