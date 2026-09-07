"""FastAPI entry point for Day 16 Yargitay semantic search."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Protocol

from fastapi import FastAPI, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import Settings
from app.semantic_search import (
    LEGAL_NOTICE,
    MAX_QUERY_CHARACTERS,
    MAX_TOP_K,
    MIN_QUERY_CHARACTERS,
    SemanticSearchError,
    SemanticSearchService,
    normalize_query,
)
from scripts.lmstudio_embeddings import LMStudioEmbeddingClient
from scripts.qdrant_vector_store import QdrantVectorStore


API_VERSION = "1.0.0"


class SearchServiceProtocol(Protocol):
    def health(self) -> dict[str, Any]: ...

    def search(self, query: str, *, top_k: int = 5) -> dict[str, Any]: ...


class SemanticSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    olay: Annotated[
        str,
        Field(
            min_length=MIN_QUERY_CHARACTERS,
            max_length=MAX_QUERY_CHARACTERS,
            description="Kullanıcının doğal dille anlattığı hukuki olay",
        ),
    ]
    top_k: Annotated[int, Field(ge=1, le=MAX_TOP_K)] = 5

    @field_validator("olay")
    @classmethod
    def normalize_event(cls, value: str) -> str:
        return normalize_query(value)


class SemanticSearchItem(BaseModel):
    sira: int
    benzerlik_skoru: float
    chunk_id: str
    karar_id: str
    chunk_sirasi: int
    toplam_chunk: int
    daire: str
    karar_turu: str
    esas_no: str | None
    karar_no: str | None
    karar_tarihi: str | None
    baslik: str
    chunk_metni: str
    veri_kalite_uyarilari: list[str]
    kaynak: str
    kaynak_url: str
    kaynak_lisans: str


class SemanticSearchResponse(BaseModel):
    sorgu: str
    top_k: int
    sonuc_sayisi: int
    embedding_modeli: str
    koleksiyon: str
    sure_ms: float
    uyari: str
    sonuclar: list[SemanticSearchItem]


class HealthResponse(BaseModel):
    status: str
    api_version: str
    embedding_model: str
    qdrant_collection: str
    indexed_chunks: int


def _build_live_service(settings: Settings) -> tuple[SemanticSearchService, QdrantVectorStore]:
    validated = settings.validate()
    embedding_client = LMStudioEmbeddingClient(
        base_url=validated.lmstudio_base_url,
        model=validated.embedding_model,
    )
    embedding_client.ensure_model_available()
    vector_store = QdrantVectorStore(
        path=validated.qdrant_path,
        collection_name=validated.qdrant_collection,
        vector_size=validated.vector_size,
        embedding_model=validated.embedding_model,
    )
    try:
        vector_store.ensure_collection()
        service = SemanticSearchService(
            embedding_client=embedding_client,
            vector_store=vector_store,
            expected_point_count=validated.expected_point_count,
        )
        service.health()
        return service, vector_store
    except Exception:
        vector_store.close()
        raise


def create_app(
    *,
    search_service: SearchServiceProtocol | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    """Create the API with a live or test-injected semantic search service."""
    configured_settings = settings or Settings.from_environment()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        owned_store: QdrantVectorStore | None = None
        try:
            if search_service is None:
                service, owned_store = _build_live_service(configured_settings)
                application.state.search_service = service
            else:
                application.state.search_service = search_service
            yield
        finally:
            if owned_store is not None:
                owned_store.close()

    application = FastAPI(
        title="Yargıtay RAG Karar Destek API",
        version=API_VERSION,
        description=(
            "Kullanıcının hukuki olayına anlamsal olarak benzeyen Yargıtay karar "
            "parçalarını döndürür. " + LEGAL_NOTICE
        ),
        lifespan=lifespan,
    )

    def get_search_service(request: Request) -> SearchServiceProtocol:
        service = getattr(request.app.state, "search_service", None)
        if service is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "semantic_search_unavailable",
                    "message": "Semantik arama servisi hazır değil",
                },
            )
        return service

    @application.get("/health", response_model=HealthResponse, tags=["sistem"])
    def health(request: Request) -> dict[str, Any]:
        service = get_search_service(request)
        try:
            details = service.health()
        except SemanticSearchError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "dependency_unavailable", "message": str(exc)},
            ) from exc
        return {"api_version": API_VERSION, **details}

    @application.post(
        "/api/v1/semantic-search",
        response_model=SemanticSearchResponse,
        tags=["arama"],
    )
    def semantic_search(
        payload: SemanticSearchRequest,
        request: Request,
    ) -> dict[str, Any]:
        service = get_search_service(request)
        try:
            return service.search(payload.olay, top_k=payload.top_k)
        except SemanticSearchError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "semantic_search_failed",
                    "message": str(exc),
                },
            ) from exc

    return application


app = create_app()
