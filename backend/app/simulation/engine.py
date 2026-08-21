from app.llm.base import LLMClient
from app.message_bus import MessageBus
from app.schemas import AgentEvent, ExperimentConfig
from app.simulation.runner import SimulationRunner


class SimulationEngine:
    def __init__(self, bus: MessageBus, llm_client: LLMClient | None = None) -> None:
        self.bus = bus
        self.llm_client = llm_client

    async def run_experiment(
        self, config: ExperimentConfig, label_sink=None
    ) -> list[AgentEvent]:
        runner = SimulationRunner(
            config=config.topology,
            bus=self.bus,
            llm_client=self.llm_client,
            label_sink=label_sink,
        )
        return await runner.run()

    async def run_topology(self, topology_config, label_sink=None) -> list[AgentEvent]:
        runner = SimulationRunner(
            config=topology_config,
            bus=self.bus,
            llm_client=self.llm_client,
            label_sink=label_sink,
        )
        return await runner.run()
