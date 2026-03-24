"""Target Application definitions — CRUD API."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from domain.target_app.models import TargetAppCreate, TargetAppResponse, TargetAppUpdate
from infrastructure.credential_store import credential_store
from infrastructure.database import get_db
from infrastructure.nsx_client import NSXClient
from infrastructure.policy_store import PolicyStore
from infrastructure.target_app_store import TargetAppStore

router = APIRouter(prefix="/target-apps", tags=["Target Applications"])


@router.get("", response_model=list[TargetAppResponse])
async def list_target_apps(db: Session = Depends(get_db)) -> list:
    return TargetAppStore(db).list_all()


@router.get("/onboarding-status")
async def get_onboarding_status(db: Session = Depends(get_db)) -> list:
    """Return AVI and vDefend onboarding status for every target app."""
    apps = TargetAppStore(db).list_all()
    policy_store = PolicyStore(db)

    # Query live NSX groups once (best-effort — empty if not connected)
    nsx_group_names: set[str] = set()
    nsx_creds = credential_store.get_nsx()
    if nsx_creds and credential_store.get_nsx_status() == "ok":
        result = await NSXClient(nsx_creds).list_groups()
        if result.get("success"):
            for g in result.get("results", []):
                name = g.get("display_name") or g.get("id", "")
                if name:
                    nsx_group_names.add(name)

    statuses = []
    for app in apps:
        prefix = app.name.split("_")[0]
        jit_group = f"{prefix}-JIT-active-users-ipaddr"
        avi_mapping = policy_store.get_by_target_app(app.name)
        statuses.append({
            "name": app.name,
            "avi_onboarded": avi_mapping is not None,
            "nsx_onboarded": jit_group in nsx_group_names,
        })
    return statuses


@router.post("", response_model=TargetAppResponse)
async def create_target_app(data: TargetAppCreate, db: Session = Depends(get_db)):
    store = TargetAppStore(db)
    if store.get_by_name(data.name):
        raise HTTPException(status_code=409, detail=f"Application '{data.name}' already exists")
    return store.create(data)


@router.put("/{app_id}", response_model=TargetAppResponse)
async def update_target_app(app_id: int, data: TargetAppUpdate, db: Session = Depends(get_db)):
    obj = TargetAppStore(db).update(app_id, data)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"Application {app_id} not found")
    return obj


@router.delete("/{app_id}")
async def delete_target_app(app_id: int, db: Session = Depends(get_db)) -> dict:
    deleted = TargetAppStore(db).delete(app_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Application {app_id} not found")
    return {"deleted": True, "id": app_id}
