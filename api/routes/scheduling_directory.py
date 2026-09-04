"""
api/routes/scheduling_directory.py — Read-only practice/provider directory
for logged-in scheduling customers (any authenticated caller, not just
admins — see auth.get_current_team). Backs the chat app's "Providers" tab
so a caller can see what they could ask the assistant about, without a
chat round trip: which practices exist, which providers each one has,
each provider's working hours, and which appointment types each offers.

Deliberately separate from api/routes/scheduling_admin.py, which is
admin-only CRUD (create/edit/hide practices, providers, appointment
types) — this file only ever reads, and only ever returns active
records, since a caller shouldn't see a hidden practice or a provider
someone deactivated. Mirrors what find_practice/list_providers
(domains/scheduling/tools/availability_tools.py) would tell a caller in
conversation, just rendered as a page instead of chat.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from google.cloud import firestore

from src.adar.config import settings
from api.routes.auth import get_current_team

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scheduling", tags=["scheduling-directory"])


def _require_scheduling_domain():
    if settings.DOMAIN != "scheduling":
        raise HTTPException(status_code=404, detail="Not available for this domain")


def get_db() -> firestore.AsyncClient:
    return firestore.AsyncClient(
        project=settings.GCP_PROJECT_ID,
        database=settings.FIRESTORE_DATABASE,
    )


def _doc_to_dict(doc) -> dict:
    d = doc.to_dict() or {}
    d["id"] = doc.id
    return d


@router.get("/directory")
async def directory(_: dict = Depends(get_current_team)):
    _require_scheduling_domain()
    db = get_db()

    practices = []
    async for doc in db.collection(settings.SCHEDULING_PRACTICES_COLLECTION).stream():
        p = _doc_to_dict(doc)
        if p.get("active") is False:
            continue
        practices.append(p)
    practices.sort(key=lambda p: p.get("name", ""))

    out = []
    for practice in practices:
        practice_id = practice["id"]

        types_by_id = {}
        async for doc in db.collection(settings.SCHEDULING_APPOINTMENT_TYPES_COLLECTION) \
                .where("practice_id", "==", practice_id).stream():
            t = _doc_to_dict(doc)
            types_by_id[t["id"]] = t

        providers = []
        async for doc in db.collection(settings.SCHEDULING_PROVIDERS_COLLECTION) \
                .where("practice_id", "==", practice_id).stream():
            prov = _doc_to_dict(doc)
            if prov.get("active") is False:
                continue
            prov["appointment_types"] = [
                {
                    "id": tid,
                    "name": types_by_id[tid]["name"],
                    "duration_minutes": types_by_id[tid].get("duration_minutes"),
                }
                for tid in prov.get("appointment_type_ids", [])
                if tid in types_by_id
            ]
            prov.pop("appointment_type_ids", None)
            prov.pop("active", None)
            providers.append(prov)
        providers.sort(key=lambda p: p.get("name", ""))

        out.append({
            "id": practice_id,
            "name": practice.get("name", ""),
            "timezone": practice.get("timezone", ""),
            "providers": providers,
            "appointment_types": [
                {
                    "id": t["id"],
                    "name": t["name"],
                    "duration_minutes": t.get("duration_minutes"),
                    "description": t.get("description", ""),
                }
                for t in sorted(types_by_id.values(), key=lambda t: t.get("name", ""))
            ],
        })

    return {"practices": out}
