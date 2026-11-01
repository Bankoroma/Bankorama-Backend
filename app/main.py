import logging
import os
import re
import unicodedata
import uuid

from fastapi import (
    FastAPI,
    UploadFile,
    File,
    HTTPException,
    BackgroundTasks,
    Depends
)

from fastapi.responses import FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import update
from sqlalchemy.orm import Session

from pypdf import PdfReader

from dotenv import load_dotenv

load_dotenv()

from app.database.database import get_db
from app.database import models
from app.database.migrations import run_migrations
from app.routes.auth import router as auth_router
from app.routes.admin import router as admin_router
from app.routes.conversions import router as conversions_router
from app.routes.plans import router as plans_router
from app.security.dependencies import require_active_subscription, require_admin

from app.services.gemini_service import extraire_donnees_pdf
from app.services.excel_service import generer_excel


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bankorama")

# Swagger désactivable en production (ENABLE_DOCS=false)
ENABLE_DOCS = os.getenv("ENABLE_DOCS", "true").lower() == "true"

app = FastAPI(
    title="Bank Statement Converter API",
    docs_url="/docs" if ENABLE_DOCS else None,
    redoc_url="/redoc" if ENABLE_DOCS else None,
    openapi_url="/openapi.json" if ENABLE_DOCS else None,
)

app.include_router(auth_router)
app.include_router(plans_router)
app.include_router(conversions_router)
app.include_router(admin_router)

run_migrations()


# --------------------------------------------------
# CORS
# --------------------------------------------------

DEFAULT_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3002",
    "http://127.0.0.1:3002",
    "https://bankorama-frontend-app.vercel.app",
]

origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", ",".join(DEFAULT_ORIGINS)).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    # Sans ça le navigateur ne peut pas lire le nom du fichier ni les crédits consommés
    expose_headers=[
        "Content-Disposition",
        "X-Credits-Consumed",
        "X-Credits-Remaining",
        "X-Pages-Processed",
    ],
)


# --------------------------------------------------
# TEMP DIRECTORY
# --------------------------------------------------

TEMP_DIR = "temp"

os.makedirs(TEMP_DIR, exist_ok=True)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


# --------------------------------------------------
# UTILITAIRES
# --------------------------------------------------

def nettoyer_nom_fichier(filename: str) -> str:
    """
    Nom affichable sûr : sans chemin, accents ni caractères spéciaux.
    Il ne sert qu'au nom du fichier téléchargé, jamais au chemin disque.
    """

    filename = filename.replace("\\", "/").rsplit("/", 1)[-1]

    nfkd = unicodedata.normalize("NFKD", filename)

    ascii_str = nfkd.encode(
        "ASCII",
        "ignore"
    ).decode("utf-8")

    ascii_str = re.sub(r"[^A-Za-z0-9._-]", "_", ascii_str).strip("._")

    return ascii_str[:120] or "releve.pdf"


def chemins_temporaires() -> tuple[str, str]:
    """
    Noms aléatoires : pas de path traversal via le nom envoyé
    et pas de collision entre deux utilisateurs simultanés.
    """

    base = os.path.join(TEMP_DIR, uuid.uuid4().hex)

    return base + ".pdf", base + ".xlsx"


def sauvegarder_upload(file: UploadFile, chemin: str):
    """
    Copie le fichier envoyé en refusant tout ce qui dépasse 10 Mo.
    """

    total = 0

    with open(chemin, "wb") as buffer:
        while chunk := file.file.read(1024 * 1024):
            total += len(chunk)

            if total > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail="Le fichier ne doit pas dépasser 10 Mo."
                )

            buffer.write(chunk)


def supprimer_fichier(chemin: str):
    """
    Supprime un fichier temporaire.
    """

    if os.path.exists(chemin):
        try:
            os.remove(chemin)

        except Exception as e:
            logger.warning(
                "Erreur lors de la suppression de %s: %s",
                chemin,
                e
            )


def compter_pages_pdf(chemin: str) -> int:
    """
    Compte le nombre de pages du PDF.

    1 page = 1 crédit
    """

    try:
        reader = PdfReader(chemin)

        # PDF protégé par mot de passe
        if reader.is_encrypted:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Les PDF protégés par mot de passe "
                    "ne sont pas supportés."
                )
            )

        page_count = len(reader.pages)

        if page_count <= 0:
            raise HTTPException(
                status_code=400,
                detail="Le PDF ne contient aucune page."
            )

        return page_count

    except HTTPException:
        raise

    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Impossible de lire le PDF."
        )


def verifier_extension_pdf(file: UploadFile):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Le fichier doit être un PDF."
        )


# --------------------------------------------------
# ROOT
# --------------------------------------------------

@app.get("/")
async def root():
    if ENABLE_DOCS:
        return RedirectResponse(url="/docs")

    return {"status": "ok"}


# --------------------------------------------------
# PARSE PDF
# --------------------------------------------------

@app.post("/api/v1/parse")
async def parse_pdf(
    file: UploadFile = File(...),
    admin=Depends(require_admin),
):
    """
    Analyse un PDF sans consommer de crédit.

    Réservée aux administrateurs : ouverte à tous, elle permettait
    d'appeler Gemini gratuitement et sans authentification.
    """

    verifier_extension_pdf(file)

    temp_pdf, _ = chemins_temporaires()

    try:

        sauvegarder_upload(file, temp_pdf)

        donnees = await extraire_donnees_pdf(
            temp_pdf
        )

        return {
            "status": "success",
            "data": donnees
        }

    except HTTPException:
        raise

    except Exception:
        logger.exception("Échec de l'analyse PDF")

        raise HTTPException(
            status_code=500,
            detail="L'analyse du relevé a échoué."
        )

    finally:

        supprimer_fichier(temp_pdf)


# --------------------------------------------------
# CONVERT PDF -> EXCEL
# --------------------------------------------------

@app.post("/api/v1/convert-to-excel")
async def convert_pdf_to_excel(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user=Depends(require_active_subscription),
    db: Session = Depends(get_db)
):
    """
    Convertit un PDF en Excel.

    Tarification : 1 page = 1 crédit.
    Les crédits sont rechargés chaque mois selon la formule.
    """

    # --------------------------------------------------
    # 1. Vérification extension
    # --------------------------------------------------

    verifier_extension_pdf(file)

    # --------------------------------------------------
    # 2. Nom des fichiers
    # --------------------------------------------------

    display_pdf = nettoyer_nom_fichier(file.filename)

    excel_filename = (
        display_pdf.rsplit(".", 1)[0]
        + ".xlsx"
    )

    temp_pdf, temp_excel = chemins_temporaires()

    credits_debites = 0
    page_count = 0

    try:

        # --------------------------------------------------
        # 3. Sauvegarde temporaire du PDF
        # --------------------------------------------------

        sauvegarder_upload(file, temp_pdf)

        # --------------------------------------------------
        # 4. Compter les pages
        # --------------------------------------------------

        page_count = compter_pages_pdf(
            temp_pdf
        )

        # 1 page = 1 crédit
        credits_required = page_count

        # --------------------------------------------------
        # 5. Vérification + débit atomique
        # --------------------------------------------------

        result = db.execute(
            update(models.User)
            .where(
                models.User.id == current_user.id,
                models.User.credits >= credits_required
            )
            .values(
                credits=(
                    models.User.credits
                    - credits_required
                )
            )
        )

        # Aucun utilisateur modifié
        # = crédits insuffisants
        if result.rowcount != 1:

            db.rollback()

            raise HTTPException(
                status_code=402,
                detail={
                    "message": "Crédits insuffisants.",
                    "credits_required": credits_required,
                    "credits_available": current_user.credits,
                }
            )

        db.commit()

        credits_debites = credits_required

        # --------------------------------------------------
        # 6. Extraction Gemini
        # --------------------------------------------------

        donnees = await extraire_donnees_pdf(
            temp_pdf
        )

        # --------------------------------------------------
        # 7. Génération Excel
        # --------------------------------------------------

        generer_excel(
            donnees,
            temp_excel
        )

        # --------------------------------------------------
        # 8. Historique
        # --------------------------------------------------

        db.add(
            models.Conversion(
                user_id=current_user.id,
                filename=display_pdf,
                pages=page_count,
                credits_used=credits_debites,
                status="success",
            )
        )
        db.commit()
        db.refresh(current_user)

        # --------------------------------------------------
        # 9. Nettoyage après téléchargement
        # --------------------------------------------------

        background_tasks.add_task(
            supprimer_fichier,
            temp_pdf
        )

        background_tasks.add_task(
            supprimer_fichier,
            temp_excel
        )

        # --------------------------------------------------
        # 10. Retour du fichier
        # --------------------------------------------------

        return FileResponse(
            path=temp_excel,
            filename=excel_filename,
            media_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            headers={
                "X-Credits-Consumed": str(
                    credits_debites
                ),
                "X-Credits-Remaining": str(
                    current_user.credits
                ),
                "X-Pages-Processed": str(
                    page_count
                )
            }
        )

    except HTTPException:
        supprimer_fichier(temp_pdf)
        supprimer_fichier(temp_excel)
        raise

    except Exception:

        logger.exception(
            "Échec de conversion pour user %s",
            current_user.id
        )

        # --------------------------------------------------
        # 11. Remboursement si erreur
        # --------------------------------------------------

        db.rollback()

        if credits_debites > 0:

            try:

                db.execute(
                    update(models.User)
                    .where(
                        models.User.id == current_user.id
                    )
                    .values(
                        credits=(
                            models.User.credits
                            + credits_debites
                        )
                    )
                )

                db.commit()

                logger.info(
                    "Remboursement de %s crédits pour user %s",
                    credits_debites,
                    current_user.id
                )

            except Exception:

                db.rollback()

                logger.exception("ERREUR REMBOURSEMENT")

        try:
            db.add(
                models.Conversion(
                    user_id=current_user.id,
                    filename=display_pdf,
                    pages=page_count,
                    credits_used=0,
                    status="failed",
                )
            )
            db.commit()

        except Exception:
            db.rollback()

        # --------------------------------------------------
        # 12. Nettoyage fichiers
        # --------------------------------------------------

        supprimer_fichier(temp_pdf)
        supprimer_fichier(temp_excel)

        # --------------------------------------------------
        # 13. Erreur API (détail interne journalisé, pas exposé)
        # --------------------------------------------------

        raise HTTPException(
            status_code=500,
            detail=(
                "La conversion a échoué. "
                "Vos crédits ont été remboursés."
            )
        )
