import json
from time import time

from app.detectors.factory import create_pipeline
from app.event_store import EventStore
from app.experiments.metrics import MetricsComputer
from app.llm.factory import get_llm_client
from app.llm.base import LLMClient
from app.message_bus import MessageBus
from app.schemas import (
    AgentEvent,
    ExperimentConfig,
    ExperimentRun,
    ExperimentStatus,
)
from app.simulation.engine import SimulationEngine


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
            bus = MessageBus()
            bus.bind_event_store(self.event_store)

            # Build detector pipeline
            if config.detector_pipeline.detectors:
                pipeline = create_pipeline(config.detector_pipeline, self.llm_client)
                bus.attach_monitor(pipeline.inspect)

            # Run simulation
            engine = SimulationEngine(bus, self.llm_client)
            events = await engine.run_experiment(config)

            # Persist events
            for e in events:
                await self.event_store.store_event(e)

            # Compute metrics
            metrics = MetricsComputer(events, config.ground_truth).compute()

            run.trace_id = events[0].trace_id if events else None
            run.metrics = metrics
            run.status = ExperimentStatus.COMPLETED
            run.completed_at = time()

        except Exception as exc:
            run.status = ExperimentStatus.FAILED
            run.error_message = str(exc)
            run.completed_at = time()

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
