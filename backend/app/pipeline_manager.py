from app.detectors.factory import create_default_pipeline
from app.llm.factory import get_llm_client_manager
from app.message_bus import message_bus


class PipelineManager:
    """Owns the detector pipeline lifecycle. Rebuilds from current settings
    (including LLM config) so runtime settings changes take effect on the
    next event through the pipeline."""

    def __init__(self) -> None:
        self._pipeline = None

    def rebuild(self) -> None:
        from app.defense.manager import get_defense_coordinator

        llm_client = get_llm_client_manager().get_client()
        defense_coordinator = get_defense_coordinator(
            bus=message_bus,
            event_store=message_bus.event_store,
        )
        self._pipeline = create_default_pipeline(
            llm_client=llm_client,
            bus=message_bus,
            defense_coordinator=defense_coordinator,
        )
        message_bus.replace_monitors([self._pipeline.inspect])

    @property
    def pipeline(self):
        return self._pipeline


_pipeline_manager: PipelineManager | None = None


def get_pipeline_manager() -> PipelineManager:
    global _pipeline_manager
    if _pipeline_manager is None:
        _pipeline_manager = PipelineManager()
    return _pipeline_manager
