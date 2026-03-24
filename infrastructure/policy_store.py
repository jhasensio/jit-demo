"""Repository for PolicyMapping CRUD operations."""
from sqlalchemy.orm import Session

from domain.policy.models import PolicyMapping, PolicyMappingCreate


class PolicyStore:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, data: PolicyMappingCreate) -> PolicyMapping:
        obj = PolicyMapping(**data.model_dump())
        self.db.add(obj)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def list_all(self) -> list[PolicyMapping]:
        return (
            self.db.query(PolicyMapping)
            .order_by(PolicyMapping.created_at.desc())
            .all()
        )

    def get_by_target_app(self, target_app: str) -> PolicyMapping | None:
        return (
            self.db.query(PolicyMapping)
            .filter(PolicyMapping.target_app == target_app)
            .first()
        )

    def delete(self, mapping_id: int) -> bool:
        obj = self.db.get(PolicyMapping, mapping_id)
        if obj is None:
            return False
        self.db.delete(obj)
        self.db.commit()
        return True
