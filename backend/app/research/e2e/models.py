"""Role-aware model routing with per-provider concurrency isolation."""

from __future__ import annotations

import asyncio
import time


class RoleModelRouter:
    """Route exact model ids without exposing credentials to run metadata."""

    def __init__(self, clients: dict[str, object], *, primary_model: str,
                 minimum_interval_s: float = 0.5) -> None:
        if primary_model not in clients:
            raise ValueError("primary model is missing from role router")
        self.clients = dict(clients)
        self.primary_model = primary_model
        self.model = primary_model
        self.llm_ready = all(bool(getattr(client, "llm_ready", True)) for client in clients.values())
        self._locks = {model: asyncio.Lock() for model in clients}
        self._last_started = {model: 0.0 for model in clients}
        self.minimum_interval_s = float(minimum_interval_s)

    def client_for(self, model_id: str):
        try:
            return self.clients[model_id]
        except KeyError as exc:
            raise RuntimeError(f"no client configured for exact model id {model_id}") from exc

    async def chat_for_model(self, model_id: str, messages, **kwargs):
        client = self.client_for(model_id)
        async with self._locks[model_id]:
            remaining = self.minimum_interval_s - (
                time.monotonic() - self._last_started[model_id]
            )
            if remaining > 0:
                await asyncio.sleep(remaining)
            self._last_started[model_id] = time.monotonic()
            return await client.chat(messages, **kwargs)

    async def chat(self, messages, **kwargs):
        """Compatibility path for legacy single-client simulations."""
        return await self.chat_for_model(self.primary_model, messages, **kwargs)
