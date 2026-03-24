"""Repository for TargetApp CRUD operations."""
from sqlalchemy.orm import Session

from domain.target_app.models import TargetApp, TargetAppCreate, TargetAppUpdate


class TargetAppStore:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, data: TargetAppCreate) -> TargetApp:
        obj = TargetApp(**data.model_dump())
        self.db.add(obj)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def list_all(self) -> list[TargetApp]:
        return self.db.query(TargetApp).order_by(TargetApp.name).all()

    def get(self, app_id: int) -> TargetApp | None:
        return self.db.get(TargetApp, app_id)

    def get_by_name(self, name: str) -> TargetApp | None:
        return self.db.query(TargetApp).filter(TargetApp.name == name).first()

    def update(self, app_id: int, data: TargetAppUpdate) -> TargetApp | None:
        obj = self.db.get(TargetApp, app_id)
        if obj is None:
            return None
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(obj, field, value)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def delete(self, app_id: int) -> bool:
        obj = self.db.get(TargetApp, app_id)
        if obj is None:
            return False
        self.db.delete(obj)
        self.db.commit()
        return True
