"""
NSX (vDefend) Gateway Firewall Policy configuration API.

Provides endpoints to manage Security Groups and Gateway Firewall Policies
on NSX Manager via the Policy API.
"""
from fastapi import APIRouter, HTTPException

from core.logger import event_bus
from infrastructure.credential_store import credential_store
from infrastructure.nsx_client import NSXClient

router = APIRouter(prefix="/nsx-policy", tags=["NSX Policy"])


def _get_nsx_client() -> NSXClient:
    creds = credential_store.get_nsx()
    if creds is None:
        raise HTTPException(status_code=503, detail="NSX credentials not configured")
    return NSXClient(creds)


# ─── Read endpoints ───────────────────────────────────────────────────────────

@router.get("/groups")
async def list_groups() -> dict:
    client = _get_nsx_client()
    result = await client.list_groups()
    if not result["success"]:
        raise HTTPException(status_code=502, detail=result.get("error", "NSX request failed"))
    return {"results": result["results"]}


@router.get("/gateway-policies")
async def list_gateway_policies() -> dict:
    client = _get_nsx_client()
    result = await client.list_gateway_policies()
    if not result["success"]:
        raise HTTPException(status_code=502, detail=result.get("error", "NSX request failed"))
    return {"results": result["results"]}


@router.get("/gateway-policies/{policy_id}")
async def get_gateway_policy(policy_id: str) -> dict:
    client = _get_nsx_client()
    result = await client.get_gateway_policy(policy_id)
    if not result["success"]:
        raise HTTPException(status_code=502, detail=result.get("error", "NSX request failed"))
    return {"result": result["result"]}


@router.get("/tier0s")
async def list_tier0s() -> dict:
    client = _get_nsx_client()
    result = await client.list_tier0s()
    if not result["success"]:
        raise HTTPException(status_code=502, detail=result.get("error", "NSX request failed"))
    return {"results": result["results"]}


# ─── Write endpoints ──────────────────────────────────────────────────────────

@router.post("/groups")
async def create_group(body: dict) -> dict:
    group_id    = (body.get("group_id") or "").strip()
    display_name = (body.get("display_name") or group_id).strip()
    ip_addresses = body.get("ip_addresses") or []
    if not group_id:
        raise HTTPException(status_code=422, detail="group_id is required")

    client = _get_nsx_client()
    result = await client.create_group(group_id, display_name, ip_addresses)

    await event_bus.publish({
        "level": "SUCCESS" if result["success"] else "ERROR",
        "domain": "CONNECTIONS",
        "message": (
            f"vDefend Security Group '{display_name}' created"
            if result["success"]
            else f"Failed to create Security Group '{display_name}': {result.get('error')}"
        ),
        "payload": result.get("body"),
    })

    if not result["success"]:
        raise HTTPException(status_code=502, detail=result.get("error", "NSX request failed"))
    return result


@router.patch("/gateway-policies/{policy_id}")
async def create_or_update_gateway_policy(policy_id: str, body: dict) -> dict:
    client = _get_nsx_client()
    result = await client.create_or_update_gateway_policy(policy_id, body)

    display_name = body.get("display_name", policy_id)
    await event_bus.publish({
        "level": "SUCCESS" if result["success"] else "ERROR",
        "domain": "CONNECTIONS",
        "message": (
            f"vDefend Gateway Policy '{display_name}' saved"
            if result["success"]
            else f"Failed to save Gateway Policy '{display_name}': {result.get('error')}"
        ),
        "payload": result.get("body"),
    })

    if not result["success"]:
        raise HTTPException(status_code=502, detail=result.get("error", "NSX request failed"))
    return result


@router.delete("/gateway-policies/{policy_id}")
async def delete_gateway_policy(policy_id: str) -> dict:
    client = _get_nsx_client()
    result = await client.delete_gateway_policy(policy_id)

    await event_bus.publish({
        "level": "SUCCESS" if result["success"] else "ERROR",
        "domain": "CONNECTIONS",
        "message": (
            f"vDefend Gateway Policy '{policy_id}' deleted"
            if result["success"]
            else f"Failed to delete Gateway Policy '{policy_id}': {result.get('error')}"
        ),
        "payload": None,
    })

    if not result["success"]:
        raise HTTPException(status_code=502, detail=result.get("error", "NSX request failed"))
    return {"deleted": True, "policy_id": policy_id}
