from app.llm.client_manager import LLMClientManager
from app.llm.mimo_client import MiMoClient

_llm_client_manager: LLMClientManager | None = None


def get_llm_client_manager() -> LLMClientManager:
    global _llm_client_manager
    if _llm_client_manager is None:
        _llm_client_manager = LLMClientManager()
    return _llm_client_manager


def get_llm_client() -> MiMoClient:
    return get_llm_client_manager().get_client()
