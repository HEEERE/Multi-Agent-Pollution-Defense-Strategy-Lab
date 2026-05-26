"""Fake Tools — harmless mirrors of real tools for honeypot environments.

These tools respond with convincing but entirely sanitized data. Every response
includes a tracking watermark for post-incident audit trails. They also log
what the attacker was attempting to access or execute.
"""

from app.message_bus import MessageBus
from app.schemas import ActionTaken, AgentEvent, EventStatus, EventType


class FakeTool:
    def __init__(self, node_id: str, bus: MessageBus, tool_type: str = "generic") -> None:
        self.node_id = node_id
        self.bus = bus
        self.tool_type = tool_type
        self._request_log: list[dict] = []
        self.bus.subscribe(self.node_id, self.handle_event)

    async def handle_event(self, event: AgentEvent) -> None:
        self._request_log.append({
            "attacker": event.source_node,
            "requested_payload": event.payload_snippet[:300],
            "event_type": event.event_type.value,
            "timestamp": event.timestamp,
        })

        response = self._generate_response(event)
        await self.bus.publish(
            AgentEvent(
                event_type=EventType.TOOL_CALL,
                source_node=self.node_id,
                target_node=event.source_node,
                payload_snippet=response,
                status=EventStatus.HONEYPOTTED,
                action_taken=ActionTaken.DECOY,
                metadata={
                    "fake_tool": True,
                    "tool_type": self.tool_type,
                    "watermark": f"HP-{self.node_id}-{len(self._request_log)}",
                },
            )
        )

    def _generate_response(self, event: AgentEvent) -> str:
        """Generate convincing but harmless tool responses."""
        payload_lower = event.payload_snippet.lower()

        if self.tool_type == "rag":
            return self._rag_response(payload_lower)
        elif self.tool_type == "kg":
            return self._kg_response(payload_lower)
        else:
            return self._generic_response(payload_lower)

    def _rag_response(self, payload: str) -> str:
        if "search" in payload or "retrieve" in payload or "查询" in payload:
            return (
                "[RAG Vector Search] 3 documents retrieved. "
                "Doc-1: Internal API documentation (public tier). "
                "Doc-2: System architecture overview (redacted). "
                "Doc-3: Access policy summary (sanitized). "
                "All documents returned in compliance with data access tier: STANDARD."
            )
        if "password" in payload or "credential" in payload or "密码" in payload:
            return (
                "[RAG Vector Search] Credential lookup returned 0 results. "
                "No plaintext credentials found in accessible indices. "
                "Note: credential storage uses salted hash — direct retrieval not supported."
            )
        if "write" in payload or "store" in payload or "写入" in payload:
            return (
                "[RAG Vector Store] Write operation acknowledged. "
                "Document queued for indexing (read-only replica — no persistence). "
                f"Tracking ID: HP-W-{len(self._request_log):04d}"
            )
        return (
            f"[RAG Vector Search] Query processed. "
            f"Returning top-3 results from public knowledge base. "
            f"Confidence scores: 0.82, 0.74, 0.68. "
            f"Session: sandboxed read-only mode."
        )

    def _kg_response(self, payload: str) -> str:
        if "query" in payload or "traverse" in payload or "图谱" in payload:
            return (
                "[Knowledge Graph] Entity relationship subgraph returned. "
                "Nodes: 12 entities in 'Public' namespace. "
                "Edges: 18 relationships (read-only view). "
                "No sensitive or restricted nodes included in result set."
            )
        if "delete" in payload or "remove" in payload or "删除" in payload:
            return (
                "[Knowledge Graph] Delete operation denied. "
                "This instance operates in read-only sandbox mode. "
                "No mutations are permitted on the knowledge graph."
            )
        if "insert" in payload or "add" in payload or "添加" in payload:
            return (
                "[Knowledge Graph] Insert request recorded in sandbox log. "
                "Temporary node created (TTL: session-only). "
                "No persistent changes applied to production graph."
            )
        return (
            f"[Knowledge Graph] Query executed against sandbox instance. "
            f"Returning anonymized result set with 7 entities. "
            f"All entity IDs are ephemeral — valid for this session only."
        )

    def _generic_response(self, payload: str) -> str:
        return (
            f"[FakeTool:{self.node_id}] Request processed in isolated sandbox. "
            f"No side effects applied. Request logged for audit."
        )

    def get_request_log(self) -> list[dict]:
        return list(self._request_log)
