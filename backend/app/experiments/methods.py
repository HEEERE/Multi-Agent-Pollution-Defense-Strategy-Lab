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
    boundary_mode: str = "asymmetric"
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
        if self.boundary_mode == "none":
            context.gateway.bind_boundary_repair(None)
        elif self.boundary_mode != "asymmetric":
            from app.experiments.baseline_boundaries import build_boundary_strategy

            context.gateway.bind_boundary_repair(
                build_boundary_strategy(self.boundary_mode, context)
            )
        context.ledger.increment_metric(context.manifest.run_id, f"method:{self.method_id}", 1)

    async def execute(self, engine, config, *, label_sink=None, context=None):
        if bool((config.metadata or {}).get("formal_e2e_case")):
            if context is None:
                raise RuntimeError("formal E2E execution requires the RunContext")
            from app.research.e2e.workload import execute_formal_case

            return await execute_formal_case(
                context=context,
                llm_client=engine.llm_client,
                config=config,
                label_sink=label_sink,
            )
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


FORMAL_E_METHOD_IDS = (
    "b0_no_defense",
    "deny_all",
    "full_reset",
    "b1_frozen_majd_guard",
    "b7_faithful",
    "b9_naive_compose",
    "raise_conservative",
    "raise_asymmetric_v1",
)


METHOD_REGISTRY = MethodRegistry()
METHOD_REGISTRY.register(RuntimeMethodAdapter("raise_asymmetric_v1"))
METHOD_REGISTRY.register(RuntimeMethodAdapter("b1_conservative", boundary_mode="none"))
METHOD_REGISTRY.register(RuntimeMethodAdapter(
    "b0_no_defense", policy_mode="allow_all", boundary_mode="none"
))
METHOD_REGISTRY.register(RuntimeMethodAdapter(
    "deny_all", policy_mode="deny_all", boundary_mode="none"
))
METHOD_REGISTRY.register(RuntimeMethodAdapter(
    "full_reset", boundary_mode="full_reset", applicable_layers=frozenset({"M", "E"})
))
METHOD_REGISTRY.register(RuntimeMethodAdapter(
    "b1_frozen_majd_guard", boundary_mode="none", version="majd-guard-frozen-v1"
))
METHOD_REGISTRY.register(RuntimeMethodAdapter(
    "b9_naive_compose", boundary_mode="naive_compose",
    applicable_layers=frozenset({"M", "E"}), version="three-stage-v1"
))
METHOD_REGISTRY.register(RuntimeMethodAdapter(
    "raise_conservative", boundary_mode="conservative",
    applicable_layers=frozenset({"M", "E"}), version="conservative-v1"
))
for _method_id, _layers, _reason in (
    ("b7_simplified", frozenset({"M", "E"}), "simplified rollback is not part of the frozen eight-method E matrix"),
    ("b7_faithful", frozenset({"E"}), "faithful paper implementation and version pin are not present"),
):
    METHOD_REGISTRY.register(RuntimeMethodAdapter(
        method_id=_method_id,
        applicable_layers=_layers,
        available=False,
        unavailable_reason=_reason,
        failure_semantics="EXCLUDED",
    ))
