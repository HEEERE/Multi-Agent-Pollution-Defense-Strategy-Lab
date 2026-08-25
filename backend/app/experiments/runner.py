import asyncio
from time import time
from pathlib import Path

from app.defense.manager import create_defense_coordinator
from app.detectors.factory import create_pipeline
from app.event_store import EventStore
from app.experiments.metrics import AggregateMetrics
from app.experiments.evaluator import FormalEvaluator
from app.experiments.artifacts import RunPackageWriter
from app.experiments.methods import METHOD_REGISTRY, MethodUnavailableError
from app.experiments.oracle import GroundTruthOracle
from app.llm.factory import get_llm_client
from app.llm.base import LLMClient
from app.message_bus import MessageBus, clear_run_context, set_run_context
from app.policy.engine import PolicyEngine
from app.schemas import (
    ExperimentConfig,
    ExperimentMetrics,
    ExperimentRun,
    ExperimentStatus,
)
from app.simulation.engine import SimulationEngine
from app.provenance import ProvenanceLedger
from app.provenance.models import ProvenanceLevel, SupportGroup
from app.runtime import RunEngine, RunManifest


class ExperimentTimeoutError(TimeoutError):
    """The immutable per-run wall-clock budget expired."""


class ExperimentRunner:
    def __init__(
        self,
        event_store: EventStore,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.event_store = event_store
        self.llm_client = llm_client or get_llm_client()

    async def run(self, config: ExperimentConfig) -> ExperimentRun:
        experiment_id = config.metadata.get("experiment_id") if config.metadata else None
        if not experiment_id:
            import uuid
            experiment_id = uuid.uuid4().hex[:16]

        run = ExperimentRun(
            experiment_id=str(experiment_id),
            name=config.name,
            config_json=config.model_dump_json(),
            status=ExperimentStatus.RUNNING,
            started_at=time(),
        )
        await self.event_store.store_experiment({
            "experiment_id": run.experiment_id,
            "name": run.name,
            "config_json": run.config_json,
            "status": run.status.value,
            "started_at": run.started_at,
        })

        try:
            metrics_list: list[ExperimentMetrics] = []
            trace_ids: list[str] = []
            policies = config.metadata.get("policies", []) if config.metadata else []

            for iteration in range(config.num_runs):
                bus = MessageBus()
                bus.bind_event_store(self.event_store)
                store_path = getattr(self.event_store, "db_path", None)
                provenance_path = store_path.with_name("provenance.db") if store_path is not None else ":memory:"
                provenance = ProvenanceLedger(provenance_path)
                manifest = self._build_manifest(config, run.experiment_id, iteration)
                if provenance.run_exists(manifest.run_id):
                    raise ValueError(
                        f"refusing to reuse non-isolated provenance run_id: {manifest.run_id}"
                    )
                if bool((config.metadata or {}).get("formal_run")):
                    manifest.validate_formal()
                method = METHOD_REGISTRY.get(manifest.method_id)
                method.ensure_available(manifest.layer)
                runtime = RunEngine(provenance)
                context = runtime.create_run(manifest, policy=method.build_policy(config))
                self._register_support_groups(context)
                if hasattr(self.event_store, "store_run"):
                    await self.event_store.store_run({
                        "run_id": manifest.run_id,
                        "experiment_id": run.experiment_id,
                        "status": "running",
                        "created_at": time(),
                        "started_at": time(),
                    })
                bus.bind_provenance_ledger(provenance, manifest.run_id)
                bus.bind_action_gateway(context.gateway)
                bus.bind_effect_sandbox(context.effect_sandbox)
                iteration_config = config.model_copy(update={
                    "topology": config.topology.model_copy(update={
                        "metadata": {**config.topology.metadata, "run_id": manifest.run_id}
                    })
                })
                set_run_context(manifest.run_id)
                events = []
                package_written = False
                artifact_root = self._artifact_root(config, store_path)
                try:
                    await method.prepare(context, iteration_config)
                    coordinator = create_defense_coordinator(bus, self.event_store)
                    bus.bind_containment_registry(coordinator.containment_registry)

                    if config.detector_pipeline.detectors or policies:
                        pipeline = create_pipeline(
                            config.detector_pipeline,
                            self.llm_client,
                            bus,
                            defense_coordinator=coordinator,
                            policy_engine=PolicyEngine(policies or None),
                        )
                        bus.attach_monitor(pipeline.inspect)

                    # One Oracle per iteration. The runner receives only its
                    # write-only sink, so no online component can read labels back.
                    oracle = GroundTruthOracle(experiment_id=run.experiment_id)
                    engine = SimulationEngine(bus, self.llm_client)
                    try:
                        events = await asyncio.wait_for(
                            method.execute(
                                engine, iteration_config, label_sink=oracle.sink()
                            ),
                            timeout=manifest.budget.wall_clock_s,
                        )
                    except TimeoutError as exc:
                        raise ExperimentTimeoutError(
                            f"run {manifest.run_id} exceeded wall-clock budget "
                            f"of {manifest.budget.wall_clock_s}s"
                        ) from exc
                    # Labels become readable only now that the run has terminated.
                    oracle.seal()
                    metrics = FormalEvaluator(
                        events=events,
                        ledger=provenance,
                        manifest=manifest,
                        oracle=oracle,
                        ground_truth=config.ground_truth,
                        sandbox_effects=context.effect_sandbox.effects,
                    ).compute()
                    metrics = await method.collect(context, events, metrics)
                    metrics.metadata.update({
                        "iteration": iteration + 1,
                        "run_id": manifest.run_id,
                        "manifest": manifest.to_dict(),
                    })
                    # UNKNOWN solver/checker outcomes remain explicit metrics;
                    # they do not erase an otherwise complete raw run package.
                    iteration_status = "completed"
                    if artifact_root is not None:
                        package = RunPackageWriter(artifact_root).write(
                            context=context,
                            events=events,
                            metrics=metrics,
                            status=iteration_status,
                        )
                        package_written = True
                        metrics.metadata["run_package"] = str(package)
                    metrics_list.append(metrics)
                    if events:
                        trace_ids.append(events[0].trace_id)
                    if hasattr(self.event_store, "store_run"):
                        await self.event_store.store_run({
                            "run_id": manifest.run_id,
                            "experiment_id": run.experiment_id,
                            "trace_id": events[0].trace_id if events else None,
                            "status": iteration_status,
                            "metrics_json": metrics.model_dump_json(),
                            "created_at": context.created_at,
                            "started_at": context.created_at,
                            "finished_at": time(),
                        })
                except Exception as iteration_error:
                    failure_status = (
                        "timeout"
                        if isinstance(iteration_error, ExperimentTimeoutError)
                        else "failed"
                    )
                    events = events or list(bus.history)
                    if artifact_root is not None and not package_written:
                        try:
                            RunPackageWriter(artifact_root).write(
                                context=context,
                                events=events,
                                metrics=ExperimentMetrics(metadata={
                                    "run_id": manifest.run_id,
                                    "failure": type(iteration_error).__name__,
                                }),
                                status=failure_status,
                                error=str(iteration_error),
                            )
                        except Exception:
                            # Preserve the original experimental failure. A
                            # package-write failure will still surface through
                            # the final experiment error and existing partial path.
                            pass
                    if hasattr(self.event_store, "store_run"):
                        await self.event_store.store_run({
                            "run_id": manifest.run_id,
                            "experiment_id": run.experiment_id,
                            "status": failure_status,
                            "error": str(iteration_error),
                            "created_at": context.created_at,
                            "started_at": context.created_at,
                            "finished_at": time(),
                        })
                    raise
                finally:
                    await method.cleanup(context)
                    clear_run_context()
                    provenance.close()

            run.trace_id = trace_ids[0] if trace_ids else None
            run.metrics = self._aggregate_metrics(
                metrics_list,
                trace_ids,
                seed=int(config.metadata.get("seed", 0)) if config.metadata else 0,
            )
            run.status = ExperimentStatus.COMPLETED
            run.completed_at = time()

        except MethodUnavailableError as exc:
            run.status = ExperimentStatus.EXCLUDED
            run.error_message = str(exc)
            run.completed_at = time()
        except ExperimentTimeoutError as exc:
            run.status = ExperimentStatus.TIMEOUT
            run.error_message = str(exc)
            run.completed_at = time()
        except Exception as exc:
            run.status = ExperimentStatus.FAILED
            run.error_message = str(exc)
            run.completed_at = time()

        finally:
            clear_run_context()

        # Store result
        await self.event_store.store_experiment({
            "experiment_id": run.experiment_id,
            "name": run.name,
            "config_json": run.config_json,
            "status": run.status.value,
            "trace_id": run.trace_id,
            "metrics_json": run.metrics.model_dump_json() if run.metrics else None,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "error_message": run.error_message,
        })

        return run

    @staticmethod
    def _aggregate_metrics(
        metrics_list: list[ExperimentMetrics],
        trace_ids: list[str],
        seed: int,
    ) -> ExperimentMetrics:
        if not metrics_list:
            return ExperimentMetrics(metadata={"n_runs": 0, "trace_ids": []})

        aggregate = AggregateMetrics(
            [item.model_dump(mode="json") for item in metrics_list],
            seed=seed,
        ).compute()
        integer_fields = {
            name for name, model_field in ExperimentMetrics.model_fields.items()
            if model_field.annotation is int
        }
        values: dict = {}
        for field in ExperimentMetrics.model_fields:
            if field == "metadata":
                continue
            mean_value = aggregate["fields"].get(field, {}).get("mean", 0)
            values[field] = round(mean_value) if field in integer_fields else mean_value
        values["metadata"] = {
            "n_runs": len(metrics_list),
            "trace_ids": trace_ids,
            "seed": seed,
            "aggregate": aggregate,
        }
        return ExperimentMetrics(**values)

    @staticmethod
    def _build_manifest(
        config: ExperimentConfig, experiment_id: str, iteration: int
    ) -> RunManifest:
        metadata = dict(config.metadata or {})
        supplied = dict(metadata.get("manifest", {}) or {})
        base_run_id = str(supplied.get("run_id") or metadata.get("run_id") or experiment_id)
        if config.num_runs > 1 or not (supplied.get("run_id") or metadata.get("run_id")):
            run_id = f"{base_run_id}:{iteration}"
        else:
            run_id = base_run_id
        supplied.update({
            "run_id": run_id,
            "experiment_id": str(supplied.get("experiment_id") or experiment_id),
            "task_id": str(supplied.get("task_id") or metadata.get("task_id") or config.name),
            "topology": supplied.get("topology") or config.topology.model_dump(mode="json"),
            "seed": int(supplied.get("seed", metadata.get("seed", 0))) + iteration,
            "effect_mode": str(supplied.get("effect_mode") or metadata.get("effect_mode", "live")),
            "horizon_closure": str(
                supplied.get("horizon_closure") or metadata.get("horizon_closure", "closed")
            ),
        })
        return RunManifest.from_mapping(supplied)

    @staticmethod
    def _register_support_groups(context) -> None:
        for index, raw in enumerate(context.manifest.support_groups):
            members = tuple(str(item) for item in raw.get("member_version_ids", ()) or ())
            if not members:
                continue
            support_id = str(raw.get("support_id") or f"support_{index}")
            context.ledger.append_support_group(SupportGroup(
                support_id=f"{context.manifest.run_id}:{support_id}",
                run_id=context.manifest.run_id,
                goal_id=str(raw.get("goal_id") or support_id),
                member_version_ids=members,
                verifier_id=str(raw.get("verifier_id") or "manifest"),
                verified=bool(raw.get("verified", True)),
                provenance_level=ProvenanceLevel(str(raw.get("provenance_level", "P1"))),
            ))

    @staticmethod
    def _artifact_root(config: ExperimentConfig, store_path) -> Path | None:
        configured = (config.metadata or {}).get("artifact_root")
        if configured:
            return Path(configured)
        if bool((config.metadata or {}).get("formal_run")):
            return (
                Path(store_path).parent / "run_packages"
                if store_path is not None else Path("run_packages")
            )
        return None
