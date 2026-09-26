import os
import shutil
import unicodedata

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

from app.database.database import engine, Base, get_db
from app.database import models
from app.routes.auth import router as auth_router
from app.security.dependencies import get_current_user

from app.services.gemini_service import extraire_donnees_pdf
from app.services.excel_service import generer_excel


load_dotenv()


app = FastAPI(title="Bank Statement Converter API")

app.include_router(auth_router)

Base.metadata.create_all(bind=engine)


# --------------------------------------------------
# CORS
# --------------------------------------------------

origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3002",
    "http://127.0.0.1:3002",
    "https://bankorama-frontend-app.vercel.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------
# TEMP DIRECTORY
# --------------------------------------------------

TEMP_DIR = "temp"

os.makedirs(TEMP_DIR, exist_ok=True)


# --------------------------------------------------
# UTILITAIRES
# --------------------------------------------------

def nettoyer_nom_fichier(filename: str) -> str:
    """
    Supprime les accents et caractères spéciaux
    du nom de fichier.
    """

    nfkd = unicodedata.normalize("NFKD", filename)

    ascii_str = nfkd.encode(
        "ASCII",
        "ignore"
    ).decode("utf-8")

    return ascii_str.replace(" ", "_")


def supprimer_fichier(chemin: str):
    """
    Supprime un fichier temporaire.
    """

    if os.path.exists(chemin):
        try:
            os.remove(chemin)

        except Exception as e:
            print(
                f"Erreur lors de la suppression "
                f"de {chemin}: {e}"
            )


def compter_pages_pdf(chemin: str) -> int:
    """
    Compte le nombre de pages du PDF.

    1 page = 1 crédit = 0,10 €
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


# --------------------------------------------------
# ROOT
# --------------------------------------------------

@app.get("/")
async def root():
    return RedirectResponse(url="/docs")


# --------------------------------------------------
# PARSE PDF
# --------------------------------------------------

@app.post("/api/v1/parse")
async def parse_pdf(
    file: UploadFile = File(...)
):
    """
    Analyse un PDF sans consommer de crédit.

    Cette route reste gratuite.
    """

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Le fichier doit être un PDF."
        )

    safe_filename = nettoyer_nom_fichier(
        file.filename
    )

    temp_pdf = os.path.join(
        TEMP_DIR,
        safe_filename
    )

    try:

        with open(temp_pdf, "wb") as buffer:
            shutil.copyfileobj(
                file.file,
                buffer
            )

        donnees = await extraire_donnees_pdf(
            temp_pdf
        )

        return {
            "status": "success",
            "data": donnees
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:

        if os.path.exists(temp_pdf):
            os.remove(temp_pdf)


# --------------------------------------------------
# CONVERT PDF -> EXCEL
# --------------------------------------------------

@app.post("/api/v1/convert-to-excel")
async def convert_pdf_to_excel(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = None,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Convertit un PDF en Excel.

    Tarification :

        1 page = 1 crédit
        1 crédit = 0,10 €

    Exemple :

        10 pages = 10 crédits = 1 €
        100 pages = 100 crédits = 10 €
        250 pages = 250 crédits = 25 €
    """

    # --------------------------------------------------
    # 1. Vérification extension
    # --------------------------------------------------

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Le fichier doit être un PDF."
        )

    # --------------------------------------------------
    # 2. Nom des fichiers temporaires
    # --------------------------------------------------

    safe_filename = nettoyer_nom_fichier(
        file.filename
    )

    temp_pdf = os.path.join(
        TEMP_DIR,
        safe_filename
    )

    excel_filename = (
        safe_filename.rsplit(".", 1)[0]
        + ".xlsx"
    )

    temp_excel = os.path.join(
        TEMP_DIR,
        excel_filename
    )

    credits_debites = 0

    try:

        # --------------------------------------------------
        # 3. Sauvegarde temporaire du PDF
        # --------------------------------------------------

        with open(temp_pdf, "wb") as buffer:
            shutil.copyfileobj(
                file.file,
                buffer
            )

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
                    "price_euros": round(
                        credits_required * 0.10,
                        2
                    )
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
        # 8. Nettoyage après téléchargement
        # --------------------------------------------------

        if background_tasks:

            background_tasks.add_task(
                supprimer_fichier,
                temp_pdf
            )

            background_tasks.add_task(
                supprimer_fichier,
                temp_excel
            )

        # --------------------------------------------------
        # 9. Retour du fichier
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
                "X-Pages-Processed": str(
                    page_count
                )
            }
        )

    except HTTPException:
        raise

    except Exception as e:

        # --------------------------------------------------
        # 10. Remboursement si erreur
        # --------------------------------------------------

        if credits_debites > 0:

            try:

                db.rollback()

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

                print(
                    f"Remboursement de "
                    f"{credits_debites} crédits "
                    f"pour user {current_user.id}"
                )

            except Exception as refund_error:

                db.rollback()

                print(
                    "ERREUR REMBOURSEMENT : "
                    f"{refund_error}"
                )

        # --------------------------------------------------
        # 11. Nettoyage fichiers
        # --------------------------------------------------

        if os.path.exists(temp_pdf):
            os.remove(temp_pdf)

        if os.path.exists(temp_excel):
            os.remove(temp_excel)

        # --------------------------------------------------
        # 12. Erreur API
        # --------------------------------------------------

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )