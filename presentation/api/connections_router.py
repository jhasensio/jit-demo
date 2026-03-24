from fastapi import APIRouter

from core.logger import event_bus
from domain.connections.models import AVICredentials, ConnectionStatus, NSXCredentials
from infrastructure.avi_client import AVIClient
from infrastructure.credential_store import credential_store
from infrastructure.nsx_client import NSXClient

router = APIRouter(prefix="/connections", tags=["Connections"])


@router.post("/nsx")
async def save_and_test_nsx(creds: NSXCredentials) -> dict:
    """Save NSX credentials in memory and run a live connectivity test.
    Credentials are kept regardless of test outcome."""
    credential_store.set_nsx(creds)
    credential_store.set_nsx_status("unconfigured")   # reset while testing

    await event_bus.publish({
        "level": "INFO",
        "domain": "CONNECTIONS",
        "message": f"Testing NSX connection → {creds.host} (user: {creds.username})",
        "payload": None,
    })

    result = await NSXClient(creds).test_connection()

    if result["success"]:
        credential_store.set_nsx_status("ok")
        await event_bus.publish({
            "level": "SUCCESS",
            "domain": "CONNECTIONS",
            "message": (
                f"NSX connected — {creds.host}  "
                f"version={result['version']}  node_type={result['node_type']}"
            ),
            "payload": {k: v for k, v in result.items() if k != "error"},
        })
    else:
        credential_store.set_nsx_status("error")
        await event_bus.publish({
            "level": "ERROR",
            "domain": "CONNECTIONS",
            "message": f"NSX connection failed: {result['error']}",
            "payload": None,
        })

    return {"host": creds.host, **result}


@router.post("/avi")
async def save_and_test_avi(creds: AVICredentials) -> dict:
    """Save AVI credentials in memory and run a live connectivity test."""
    credential_store.set_avi(creds)
    credential_store.set_avi_status("unconfigured")

    await event_bus.publish({
        "level": "INFO",
        "domain": "CONNECTIONS",
        "message": (
            f"Testing AVI connection → {creds.host} "
            f"(user: {creds.username}, configured version: {creds.avi_version})"
        ),
        "payload": None,
    })

    result = await AVIClient(creds).test_connection()

    if result["success"]:
        credential_store.set_avi_status("ok")
        await event_bus.publish({
            "level": "SUCCESS",
            "domain": "CONNECTIONS",
            "message": f"AVI connected — {creds.host}  version={result['version']}",
            "payload": {k: v for k, v in result.items() if k != "error"},
        })
    else:
        credential_store.set_avi_status("error")
        await event_bus.publish({
            "level": "ERROR",
            "domain": "CONNECTIONS",
            "message": f"AVI connection failed: {result['error']}",
            "payload": None,
        })

    return {"host": creds.host, "configured_version": creds.avi_version, **result}


@router.patch("/avi/version")
async def update_avi_version(body: dict) -> dict:
    """Update only the AVI API version on the stored credentials."""
    new_version = (body.get("version") or "").strip()
    if not new_version:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="version is required")
    creds = credential_store.get_avi()
    if creds is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="AVI not configured")
    updated = creds.model_copy(update={"avi_version": new_version})
    credential_store.set_avi(updated)
    return {"updated": True, "avi_version": new_version}


@router.delete("/nsx")
async def disconnect_nsx() -> dict:
    """Clear NSX credentials and reset status to unconfigured."""
    credential_store.clear_nsx()
    await event_bus.publish({
        "level": "INFO",
        "domain": "CONNECTIONS",
        "message": "NSX connector disconnected",
        "payload": None,
    })
    return {"disconnected": True}


@router.delete("/avi")
async def disconnect_avi() -> dict:
    """Clear AVI credentials and reset status to unconfigured."""
    credential_store.clear_avi()
    await event_bus.publish({
        "level": "INFO",
        "domain": "CONNECTIONS",
        "message": "AVI connector disconnected",
        "payload": None,
    })
    return {"disconnected": True}


@router.get("/status")
async def connection_status() -> ConnectionStatus:
    """Return the current credential status for NSX and AVI."""
    nsx = credential_store.get_nsx()
    avi = credential_store.get_avi()
    return ConnectionStatus(
        nsx=credential_store.get_nsx_status(),
        avi=credential_store.get_avi_status(),
        nsx_host=nsx.host if nsx else None,
        avi_host=avi.host if avi else None,
        avi_version=avi.avi_version if avi else None,
    )
