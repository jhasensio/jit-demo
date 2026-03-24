"""SQLAlchemy SQLite database setup."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = "sqlite:///./zero_trust.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    """Create all tables on startup and seed defaults."""
    # Import models so their metadata is registered before create_all
    import domain.policy.models      # noqa: F401
    import domain.target_app.models  # noqa: F401
    Base.metadata.create_all(bind=engine)

    # Seed default target applications if the table is empty
    from domain.target_app.models import TargetApp
    db = SessionLocal()
    try:
        if db.query(TargetApp).count() == 0:
            defaults = [
                TargetApp(name="HR_APP_01",  ip_address="10.114.209.72", description="Human Resources Application"),
                TargetApp(name="FIN_APP_01", ip_address="10.114.209.73", description="Finance Application"),
                TargetApp(name="ENG_APP_01", ip_address="10.114.209.74", description="Engineering Application"),
            ]
            db.add_all(defaults)
            db.commit()
    finally:
        db.close()


def get_db():
    """FastAPI dependency — yields a DB session and ensures it is closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
