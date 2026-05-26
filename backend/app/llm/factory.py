from functools import lru_cache

from app.core.config import get_settings
from app.llm.mimo_client import MiMoClient


@lru_cache
def get_llm_client() -> MiMoClient:
    return MiMoClient(get_settings())
