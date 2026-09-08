import os
import json
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)

class Transaction(BaseModel):
    date_valeur: str = Field(description="Date valeur au format DD/MM/YYYY")
    libelle: str = Field(description="Description ou nature de la transaction")
    type_paiement: str = Field(description="Type : Virement, Carte, Retrait, Chèque, Frais, etc.")
    debit: float | None = Field(default=None, description="Montant du débit (sortie d'argent) ou null")
    credit: float | None = Field(default=None, description="Montant du crédit (entrée d'argent) ou null")

class ReleveBancaire(BaseModel):
    banque: str = Field(description="Nom de la banque émettrice")
    titulaire: str = Field(description="Nom du titulaire du compte")
    periode: str = Field(description="Période couverte par le relevé")
    transactions: list[Transaction]

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


def _extraire_sync(pdf_path: str) -> dict:
    uploaded_file = client.files.upload(file=pdf_path)

    prompt = (
        "Tu es un expert comptable. Analyse ce relevé bancaire "
        "et extrais la liste exhaustive de toutes les transactions sans en oublier une seule."
    )

    try:
        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=[uploaded_file, prompt],   
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ReleveBancaire,
            ),
        )
        return json.loads(response.text)

    finally:
        try:
            client.files.delete(name=uploaded_file.name)
        except Exception:
            pass


async def extraire_donnees_pdf(pdf_path: str) -> dict:
    return await asyncio.to_thread(_extraire_sync, pdf_path)