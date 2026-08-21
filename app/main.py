import os
import shutil
import unicodedata
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware  # <--- Import ajouté
from dotenv import load_dotenv

from app.services.gemini_service import extraire_donnees_pdf
from app.services.excel_service import generer_excel

load_dotenv()

app = FastAPI(title="Bank Statement Converter API")

# <--- Configuration CORS obligatoire pour le dev local --->
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TEMP_DIR = "temp"
os.makedirs(TEMP_DIR, exist_ok=True)


def nettoyer_nom_fichier(filename: str) -> str:
    """ Supprime les accents et caractères spéciaux du nom de fichier """
    nfkd = unicodedata.normalize('NFKD', filename)
    ascii_str = nfkd.encode('ASCII', 'ignore').decode('utf-8')
    return ascii_str.replace(" ", "_")


def supprimer_fichier(chemin: str):
    """ Tâche en arrière-plan pour nettoyer les fichiers temporaires après envoi """
    if os.path.exists(chemin):
        try:
            os.remove(chemin)
        except Exception as e:
            print(f"Erreur lors de la suppression de {chemin}: {e}")


@app.get("/")
async def root():
    return RedirectResponse(url="/docs")


@app.post("/api/v1/parse")
async def parse_pdf(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Le fichier doit être un PDF.")

    safe_filename = nettoyer_nom_fichier(file.filename)
    temp_pdf = os.path.join(TEMP_DIR, safe_filename)

    try:
        with open(temp_pdf, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        donnees = await extraire_donnees_pdf(temp_pdf)
        return {"status": "success", "data": donnees}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        if os.path.exists(temp_pdf):
            os.remove(temp_pdf)


@app.post("/api/v1/convert-to-excel")
async def convert_pdf_to_excel(file: UploadFile = File(...), background_tasks: BackgroundTasks = BackgroundTasks()):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Le fichier doit être un PDF.")

    safe_filename = nettoyer_nom_fichier(file.filename)
    temp_pdf = os.path.join(TEMP_DIR, safe_filename)
    
    excel_filename = safe_filename.rsplit('.', 1)[0] + ".xlsx"
    temp_excel = os.path.join(TEMP_DIR, excel_filename)

    try:
        with open(temp_pdf, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        donnees = await extraire_donnees_pdf(temp_pdf)
        generer_excel(donnees, temp_excel)

        # Programmer la suppression des fichiers temporaires APRES l'envoi du fichier
        background_tasks.add_task(supprimer_fichier, temp_pdf)
        background_tasks.add_task(supprimer_fichier, temp_excel)

        return FileResponse(
            path=temp_excel,
            filename=excel_filename,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except Exception as e:
        # Nettoyage en cas d'erreur avant l'envoi
        if os.path.exists(temp_pdf):
            os.remove(temp_pdf)
        if os.path.exists(temp_excel):
            os.remove(temp_excel)
        raise HTTPException(status_code=500, detail=str(e))