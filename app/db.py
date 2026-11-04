from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config import settings

args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
# hide_parameters: tanpa ini pesan galat SQLAlchemy memuat NILAI parameter ([parameters: ...]) = isi tulisan & email masuk ke log/Sentry saat ada error DB
engine = create_engine(settings.database_url, connect_args=args, hide_parameters=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as db:
        yield db
