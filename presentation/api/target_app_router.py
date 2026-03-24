"""Target Application definitions — CRUD API."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from domain.target_app.models import TargetAppCreate, TargetAppResponse, TargetAppUpdate
from infrastructure.database import get_db
from infrastructure.target_app_store import TargetAppStore

router = APIRouter(prefix="/target-apps", tags=["Target Applications"])


@router.get("", response_model=list[TargetAppResponse])
async def list_target_apps(db: Session = Depends(get_db)) -> list:
    return TargetAppStore(db).list_all()


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
