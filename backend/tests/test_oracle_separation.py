"""Ground truth must be structurally unreachable from the online runtime.

The defect this pins down was live: ``SimulationRunner`` wrote
``ground_truth_threat`` into ``AgentEvent.metadata``, and ``SemanticDetector``
read that field to auto-tune its per-category thresholds during the run. A
detector calibrating on the answer key makes its own precision/recall figures
meaningless, so the label has to be out of reach by construction rather than by
convention.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.experiments.oracle import GroundTruthOracle
from app.message_bus import MessageBus
from app.schemas import (
    EdgeConfig,
    InjectionConfig,
    InjectionType,
    NodeConfig,
    TopologyConfig,
)
from app.simulation.runner import SimulationRunner

APP = Path(__file__).resolve().parent.parent / "app"

# Everything except the offline experiment package.
RUNTIME_DIRS = (
    "agents",
    "api",
    "defense",
    "detectors",
    "gateway",
    "llm",
    "monitoring",
    "policy",
    "services",
    "simulation",
    "skills",
    "strategy",
    "tools",
    "trace_graph",
)


class TestNoLabelInRuntimeSource:
    def test_runtime_never_reads_a_ground_truth_field(self):
        """No runtime module may read a ``ground_truth*`` key or attribute."""
        offenders: list[str] = []
        for d in RUNTIME_DIRS:
            root = APP / d
            if not root.is_dir():
                continue
            for path in root.rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    # metadata.get("ground_truth_threat") / ["ground_truth..."]
                    if isinstance(node, ast.Constant) and isinstance(
                        node.value, str
                    ):
                        if node.value.startswith("ground_truth"):
                            offenders.append(
                                f"{path.relative_to(APP)}: string {node.value!r}"
                            )
                    # obj.ground_truth
                    if isinstance(node, ast.Attribute) and node.attr.startswith(
                        "ground_truth"
                    ):
                        offenders.append(
                            f"{path.relative_to(APP)}: attribute .{node.attr}"
                        )
        assert not offenders, (
            "online runtime touches ground truth:\n  " + "\n  ".join(offenders)
        )

    def test_runtime_cannot_import_the_oracle(self):
        offenders: list[str] = []
        for d in RUNTIME_DIRS:
            root = APP / d
            if not root.is_dir():
                continue
            for path in root.rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    mods: list[str] = []
                    if isinstance(node, ast.Import):
                        mods = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        mods = [node.module]
                    for m in mods:
                        if "experiments.oracle" in m:
                            offenders.append(f"{path.relative_to(APP)}: {m}")
        assert not offenders, (
            "online runtime imports the Oracle:\n  " + "\n  ".join(offenders)
        )


class TestInjectionDoesNotLabelTheEvent:
    async def test_injected_event_carries_no_label(self):
        bus = MessageBus()
        cfg = TopologyConfig(
            name="inj",
            nodes=[
                NodeConfig(node_id="gateway", node_type="gateway"),
                NodeConfig(node_id="agent_a", node_type="agent"),
            ],
            edges=[EdgeConfig(source="gateway", target="agent_a")],
            injections=[
                InjectionConfig(
                    injection_type=InjectionType.RAG_POISONING,
                    source_node="gateway",
                    target_node="agent_a",
                    payload="malicious",
                    turn=0,
                )
            ],
            max_turns=1,
        )
        oracle = GroundTruthOracle()
        runner = SimulationRunner(cfg, bus, None, label_sink=oracle.sink())
        await runner.run()

        assert bus.history, "no event was published"
        for e in bus.history:
            leaked = [k for k in e.metadata if k.startswith("ground_truth")]
            assert not leaked, f"event {e.event_id} leaked {leaked}"

        oracle.seal()
        assert oracle.threat_count == 1, "the label never reached the oracle"

    async def test_injection_type_is_still_recorded(self):
        """Removing the label must not remove legitimate provenance metadata."""
        bus = MessageBus()
        cfg = TopologyConfig(
            name="inj",
            nodes=[NodeConfig(node_id="agent_a", node_type="agent")],
            injections=[
                InjectionConfig(
                    injection_type=InjectionType.PROMPT_INJECTION,
                    source_node="gateway",
                    target_node="agent_a",
                    payload="x",
                    turn=0,
                )
            ],
            max_turns=1,
        )
        await SimulationRunner(cfg, bus, None).run()
        assert any(
            e.metadata.get("injection_type") == "prompt_injection"
            for e in bus.history
        )


class TestOracleAccessDiscipline:
    def test_reading_before_seal_is_refused(self):
        """Mid-run label access is the failure mode; it must raise, not warn."""
        o = GroundTruthOracle()
        o.sink()("e1", True, "k")
        with pytest.raises(RuntimeError, match="before the run has ended"):
            o.label_for("e1")
        with pytest.raises(RuntimeError, match="before seal"):
            o.all_labels()

    def test_writing_after_seal_is_refused(self):
        o = GroundTruthOracle()
        sink = o.sink()
        sink("e1", True, "k")
        o.seal()
        with pytest.raises(RuntimeError, match="sealed"):
            sink("e2", False, "k")

    def test_sink_is_write_only(self):
        """The sink handed to the runtime must expose no read path."""
        o = GroundTruthOracle()
        sink = o.sink()
        assert not hasattr(sink, "labels")
        assert not hasattr(sink, "label_for")
        # A closure over the oracle would still be reachable via __closure__,
        # but only for code that already imports the oracle module -- which the
        # isolation test above forbids for runtime packages.
        assert callable(sink)

    def test_round_trip_through_disk(self, tmp_path):
        o = GroundTruthOracle(experiment_id="exp1")
        s = o.sink()
        s("e1", True, "rag_poisoning")
        s("e2", False, "benign")
        o.seal()
        p = tmp_path / "oracle.json"
        o.save(p)

        loaded = GroundTruthOracle.load(p)
        assert loaded.sealed
        assert loaded.label_for("e1") is True
        assert loaded.label_for("e2") is False
        assert loaded.threat_count == 1
        assert loaded.kinds["e1"] == "rag_poisoning"


class TestConfigObjectIsNotALeakPath:
    """``ExperimentConfig`` still carries a legacy ``ground_truth`` map.

    That is acceptable for the harness, but the object must not be handed to a
    detector or to the simulation runner, or the label becomes reachable again
    through configuration rather than through event metadata.
    """

    def test_pipeline_receives_only_the_detector_subconfig(self):
        import inspect

        from app.detectors.factory import create_pipeline

        params = inspect.signature(create_pipeline).parameters
        first = next(iter(params.values()))
        annotation = str(first.annotation)
        assert "ExperimentConfig" not in annotation, (
            "create_pipeline takes the whole ExperimentConfig, which carries "
            "ground_truth"
        )
        assert "DetectorPipelineConfig" in annotation

    def test_simulation_runner_receives_only_the_topology(self):
        import inspect

        params = inspect.signature(SimulationRunner.__init__).parameters
        annotation = str(params["config"].annotation)
        assert "ExperimentConfig" not in annotation, (
            "SimulationRunner takes the whole ExperimentConfig"
        )
        assert "TopologyConfig" in annotation

    def test_runner_has_no_attribute_exposing_labels(self):
        oracle = GroundTruthOracle()
        runner = SimulationRunner(TopologyConfig(), MessageBus(), None,
                                  label_sink=oracle.sink())
        for name in dir(runner):
            assert not name.startswith("ground_truth"), (
                f"runner exposes {name}"
            )


class TestDetectorNoLongerCalibratesOnLabels:
    def test_auto_calibrate_defaults_off(self):
        from app.settings_manager import FACTORY_DEFAULTS

        value = FACTORY_DEFAULTS["detectors"]["semantic.auto_calibrate"]
        assert value is False, (
            "online auto-calibration is on by default; it required a ground "
            "truth label on the event"
        )

    def test_record_calibration_is_inert(self):
        """Even if called with a labelled event, nothing may be learned."""
        from app.detectors.semantic_detector import SemanticDetector
        from app.schemas import AgentEvent, EventType

        det = SemanticDetector(auto_calibrate=True)
        event = AgentEvent(
            event_id="e1",
            trace_id="t",
            event_type=EventType.INPUT,
            source_node="a",
            target_node="b",
            payload_snippet="something long enough to inspect",
            metadata={"ground_truth_threat": True},
        )
        det._record_calibration(event, "rag_poisoning", 0.9, True)
        assert not det._category_stats, (
            "detector still accumulates calibration state from a label"
        )
