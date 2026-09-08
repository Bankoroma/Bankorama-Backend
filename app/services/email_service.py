import os
import smtplib
from email.message import EmailMessage


SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

MAIL_USERNAME = os.getenv("MAIL_USERNAME")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
MAIL_FROM = os.getenv("MAIL_FROM")


def send_verification_email(
    to_email: str,
    token: str,
    raison_sociale: str
):
    verification_url = (
        f"http://localhost:3002/verify-email?token={token}"
    )

    message = EmailMessage()

    message["Subject"] = "Vérification de votre compte Bankorama"
    message["From"] = MAIL_FROM
    message["To"] = to_email

    message.set_content(
        f"""
Bonjour {raison_sociale},

Merci de vous être inscrit sur Bankorama.

Cliquez sur le lien suivant pour vérifier votre adresse email :

{verification_url}

Ce lien est valable pendant 24 heures.
"""
    )

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(MAIL_USERNAME, MAIL_PASSWORD)
        server.send_message(message)