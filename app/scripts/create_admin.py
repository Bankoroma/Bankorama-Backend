"""
Crée un compte administrateur, ou promeut un compte existant.

    docker exec -it gares_api python -m app.scripts.create_admin admin@exemple.com

Le mot de passe est demandé de façon masquée (ou lu dans ADMIN_PASSWORD).
"""

import getpass
import os
import sys

from sqlalchemy import text

from app.database.database import owner_engine
from app.database.migrations import run_migrations
from app.security.security import hash_password


def main():
    if len(sys.argv) < 2:
        print("Usage : python -m app.scripts.create_admin <email> [raison sociale]")
        sys.exit(1)

    email = sys.argv[1].strip().lower()
    raison_sociale = sys.argv[2] if len(sys.argv) > 2 else "Administration Bankorama"

    run_migrations()

    with owner_engine.begin() as conn:
        existing = conn.execute(
            text("SELECT id FROM users WHERE lower(email) = :e"),
            {"e": email},
        ).scalar()

        if existing:
            conn.execute(
                text(
                    "UPDATE users SET role = 'admin', subscription_status = 'active', "
                    "is_active = true WHERE id = :id"
                ),
                {"id": existing},
            )
            print(f"Compte {email} promu administrateur.")
            return

        password = os.getenv("ADMIN_PASSWORD") or getpass.getpass("Mot de passe : ")

        if len(password) < 12:
            print("Mot de passe trop court (12 caractères minimum).")
            sys.exit(1)

        conn.execute(
            text(
                """
                INSERT INTO users (raison_sociale, email, hashed_password, is_active,
                                   is_verified, credits, role, subscription_status)
                VALUES (:rs, :e, :pwd, true, true, 0, 'admin', 'active')
                """
            ),
            {"rs": raison_sociale, "e": email, "pwd": hash_password(password)},
        )
        print(f"Administrateur {email} créé.")


if __name__ == "__main__":
    main()
