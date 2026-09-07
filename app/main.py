"""FastAPI entry point for the local Yargitay RAG service."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal, Protocol

from fastapi import FastAPI, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import Settings
from app.rag_answer import (
    DEFAULT_RAG_MIN_SCORE,
    DEFAULT_RAG_TOP_K,
    PROMPT_VERSION,
    RAGAnswerError,
    RAGAnswerService,
)
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
from scripts.lmstudio_chat import LMStudioChatClient
from scripts.qdrant_vector_store import QdrantVectorStore


API_VERSION = "1.2.0"


class SearchServiceProtocol(Protocol):
    def health(self) -> dict[str, Any]: ...

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        min_score: float | None = None,
        metadata_filters: dict[str, str | bool] | None = None,
    ) -> dict[str, Any]: ...


class RAGAnswerServiceProtocol(Protocol):
    def health(self) -> dict[str, Any]: ...

    def answer(
        self,
        query: str,
        *,
        top_k: int = DEFAULT_RAG_TOP_K,
        min_score: float = DEFAULT_RAG_MIN_SCORE,
        metadata_filters: dict[str, str | bool] | None = None,
    ) -> dict[str, Any]: ...


class MetadataFiltersRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    karar_turu: Literal["hukuk", "ceza", "kurul"] | None = None
    daire: Annotated[str | None, Field(max_length=120)] = None
    veri_kalite_durumu: Literal["gecerli", "uyarili"] | None = None
    metin_2000_karakter_sinirinda: bool | None = None

    @field_validator("daire")
    @classmethod
    def normalize_chamber(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("daire filtresi boş olamaz")
        return normalized


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
    min_score: Annotated[float | None, Field(ge=-1, le=1)] = None
    filtreler: MetadataFiltersRequest | None = None

    @field_validator("olay")
    @classmethod
    def normalize_event(cls, value: str) -> str:
        return normalize_query(value)


class RAGAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    olay: Annotated[
        str,
        Field(
            min_length=MIN_QUERY_CHARACTERS,
            max_length=MAX_QUERY_CHARACTERS,
            description="Kaynaklara dayalı değerlendirilecek hukuki olay",
        ),
    ]
    top_k: Annotated[int, Field(ge=1, le=MAX_TOP_K)] = DEFAULT_RAG_TOP_K
    min_score: Annotated[float, Field(ge=-1, le=1)] = DEFAULT_RAG_MIN_SCORE
    filtreler: MetadataFiltersRequest | None = None

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
    aranan_aday_chunk_sayisi: int
    minimum_benzerlik_skoru: float | None
    filtreler: dict[str, str | bool]
    sonuc_sayisi: int
    yeterli_sonuc_bulundu: bool
    embedding_modeli: str
    koleksiyon: str
    sure_ms: float
    uyari: str
    sonuclar: list[SemanticSearchItem]


class RAGSourceItem(BaseModel):
    kaynak_etiketi: str
    sira: int
    benzerlik_skoru: float
    chunk_id: str
    karar_id: str
    daire: str
    esas_no: str | None
    karar_no: str | None
    karar_tarihi: str | None
    baslik: str
    chunk_metni: str
    veri_kalite_uyarilari: list[str]
    kaynak: str
    kaynak_url: str
    kaynak_lisans: str


class RAGAnswerResponse(BaseModel):
    sorgu: str
    durum: Literal["tamamlandi", "yetersiz_kaynak"]
    degerlendirme_uretildi: bool
    cevap: str
    bulunan_kaynak_sayisi: int
    kullanilan_kaynak_sayisi: int
    minimum_gerekli_kaynak: int
    minimum_benzerlik_skoru: float
    filtreler: dict[str, str | bool]
    chat_modeli: str
    prompt_surumu: str
    llm_cagrildi: bool
    model_istatistikleri: dict[str, int | float] | None
    model_response_id: str | None
    sure_ms: float
    uyari: str
    kaynaklar: list[RAGSourceItem]


class HealthResponse(BaseModel):
    status: str
    api_version: str
    embedding_model: str
    qdrant_collection: str
    indexed_chunks: int
    chat_model: str | None = None
    rag_prompt_version: str | None = None
    minimum_rag_sources: int | None = None


def _build_live_services(
    settings: Settings,
) -> tuple[SemanticSearchService, RAGAnswerService, QdrantVectorStore]:
    validated = settings.validate()
    embedding_client = LMStudioEmbeddingClient(
        base_url=validated.lmstudio_base_url,
        model=validated.embedding_model,
    )
    embedding_client.ensure_model_available()
    chat_client = LMStudioChatClient(
        base_url=validated.lmstudio_base_url,
        model=validated.chat_model,
    )
    chat_client.ensure_model_available()
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
        rag_service = RAGAnswerService(
            semantic_search=service,
            chat_client=chat_client,
        )
        return service, rag_service, vector_store
    except Exception:
        vector_store.close()
        raise


def create_app(
    *,
    search_service: SearchServiceProtocol | None = None,
    rag_service: RAGAnswerServiceProtocol | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    """Create the API with a live or test-injected semantic search service."""
    configured_settings = settings or Settings.from_environment()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        owned_store: QdrantVectorStore | None = None
        try:
            if search_service is None:
                service, live_rag_service, owned_store = _build_live_services(
                    configured_settings
                )
                application.state.search_service = service
                application.state.rag_service = live_rag_service
            else:
                application.state.search_service = search_service
                if rag_service is not None:
                    application.state.rag_service = rag_service
            yield
        finally:
            if owned_store is not None:
                owned_store.close()

    application = FastAPI(
        title="Yargıtay RAG Karar Destek API",
        version=API_VERSION,
        description=(
            "Kullanıcının hukuki olayına anlamsal olarak benzeyen Yargıtay karar "
            "parçalarını bulur ve isteğe bağlı olarak Gemma ile kaynaklı bir "
            "değerlendirme üretir. " + LEGAL_NOTICE
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

    def get_rag_service(request: Request) -> RAGAnswerServiceProtocol:
        service = getattr(request.app.state, "rag_service", None)
        if service is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "rag_answer_unavailable",
                    "message": "RAG cevap servisi hazır değil",
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
        rag_details: dict[str, Any] = {
            "chat_model": None,
            "rag_prompt_version": None,
            "minimum_rag_sources": None,
        }
        available_rag_service = getattr(request.app.state, "rag_service", None)
        if available_rag_service is not None:
            rag_details = available_rag_service.health()
        return {"api_version": API_VERSION, **details, **rag_details}

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
            metadata_filters = (
                payload.filtreler.model_dump(exclude_none=True)
                if payload.filtreler is not None
                else None
            )
            return service.search(
                payload.olay,
                top_k=payload.top_k,
                min_score=payload.min_score,
                metadata_filters=metadata_filters,
            )
        except SemanticSearchError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "semantic_search_failed",
                    "message": str(exc),
                },
            ) from exc

    @application.post(
        "/api/v1/rag-answer",
        response_model=RAGAnswerResponse,
        tags=["rag"],
    )
    def rag_answer(
        payload: RAGAnswerRequest,
        request: Request,
    ) -> dict[str, Any]:
        service = get_rag_service(request)
        metadata_filters = (
            payload.filtreler.model_dump(exclude_none=True)
            if payload.filtreler is not None
            else None
        )
        try:
            return service.answer(
                payload.olay,
                top_k=payload.top_k,
                min_score=payload.min_score,
                metadata_filters=metadata_filters,
            )
        except RAGAnswerError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "rag_answer_failed", "message": str(exc)},
            ) from exc

    return application


app = create_app()
