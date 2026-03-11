"""
ARIA Cosmos DB client — async wrapper around azure-cosmos SDK.
All agents use this module; no agent imports azure-cosmos directly.
"""
import uuid
from datetime import datetime, timezone
from typing import Any

from azure.cosmos.aio import CosmosClient
from azure.cosmos.exceptions import CosmosResourceNotFoundError, CosmosHttpResponseError

from utils.config import COSMOS_ENDPOINT, COSMOS_KEY, COSMOS_DB


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AriaCosmosClient:
    """Thin async wrapper. Use as an async context manager or call connect()/close() explicitly."""

    def __init__(self):
        self._client: CosmosClient | None = None
        self._db = None

    async def connect(self) -> None:
        self._client = CosmosClient(COSMOS_ENDPOINT, credential=COSMOS_KEY)
        self._db = self._client.get_database_client(COSMOS_DB)

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *_):
        await self.close()

    def _container(self, name: str):
        return self._db.get_container_client(name)

    # ── Write ──────────────────────────────────────────────────────────────────

    async def upsert(self, container: str, doc: dict) -> dict:
        """Upsert a document. Adds id and created_at if not present."""
        if "id" not in doc:
            doc["id"] = str(uuid.uuid4())
        if "created_at" not in doc:
            doc["created_at"] = _now_iso()
        doc["updated_at"] = _now_iso()
        return await self._container(container).upsert_item(doc)

    async def delete(self, container: str, doc_id: str, partition_key: Any) -> None:
        """Delete a document by id. Silently ignores not-found."""
        try:
            await self._container(container).delete_item(item=doc_id, partition_key=partition_key)
        except CosmosResourceNotFoundError:
            pass

    # ── Read ───────────────────────────────────────────────────────────────────

    async def get(self, container: str, doc_id: str, partition_key: Any) -> dict | None:
        """Fetch a single document by id. Returns None if not found."""
        try:
            return await self._container(container).read_item(item=doc_id, partition_key=partition_key)
        except CosmosResourceNotFoundError:
            return None

    async def query(self, container: str, sql: str, params: list[dict] | None = None,
                    partition_key: Any = None) -> list[dict]:
        """Run a parameterised SQL query. Returns list of matching docs."""
        # azure-cosmos 4.x: cross-partition is the default; no enable_cross_partition_query
        kwargs: dict = {}
        if partition_key is not None:
            kwargs["partition_key"] = partition_key
        items = self._container(container).query_items(
            query=sql,
            parameters=params or [],
            **kwargs
        )
        return [item async for item in items]

    async def count(self, container: str, sql_where: str = "") -> int:
        """Return count of documents, optionally filtered by a WHERE clause."""
        where = f"WHERE {sql_where}" if sql_where else ""
        sql = f"SELECT VALUE COUNT(1) FROM c {where}"
        results = await self.query(container, sql)
        return results[0] if results else 0

    # ── Log helper ─────────────────────────────────────────────────────────────

    async def log(self, agent_name: str, action: str, detail: dict | None = None) -> None:
        """Write an agent log entry to agent_logs container."""
        from utils.config import CONTAINER_LOGS
        doc = {
            "agent_name": agent_name,
            "action": action,
            "detail": detail or {},
            "timestamp": _now_iso(),
        }
        await self.upsert(CONTAINER_LOGS, doc)
