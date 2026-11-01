import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

# Connexion propriétaire (superuser) : sert uniquement aux migrations au démarrage
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgrespassword@localhost:5432/gares_db"
)

if not DATABASE_URL:
    raise ValueError("La variable d'environnement DATABASE_URL n'est pas définie.")

# Rôle applicatif sans privilège : soumis au Row Level Security
APP_DB_USER = os.getenv("APP_DB_USER", "bankorama_app")
APP_DB_PASSWORD = os.getenv("APP_DB_PASSWORD")

if not APP_DB_PASSWORD:
    raise ValueError(
        "La variable d'environnement APP_DB_PASSWORD n'est pas définie "
        "(mot de passe du rôle PostgreSQL applicatif soumis au RLS)."
    )

APP_DATABASE_URL = os.getenv("APP_DATABASE_URL") or make_url(DATABASE_URL).set(
    username=APP_DB_USER,
    password=APP_DB_PASSWORD,
)

owner_engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=1,
    max_overflow=0,
    # Le mot de passe du rôle applicatif passe en paramètre : jamais dans les logs
    hide_parameters=True,
)

engine = create_engine(
    APP_DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    # Pas de hash de mot de passe ni de donnée client dans les logs d'erreur
    hide_parameters=True,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


# --------------------------------------------------
# CONTEXTE RLS
# --------------------------------------------------
# L'identifiant de l'utilisateur authentifié est stocké dans session.info
# et injecté dans chaque transaction via set_config(..., is_local=true) :
# il disparaît à la fin de la transaction, aucune fuite entre requêtes.

def _apply_rls_context(connection, user_id):
    connection.execute(
        text("SELECT set_config('app.user_id', :uid, true)"),
        {"uid": str(user_id) if user_id else ""},
    )


@event.listens_for(SessionLocal, "after_begin")
def _on_begin(session, transaction, connection):
    _apply_rls_context(connection, session.info.get("user_id"))


def set_rls_user(db, user_id: int):
    db.info["user_id"] = user_id

    if db.in_transaction():
        _apply_rls_context(db.connection(), user_id)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
