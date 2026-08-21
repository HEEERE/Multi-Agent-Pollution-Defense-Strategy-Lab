from app.core.config import get_settings
from app.llm.mimo_client import MiMoClient
from app.settings_manager import get_settings_manager


class LLMClientManager:
    """Owns the LLM client lifecycle.

    Non-secret runtime options come from SettingsManager. The API key is read
    only from the process environment and is never persisted or returned by
    the settings API.
    """

    def __init__(self) -> None:
        self._client: MiMoClient | None = None

    def get_client(self) -> MiMoClient:
        if self._client is None:
            self._rebuild()
        return self._client  # type: ignore[return-value]

    def _rebuild(self) -> MiMoClient:
        mgr = get_settings_manager()
        settings = get_settings()
        # Settings-DB values win when present so the UI can retune a live run,
        # but they fall back to the process environment. Capability flags default
        # from env only: they describe the model, not an operator preference.
        self._client = MiMoClient(
            api_key=settings.mimo_api_key,
            base_url=str(
                mgr.get_value_sync("llm", "llm.base_url", "") or settings.mimo_base_url
            ),
            model=str(mgr.get_value_sync("llm", "llm.model", "") or settings.mimo_model),
            enabled=bool(
                mgr.get_value_sync("llm", "llm.enabled", settings.llm_enabled)
            ),
            temperature=float(
                mgr.get_value_sync("llm", "llm.temperature", settings.llm_temperature)
            ),
            max_tokens=int(
                mgr.get_value_sync("llm", "llm.max_tokens", settings.llm_max_tokens)
            ),
            request_timeout=float(
                mgr.get_value_sync(
                    "llm", "llm.request_timeout", settings.llm_request_timeout_seconds
                )
            ),
            max_input_tokens=settings.llm_max_input_tokens,
            max_output_ceiling=settings.llm_max_output_ceiling,
            tool_calling_enabled=settings.llm_tool_calling_enabled,
            thinking_enabled=settings.llm_thinking_enabled,
            reasoning_effort=settings.llm_reasoning_effort,
        )
        return self._client

    def invalidate(self) -> None:
        self._client = None
