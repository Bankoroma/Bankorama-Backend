import logging
import os
import smtplib
import ssl
from email.message import EmailMessage


logger = logging.getLogger(__name__)

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
MAIL_USERNAME = os.getenv("MAIL_USERNAME")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
MAIL_FROM = os.getenv("MAIL_FROM", MAIL_USERNAME)

FRONTEND_URL = os.getenv(
    "FRONTEND_URL",
    "http://localhost:3000"
)


def _send(to_email: str, subject: str, body: str):
    """
    Envoi SMTP. Exécuté en tâche de fond : un échec est journalisé
    mais ne bloque jamais l'inscription ou l'activation.
    """

    if not SMTP_HOST:
        logger.warning("SMTP non configuré, email non envoyé à %s", to_email)
        return

    message = EmailMessage()
    message["From"] = MAIL_FROM
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    context = ssl.create_default_context()

    try:
        # 465 = SSL direct, sinon STARTTLS (587)
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=15) as server:
                server.login(MAIL_USERNAME, MAIL_PASSWORD)
                server.send_message(message)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
                server.starttls(context=context)
                server.login(MAIL_USERNAME, MAIL_PASSWORD)
                server.send_message(message)

        logger.info("Email envoyé à %s", to_email)

    except (smtplib.SMTPException, OSError):
        logger.exception("Échec d'envoi de l'email à %s", to_email)


def send_registration_email(to_email: str, raison_sociale: str, plan_name: str):
    _send(
        to_email,
        "Bienvenue sur Bankorama",
        f"""
Bonjour {raison_sociale},

Merci de vous être inscrit sur Bankorama avec la formule {plan_name}.

Votre compte est créé : vous pouvez dès maintenant vous connecter.
Les conversions seront disponibles dès que notre équipe aura activé votre abonnement.

{FRONTEND_URL}/login
""",
    )


def send_activation_email(
    to_email: str,
    raison_sociale: str,
    plan_name: str,
    monthly_credits: int,
):
    _send(
        to_email,
        "Votre abonnement Bankorama est activé",
        f"""
Bonjour {raison_sociale},

Votre abonnement {plan_name} est actif : {monthly_credits} crédits
sont disponibles et seront rechargés chaque mois.

{FRONTEND_URL}/dashboard
""",
    )
