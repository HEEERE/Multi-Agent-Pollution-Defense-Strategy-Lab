from time import time

from app.defense.manager import create_defense_coordinator
from app.detectors.factory import create_pipeline
from app.event_store import EventStore
from app.experiments.metrics import AggregateMetrics, MetricsComputer
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
from app.actions import ActionGateway


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
            run_id = config.metadata.get("run_id") if config.metadata else None
            if run_id:
                set_run_context(run_id)

            metrics_list: list[ExperimentMetrics] = []
            trace_ids: list[str] = []
            policies = config.metadata.get("policies", []) if config.metadata else []

            for iteration in range(config.num_runs):
                bus = MessageBus()
                bus.bind_event_store(self.event_store)
                store_path = getattr(self.event_store, "db_path", None)
                provenance_path = store_path.with_name("provenance.db") if store_path is not None else ":memory:"
                provenance = ProvenanceLedger(provenance_path)
                provenance_run_id = f"{run.experiment_id}:{iteration}"
                bus.bind_provenance_ledger(provenance, provenance_run_id)
                bus.bind_action_gateway(ActionGateway(provenance, effect_mode="live"))
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
                events = await engine.run_experiment(
                    config, label_sink=oracle.sink()
                )
                # Labels become readable only now that the run has terminated.
                oracle.seal()
                metrics = MetricsComputer(
                    events, config.ground_truth, oracle=oracle
                ).compute()
                metrics.metadata.update({"iteration": iteration + 1})
                metrics_list.append(metrics)
                if events:
                    trace_ids.append(events[0].trace_id)
                provenance.close()

            run.trace_id = trace_ids[0] if trace_ids else None
            run.metrics = self._aggregate_metrics(
                metrics_list,
                trace_ids,
                seed=int(config.metadata.get("seed", 0)) if config.metadata else 0,
            )
            run.status = ExperimentStatus.COMPLETED
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
            "propagation_depth",
            "total_events",
            "threats_detected",
            "threats_blocked",
            "cascade_depth",
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
