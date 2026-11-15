"""External-agent SDK; credentials are supplied by the caller."""

from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from app.memory.contracts import MemoryInput, SearchRequest


class MemoryRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    title: str
    content: str
    status: str
    version: int
    data: MemoryInput


class SearchResult(BaseModel):
    memory: MemoryRecord
    score: float
    explanation: dict[str, Any]


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    results: list[SearchResult]
    context: str
    warnings: list[str]


class MemoriaClientError(Exception):
    def __init__(self, status_code: Any, message: Any) -> None:
        super().__init__(message)
        self.status_code = status_code


def checked(response: Any) -> Any:
    if response.is_error:
        try:
            message = response.json().get("message", "Memoria API request failed")
        except ValueError:
            message = "Memoria API request failed"
        raise MemoriaClientError(response.status_code, message)
    return response.json()


def remember_body(content: Any, memory_type: Any, attributes: Any) -> Any:
    attributes.setdefault("title", content[:300])
    attributes.setdefault("sources", [{"source_id": "external-client", "quote": content}])
    return MemoryInput(content=content, memory_type=memory_type, **attributes).model_dump(
        mode="json"
    )


class MemoriaClient:
    def __init__(
        self,
        base_url: Any = "http://localhost:8000",
        api_key: Any = "",
        timeout: Any = 120,
        transport: Any = None,
    ) -> None:
        self.http = httpx.Client(
            base_url=base_url.rstrip("/") + "/api/v1/",
            headers={"Authorization": "Bearer " + api_key},
            timeout=timeout,
            transport=transport,
        )

    def remember(
        self, content: str, memory_type: Any = "semantic", **attributes: Any
    ) -> MemoryRecord:
        body = remember_body(content, memory_type, attributes)
        return MemoryRecord.model_validate(checked(self.http.post("memory", json=body)))

    def search(self, query: str, **options: Any) -> SearchResponse:
        body = SearchRequest(query=query, **options).model_dump(mode="json")
        return SearchResponse.model_validate(checked(self.http.post("search", json=body)))

    def get_context(self, query: str, **options: Any) -> str:
        return self.search(query, **options).context

    def get(self, memory_id: str) -> MemoryRecord:
        return MemoryRecord.model_validate(checked(self.http.get("memory/" + memory_id)))

    def ingest(self, content: str, background: Any = True, idempotency_key: Any = None) -> Any:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        return checked(
            self.http.post(
                "ingestion", json={"content": content, "background": background}, headers=headers
            )
        )

    def ingest_document(self, path: str | Path) -> Any:
        path = Path(path)
        with path.open("rb") as file:
            return checked(self.http.post("ingestion/document", files={"file": (path.name, file)}))

    def job(self, job_id: Any) -> Any:
        return checked(self.http.get("ingestion/" + job_id))

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> Any:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


class AsyncMemoriaClient:
    def __init__(
        self,
        base_url: Any = "http://localhost:8000",
        api_key: Any = "",
        timeout: Any = 120,
        transport: Any = None,
    ) -> None:
        self.http = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/api/v1/",
            headers={"Authorization": "Bearer " + api_key},
            timeout=timeout,
            transport=transport,
        )

    async def remember(
        self, content: str, memory_type: Any = "semantic", **attributes: Any
    ) -> MemoryRecord:
        response = await self.http.post(
            "memory", json=remember_body(content, memory_type, attributes)
        )
        return MemoryRecord.model_validate(checked(response))

    async def search(self, query: str, **options: Any) -> SearchResponse:
        response = await self.http.post(
            "search", json=SearchRequest(query=query, **options).model_dump(mode="json")
        )
        return SearchResponse.model_validate(checked(response))

    async def get_context(self, query: str, **options: Any) -> str:
        return (await self.search(query, **options)).context

    async def get(self, memory_id: str) -> MemoryRecord:
        return MemoryRecord.model_validate(checked(await self.http.get("memory/" + memory_id)))

    async def ingest(
        self, content: str, background: Any = True, idempotency_key: Any = None
    ) -> Any:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        return checked(
            await self.http.post(
                "ingestion", json={"content": content, "background": background}, headers=headers
            )
        )

    async def job(self, job_id: Any) -> Any:
        return checked(await self.http.get("ingestion/" + job_id))

    async def close(self) -> None:
        await self.http.aclose()

    async def __aenter__(self) -> Any:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
