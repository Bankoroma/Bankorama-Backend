"""
Migrations idempotentes exécutées au démarrage avec le rôle propriétaire.

- crée le rôle applicatif (NOSUPERUSER, NOBYPASSRLS) utilisé par l'API
- ajoute les colonnes abonnement / rôle sur users
- crée et alimente la table plans
- active le Row Level Security et ses politiques
"""

from sqlalchemy import text

from app.database.database import APP_DB_PASSWORD, APP_DB_USER, Base, owner_engine
from app.database import models  # noqa: F401  (enregistre les modèles)


PLANS = [
    # code, nom, prix TTC (DH), crédits / mois, ordre
    ("starter", "Starter", 300, 30, 1),
    ("standard", "Standard", 600, 70, 2),
    ("ultime", "Ultime", 1800, 250, 3),
]


SCHEMA_SQL = """
ALTER TABLE users ADD COLUMN IF NOT EXISTS role varchar(20) NOT NULL DEFAULT 'user';
ALTER TABLE users ADD COLUMN IF NOT EXISTS plan_id integer REFERENCES plans(id);
ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_status varchar(20) NOT NULL DEFAULT 'pending';
ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_activated_at timestamptz;
ALTER TABLE users ADD COLUMN IF NOT EXISTS credits_renew_at timestamptz;
ALTER TABLE users ALTER COLUMN credits SET DEFAULT 0;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_role_check') THEN
        ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN ('user', 'admin'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_subscription_status_check') THEN
        ALTER TABLE users ADD CONSTRAINT users_subscription_status_check
            CHECK (subscription_status IN ('pending', 'active', 'suspended'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_credits_check') THEN
        ALTER TABLE users ADD CONSTRAINT users_credits_check CHECK (credits >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'conversions_status_check') THEN
        ALTER TABLE conversions ADD CONSTRAINT conversions_status_check
            CHECK (status IN ('success', 'failed'));
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS ux_users_email_lower ON users (lower(email));
CREATE INDEX IF NOT EXISTS ix_conversions_user_created ON conversions (user_id, created_at DESC);
"""


RLS_SQL = """
-- Contexte : identifiant de l'utilisateur authentifié, posé par l'API par transaction
CREATE OR REPLACE FUNCTION app_current_user_id() RETURNS integer
LANGUAGE sql STABLE AS $$
    SELECT NULLIF(current_setting('app.user_id', true), '')::integer
$$;

-- Le rôle admin est lu en base, jamais pris depuis le client
CREATE OR REPLACE FUNCTION app_is_admin() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT EXISTS (
        SELECT 1 FROM users
        WHERE id = app_current_user_id() AND role = 'admin' AND is_active
    )
$$;

-- Connexion : recherche par email avant authentification
CREATE OR REPLACE FUNCTION auth_find_user(p_email text)
RETURNS TABLE (id integer, hashed_password varchar, is_active boolean)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT u.id, u.hashed_password, u.is_active
    FROM users u WHERE lower(u.email) = lower(p_email)
$$;

-- Inscription : un nouveau compte est toujours "user", "pending" et sans crédit
CREATE OR REPLACE FUNCTION auth_register_user(
    p_raison_sociale text, p_email text, p_hashed_password text, p_plan_code text
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_plan_id integer;
    v_id integer;
BEGIN
    SELECT p.id INTO v_plan_id FROM plans p WHERE p.code = p_plan_code AND p.is_active;
    IF v_plan_id IS NULL THEN
        RAISE EXCEPTION 'Formule inconnue' USING ERRCODE = '22023';
    END IF;

    INSERT INTO users (raison_sociale, email, hashed_password, is_active, is_verified,
                       credits, role, plan_id, subscription_status)
    VALUES (p_raison_sociale, lower(p_email), p_hashed_password, true, false,
            0, 'user', v_plan_id, 'pending')
    RETURNING users.id INTO v_id;

    RETURN v_id;
END $$;

-- Un utilisateur ne peut pas modifier son rôle, son abonnement ni son statut
CREATE OR REPLACE FUNCTION users_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF current_setting('is_superuser') = 'on' THEN
        RETURN NEW;
    END IF;

    IF NOT app_is_admin() AND (
        NEW.role IS DISTINCT FROM OLD.role
        OR NEW.plan_id IS DISTINCT FROM OLD.plan_id
        OR NEW.subscription_status IS DISTINCT FROM OLD.subscription_status
        OR NEW.subscription_activated_at IS DISTINCT FROM OLD.subscription_activated_at
        OR NEW.is_active IS DISTINCT FROM OLD.is_active
        OR NEW.email IS DISTINCT FROM OLD.email
    ) THEN
        RAISE EXCEPTION 'Modification réservée aux administrateurs' USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS users_guard ON users;
CREATE TRIGGER users_guard BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION users_guard();

REVOKE ALL ON FUNCTION app_is_admin() FROM PUBLIC;
REVOKE ALL ON FUNCTION auth_find_user(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION auth_register_user(text, text, text, text) FROM PUBLIC;

-- users
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS users_select ON users;
DROP POLICY IF EXISTS users_update ON users;
CREATE POLICY users_select ON users FOR SELECT
    USING (id = app_current_user_id() OR app_is_admin());
CREATE POLICY users_update ON users FOR UPDATE
    USING (id = app_current_user_id() OR app_is_admin())
    WITH CHECK (id = app_current_user_id() OR app_is_admin());

-- plans : lecture publique, aucune écriture par l'API
ALTER TABLE plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE plans FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS plans_select ON plans;
CREATE POLICY plans_select ON plans FOR SELECT USING (true);

-- conversions : chacun voit et écrit uniquement les siennes, l'admin voit tout
ALTER TABLE conversions ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS conversions_select ON conversions;
DROP POLICY IF EXISTS conversions_insert ON conversions;
CREATE POLICY conversions_select ON conversions FOR SELECT
    USING (user_id = app_current_user_id() OR app_is_admin());
CREATE POLICY conversions_insert ON conversions FOR INSERT
    WITH CHECK (user_id = app_current_user_id());
"""


def _grants_sql(role: str) -> str:
    return f"""
GRANT USAGE ON SCHEMA public TO {role};
GRANT SELECT, UPDATE ON users TO {role};
GRANT SELECT ON plans TO {role};
GRANT SELECT, INSERT ON conversions TO {role};
GRANT USAGE ON SEQUENCE conversions_id_seq TO {role};
GRANT EXECUTE ON FUNCTION app_current_user_id() TO {role};
GRANT EXECUTE ON FUNCTION app_is_admin() TO {role};
GRANT EXECUTE ON FUNCTION auth_find_user(text) TO {role};
GRANT EXECUTE ON FUNCTION auth_register_user(text, text, text, text) TO {role};
"""


def _ensure_app_role(conn):
    if not APP_DB_USER.replace("_", "").isalnum():
        raise ValueError("APP_DB_USER invalide.")

    exists = conn.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = :r"),
        {"r": APP_DB_USER},
    ).scalar()

    verb = "ALTER" if exists else "CREATE"

    statement = conn.execute(
        text(
            "SELECT format('%s ROLE %I LOGIN NOSUPERUSER NOBYPASSRLS "
            "NOCREATEDB NOCREATEROLE PASSWORD %L', "
            "CAST(:verb AS text), CAST(:role AS text), CAST(:pw AS text))"
        ),
        {"verb": verb, "role": APP_DB_USER, "pw": APP_DB_PASSWORD},
    ).scalar()

    conn.exec_driver_sql(statement)


def run_migrations():
    Base.metadata.create_all(bind=owner_engine)

    with owner_engine.begin() as conn:
        # Un seul worker applique les migrations à la fois
        conn.execute(text("SELECT pg_advisory_xact_lock(724519)"))

        _ensure_app_role(conn)

        conn.exec_driver_sql(SCHEMA_SQL)

        for code, name, price, credits, order in PLANS:
            conn.execute(
                text(
                    """
                    INSERT INTO plans (code, name, price_ttc, monthly_credits, is_active, sort_order)
                    VALUES (:code, :name, :price, :credits, true, :order)
                    ON CONFLICT (code) DO UPDATE SET
                        name = EXCLUDED.name,
                        price_ttc = EXCLUDED.price_ttc,
                        monthly_credits = EXCLUDED.monthly_credits,
                        sort_order = EXCLUDED.sort_order
                    """
                ),
                {"code": code, "name": name, "price": price, "credits": credits, "order": order},
            )

        conn.exec_driver_sql(RLS_SQL)
        conn.exec_driver_sql(_grants_sql(f'"{APP_DB_USER}"'))
