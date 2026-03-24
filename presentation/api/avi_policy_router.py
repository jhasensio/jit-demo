"""
AVI Network Security Policy configuration API.

Provides endpoints to manage NetworkSecurityPolicy objects on the AVI controller
and persist policy-to-virtualservice-to-target_app mappings in SQLite.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from core.logger import event_bus
from domain.policy.models import PolicyMappingCreate, PolicyMappingResponse
from infrastructure.avi_client import AVIClient
from infrastructure.credential_store import credential_store
from infrastructure.database import get_db
from infrastructure.policy_store import PolicyStore

router = APIRouter(prefix="/avi-policy", tags=["AVI Policy"])


def _get_avi_client() -> AVIClient:
    creds = credential_store.get_avi()
    if creds is None:
        raise HTTPException(status_code=503, detail="AVI credentials not configured")
    return AVIClient(creds)


# ─── AVI read endpoints ───────────────────────────────────────────────────────

@router.get("/networksecuritypolicies")
async def list_networksecuritypolicies() -> dict:
    client = _get_avi_client()
    result = await client.list_networksecuritypolicies()
    if not result["success"]:
        raise HTTPException(status_code=502, detail=result.get("error", "AVI request failed"))
    return {"results": result["results"]}


@router.get("/virtualservices")
async def list_virtualservices() -> dict:
    client = _get_avi_client()
    result = await client.list_virtualservices()
    if not result["success"]:
        raise HTTPException(status_code=502, detail=result.get("error", "AVI request failed"))
    return {"results": result["results"]}


@router.get("/ipaddrgroups")
async def list_ipaddrgroups() -> dict:
    client = _get_avi_client()
    result = await client.list_ipaddrgroups()
    if not result["success"]:
        raise HTTPException(status_code=502, detail=result.get("error", "AVI request failed"))
    return {"results": result["results"]}


@router.post("/ipaddrgroups")
async def create_ipaddrgroup(body: dict) -> dict:
    name  = body.get("name", "").strip()
    addrs = body.get("addrs", [])
    if not name:
        raise HTTPException(status_code=422, detail="name is required")

    client = _get_avi_client()
    result = await client.create_ipaddrgroup(name, addrs)

    await event_bus.publish({
        "level": "SUCCESS" if result["success"] else "ERROR",
        "domain": "CONNECTIONS",
        "message": (
            f"AVI IPAddrGroup '{name}' created"
            if result["success"]
            else f"Failed to create IPAddrGroup '{name}': {result.get('error')}"
        ),
        "payload": result.get("body"),
    })

    if not result["success"]:
        raise HTTPException(status_code=502, detail=result.get("error", "AVI request failed"))
    return result


@router.get("/networksecuritypolicies/{uuid}")
async def get_networksecuritypolicy(uuid: str) -> dict:
    client = _get_avi_client()
    result = await client.get_networksecuritypolicy(uuid)
    if not result["success"]:
        raise HTTPException(status_code=502, detail=result.get("error", "AVI request failed"))
    return {"result": result["result"]}


@router.get("/networksecuritypolicies/{uuid}/references")
async def get_nsp_references(uuid: str) -> dict:
    client = _get_avi_client()
    result = await client.get_nsp_referred_by(uuid)
    if not result["success"]:
        raise HTTPException(status_code=502, detail=result.get("error", "AVI request failed"))
    return {"result": result["result"], "referred_by_vs": result["referred_by_vs"]}


# ─── AVI write endpoints ──────────────────────────────────────────────────────

@router.post("/create")
async def create_networksecuritypolicy(body: dict) -> dict:
    name             = body.get("name", "").strip()
    ipaddrgroup_ref  = body.get("ipaddrgroup_ref", "").strip()
    if not name or not ipaddrgroup_ref:
        raise HTTPException(status_code=422, detail="name and ipaddrgroup_ref are required")

    client = _get_avi_client()
    result = await client.create_networksecuritypolicy(name, ipaddrgroup_ref)

    await event_bus.publish({
        "level": "SUCCESS" if result["success"] else "ERROR",
        "domain": "CONNECTIONS",
        "message": (
            f"AVI NetworkSecurityPolicy '{name}' created"
            if result["success"]
            else f"Failed to create NSP '{name}': {result.get('error')}"
        ),
        "payload": result.get("body"),
    })

    if not result["success"]:
        raise HTTPException(status_code=502, detail=result.get("error", "AVI request failed"))
    return result


@router.post("/detach")
async def detach_policy_from_vs(body: dict) -> dict:
    vs_uuid = body.get("vs_uuid", "").strip()
    if not vs_uuid:
        raise HTTPException(status_code=422, detail="vs_uuid is required")

    client = _get_avi_client()
    result = await client.detach_policy_from_vs(vs_uuid)

    await event_bus.publish({
        "level": "SUCCESS" if result["success"] else "ERROR",
        "domain": "CONNECTIONS",
        "message": (
            f"Policy detached from VirtualService {vs_uuid}"
            if result["success"]
            else f"Failed to detach policy from VS {vs_uuid}: {result.get('error')}"
        ),
        "payload": None,
    })

    if not result["success"]:
        raise HTTPException(status_code=502, detail=result.get("error", "AVI request failed"))
    return result


@router.post("/attach")
async def attach_policy_to_vs(body: dict) -> dict:
    vs_uuid    = body.get("vs_uuid", "").strip()
    policy_ref = body.get("policy_ref", "").strip()
    if not vs_uuid or not policy_ref:
        raise HTTPException(status_code=422, detail="vs_uuid and policy_ref are required")

    client = _get_avi_client()
    result = await client.attach_policy_to_vs(vs_uuid, policy_ref)

    await event_bus.publish({
        "level": "SUCCESS" if result["success"] else "ERROR",
        "domain": "CONNECTIONS",
        "message": (
            f"Policy attached to VirtualService {vs_uuid}"
            if result["success"]
            else f"Failed to attach policy: {result.get('error')}"
        ),
        "payload": None,
    })

    if not result["success"]:
        raise HTTPException(status_code=502, detail=result.get("error", "AVI request failed"))
    return result


@router.put("/networksecuritypolicies/{uuid}")
async def update_networksecuritypolicy(uuid: str, body: dict) -> dict:
    client = _get_avi_client()
    result = await client.update_networksecuritypolicy(uuid, body)

    await event_bus.publish({
        "level": "SUCCESS" if result["success"] else "ERROR",
        "domain": "CONNECTIONS",
        "message": (
            f"AVI NetworkSecurityPolicy '{uuid}' updated"
            if result["success"]
            else f"Failed to update NSP '{uuid}': {result.get('error')}"
        ),
        "payload": None,
    })

    if not result["success"]:
        raise HTTPException(status_code=502, detail=result.get("error", "AVI request failed"))
    return result


@router.delete("/networksecuritypolicies/{uuid}")
async def delete_networksecuritypolicy(uuid: str) -> dict:
    client = _get_avi_client()
    result = await client.delete_networksecuritypolicy(uuid)

    await event_bus.publish({
        "level": "SUCCESS" if result["success"] else "ERROR",
        "domain": "CONNECTIONS",
        "message": (
            f"AVI NetworkSecurityPolicy '{uuid}' deleted"
            if result["success"]
            else f"Failed to delete NSP '{uuid}': {result.get('error')}"
        ),
        "payload": None,
    })

    if not result["success"]:
        raise HTTPException(status_code=502, detail=result.get("error", "AVI request failed"))
    return {"deleted": True, "uuid": uuid}


# ─── Mapping persistence (SQLite) ─────────────────────────────────────────────

@router.get("/mappings", response_model=list[PolicyMappingResponse])
async def list_mappings(db: Session = Depends(get_db)) -> list:
    return PolicyStore(db).list_all()


@router.post("/mappings", response_model=PolicyMappingResponse)
async def create_mapping(data: PolicyMappingCreate, db: Session = Depends(get_db)):
    return PolicyStore(db).create(data)


@router.delete("/mappings/{mapping_id}")
async def delete_mapping(mapping_id: int, db: Session = Depends(get_db)) -> dict:
    deleted = PolicyStore(db).delete(mapping_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Mapping {mapping_id} not found")
    return {"deleted": True, "id": mapping_id}
