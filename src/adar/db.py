import logging
from typing import Optional

from google import genai
from google.genai import types as genai_types
from google.cloud import firestore
from google.cloud.firestore_v1.vector import Vector
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure

from src.adar.config import settings

logger = logging.getLogger(__name__)

_db: Optional[firestore.AsyncClient] = None
_genai_client: Optional[genai.Client] = None

EMBEDDING_MODEL = "models/gemini-embedding-001"
EMBEDDING_DIM   = 768


def get_db() -> firestore.AsyncClient:
    global _db
    if _db is None:
        _db = firestore.AsyncClient(
            project=settings.GCP_PROJECT_ID,
            database=settings.FIRESTORE_DATABASE,
        )
    return _db


def get_genai_client() -> genai.Client:
    global _genai_client
    if _genai_client is None:
        _genai_client = genai.Client(api_key=settings.GOOGLE_API_KEY)
    return _genai_client


async def embed_text(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> list[float]:
    client = get_genai_client()
    response = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
        config=genai_types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=EMBEDDING_DIM,
        ),
    )
    return response.embeddings[0].values


async def vector_search(
    collection: str,
    query: str,
    top_k: int = 10,
    filters: Optional[dict] = None,
) -> list[dict]:
    """
    Semantic vector search with Python post-filtering.
    Firestore find_nearest cannot use where() — filters applied after fetch.
    """
    try:
        query_vector = await embed_text(query, task_type="RETRIEVAL_QUERY")
        db = get_db()
        fetch_k = min(top_k * 6 if filters else top_k, 50)

        vector_query = db.collection(collection).find_nearest(
            vector_field="embedding",
            query_vector=Vector(query_vector),
            distance_measure=DistanceMeasure.COSINE,
            limit=fetch_k,
        )

        results = []
        async for doc in vector_query.stream():
            data = doc.to_dict()
            data["doc_id"] = doc.id
            data.pop("embedding", None)

            if filters:
                if not all(
                    str(data.get(f, "")).lower() == str(v).lower()
                    for f, v in filters.items()
                ):
                    continue

            results.append(data)
            if len(results) >= top_k:
                break

        return results

    except Exception as e:
        logger.error(f"Vector search error in {collection}: {e}")
        return []


async def _scan_collection(collection: str, filters: dict, limit: int = 50) -> list[dict]:
    """
    Full collection scan with Python-side filtering.
    Slow but works without composite indexes. Use only as fallback.
    """
    try:
        db = get_db()
        results = []
        async for doc in db.collection(collection).limit(500).stream():
            data = doc.to_dict()
            data["doc_id"] = doc.id
            data.pop("embedding", None)
            if all(
                str(data.get(f, "")).lower() == str(v).lower()
                for f, v in filters.items()
            ):
                results.append(data)
                if len(results) >= limit:
                    break
        return results
    except Exception as e:
        logger.error(f"Collection scan error in {collection}: {e}")
        return []


async def direct_query(
    collection: str,
    filters: dict,
    limit: int = 50,
    order_by: Optional[str] = None,
) -> list[dict]:
    """
    Direct Firestore where() query.
    Falls back to collection scan + Python filter if index not ready (503).
    """
    try:
        db = get_db()
        query = db.collection(collection)
        for field, value in filters.items():
            query = query.where(field, "==", value)
        if order_by:
            query = query.order_by(order_by)
        query = query.limit(limit)

        results = []
        async for doc in query.stream():
            data = doc.to_dict()
            data["doc_id"] = doc.id
            data.pop("embedding", None)
            results.append(data)
        return results

    except Exception as e:
        if "503" in str(e) or "timed out" in str(e).lower() or "index" in str(e).lower():
            logger.warning(
                f"Index not ready for {collection} — using collection scan fallback. "
                f"Run create_indexes.sh to fix permanently."
            )
            return await _scan_collection(collection, filters, limit)
        logger.error(f"direct_query error in {collection}: {e}")
        return []


async def get_documents_by_field(
    collection: str,
    field: str,
    value: str,
    limit: int = 50,
    extra_filters: Optional[dict] = None,
) -> list[dict]:
    filters = {field: value}
    if extra_filters:
        filters.update(extra_filters)
    return await direct_query(collection, filters, limit=limit)




async def add_document(collection: str, data: dict) -> str:
    try:
        db = get_db()
        _, doc_ref = await db.collection(collection).add({
            **data,
            "created_at": firestore.SERVER_TIMESTAMP,
        })
        return doc_ref.id
    except Exception as e:
        logger.error(f"Add document error in {collection}: {e}")
        raise