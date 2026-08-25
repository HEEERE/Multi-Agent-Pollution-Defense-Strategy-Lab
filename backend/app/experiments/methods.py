"""Method-adapter contract used by every formal experiment run."""

from __future__ import annotations

from dataclasses import dataclass

from app.actions import DeterministicPolicy, SecurityDecision
from app.actions.policy import PolicyDecision


class MethodUnavailableError(RuntimeError):
    pass


class _AllowAllPolicy(DeterministicPolicy):
    """Intentional B0 baseline; the gateway and dry-run barrier still apply."""

    def evaluate(self, request, ledger) -> PolicyDecision:
        return PolicyDecision(SecurityDecision.ALLOW, "baseline_no_defense")


class _DenyAllPolicy(DeterministicPolicy):
    def evaluate(self, request, ledger) -> PolicyDecision:
        return PolicyDecision(SecurityDecision.DENY, "baseline_deny_all", False)


@dataclass(frozen=True)
class RuntimeMethodAdapter:
    method_id: str
    policy_mode: str = "deterministic"
    version: str = "runtime-v1"
    applicable_layers: frozenset[str] = frozenset({"E"})
    cost_components: tuple[str, ...] = ("C_op", "L_task", "C_replay", "C_human")
    failure_semantics: str = "FAILED"
    available: bool = True
    unavailable_reason: str = ""

    def ensure_available(self, layer: str) -> None:
        if layer not in self.applicable_layers:
            raise MethodUnavailableError(
                f"method {self.method_id} is not applicable to layer {layer}"
            )
        if not self.available:
            raise MethodUnavailableError(
                f"method {self.method_id} unavailable: {self.unavailable_reason}"
            )

    def build_policy(self, config) -> DeterministicPolicy:
        if self.policy_mode == "allow_all":
            return _AllowAllPolicy()
        if self.policy_mode == "deny_all":
            return _DenyAllPolicy()
        capabilities: dict[str, set[str]] = {}
        scopes: dict[str, set[str]] = {}
        for node in config.topology.nodes:
            node_caps = set(node.metadata.get("capabilities", ()) or ())
            if node_caps:
                capabilities[node.node_id] = node_caps
            node_scopes = node.metadata.get("resource_scopes")
            if node_scopes is not None:
                scopes[node.node_id] = set(node_scopes or ())
        return DeterministicPolicy(capabilities=capabilities, scopes=scopes)

    async def prepare(self, context, config) -> None:
        self.ensure_available(context.manifest.layer)
        context.ledger.increment_metric(context.manifest.run_id, f"method:{self.method_id}", 1)

    async def execute(self, engine, config, *, label_sink=None):
        return await engine.run_experiment(config, label_sink=label_sink)

    async def collect(self, context, events, metrics):
        metrics.metadata["method_id"] = self.method_id
        return metrics

    async def cleanup(self, context) -> None:
        return None


class MethodRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, RuntimeMethodAdapter] = {}

    def register(self, adapter: RuntimeMethodAdapter) -> None:
        if adapter.method_id in self._adapters:
            raise ValueError(f"duplicate method adapter: {adapter.method_id}")
        self._adapters[adapter.method_id] = adapter

    def get(self, method_id: str) -> RuntimeMethodAdapter:
        try:
            return self._adapters[method_id]
        except KeyError as exc:
            raise ValueError(f"unknown formal method_id: {method_id}") from exc

    def available(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))

    def describe(self) -> list[dict]:
        return [
            {
                "method_id": adapter.method_id,
                "version": adapter.version,
                "applicable_layers": sorted(adapter.applicable_layers),
                "cost_components": list(adapter.cost_components),
                "failure_semantics": adapter.failure_semantics,
                "available": adapter.available,
                "unavailable_reason": adapter.unavailable_reason,
            }
            for adapter in sorted(self._adapters.values(), key=lambda item: item.method_id)
        ]


METHOD_REGISTRY = MethodRegistry()
METHOD_REGISTRY.register(RuntimeMethodAdapter("raise_asymmetric_v1"))
METHOD_REGISTRY.register(RuntimeMethodAdapter("b1_conservative"))
METHOD_REGISTRY.register(RuntimeMethodAdapter("b0_no_defense", "allow_all"))
METHOD_REGISTRY.register(RuntimeMethodAdapter("deny_all", "deny_all"))
for _method_id, _layers, _reason in (
    ("full_reset", frozenset({"M", "E"}), "runtime full-reset state strategy is not implemented"),
    ("b1_frozen_majd_guard", frozenset({"E"}), "frozen legacy component/version bundle is not present"),
    ("b7_simplified", frozenset({"M", "E"}), "M-layer code is not yet adapted to the formal runtime"),
    ("b7_faithful", frozenset({"E"}), "faithful paper implementation and version pin are not present"),
    ("b9_naive_compose", frozenset({"M", "E"}), "M-layer composition is not yet adapted to the formal runtime"),
    ("raise_conservative", frozenset({"M", "E"}), "conservative-only boundary strategy is not implemented"),
):
    METHOD_REGISTRY.register(RuntimeMethodAdapter(
        method_id=_method_id,
        applicable_layers=_layers,
        available=False,
        unavailable_reason=_reason,
        failure_semantics="EXCLUDED",
    ))
