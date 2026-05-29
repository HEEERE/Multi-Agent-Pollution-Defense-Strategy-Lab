from app.llm.mimo_client import MiMoClient
from app.settings_manager import get_settings_manager


class LLMClientManager:
    """Owns the LLM client lifecycle. Reads config from SettingsManager so
    runtime settings changes (via PUT /api/settings/llm) take effect on the
    next pipeline rebuild."""

    def __init__(self) -> None:
        self._client: MiMoClient | None = None

    def get_client(self) -> MiMoClient:
        if self._client is None:
            self._rebuild()
        return self._client  # type: ignore[return-value]

    def _rebuild(self) -> MiMoClient:
        mgr = get_settings_manager()
        self._client = MiMoClient(
            api_key=str(mgr.get_value_sync("llm", "llm.api_key", "")),
            base_url=str(mgr.get_value_sync("llm", "llm.base_url", "")),
            model=str(mgr.get_value_sync("llm", "llm.model", "")),
            enabled=bool(mgr.get_value_sync("llm", "llm.enabled", False)),
            temperature=float(mgr.get_value_sync("llm", "llm.temperature", 0.2)),
            max_tokens=int(mgr.get_value_sync("llm", "llm.max_tokens", 700)),
            request_timeout=float(mgr.get_value_sync("llm", "llm.request_timeout", 45)),
        )
        return self._client

    def invalidate(self) -> None:
        self._client = None
