import json
import os
import urllib.request


RESEND_API_KEY = os.getenv("RESEND_API_KEY")

FRONTEND_URL = os.getenv(
    "FRONTEND_URL",
    "http://localhost:3002"
)

RESEND_FROM = os.getenv(
    "RESEND_FROM",
    "Bankorama <onboarding@resend.dev>"
)


def send_verification_email(
    to_email: str,
    token: str,
    raison_sociale: str
):
    verification_url = (
        f"{FRONTEND_URL}/verify-email?token={token}"
    )

    data = {
        "from": RESEND_FROM,
        "to": [to_email],
        "subject": "Vérification de votre compte Bankorama",
        "text": f"""
Bonjour {raison_sociale},

Merci de vous être inscrit sur Bankorama.

Cliquez sur le lien suivant pour vérifier votre adresse email :

{verification_url}

Ce lien est valable pendant 24 heures.
"""
    }

    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(data).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=15) as response:
        response.read()