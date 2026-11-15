"""Crée la base « demo » de l'Odoo de démonstration (une seule fois).

    docker compose -f odoo/compose.yaml up -d
    uv run python -m outils.odoo_installer

Installe, sans données de démonstration d'Odoo : Contacts, CRM, Achats, Facturation,
et la comptabilité française (plan comptable général, TVA). La société est réglée en
France, en euros, en français. Le mot de passe de l'administrateur est celui de
odoo/.env (ODOO_ADMIN_MOT_DE_PASSE) : il n'est jamais affiché.

Sans effet si la comptabilité française est déjà installée. La base elle-même est créée
par Odoo au premier démarrage (option --database=demo du compose), avec le seul module de base.
"""

import os
import pathlib
import subprocess
import sys
import time

import httpx

RACINE = pathlib.Path(__file__).resolve().parent.parent
COMPOSE = ["docker", "compose", "-f", str(RACINE / "odoo" / "compose.yaml")]  # Compose charge odoo/.env tout seul
BASE = "demo"
MODULES = "contacts,crm,purchase,account,l10n_fr_account"
ADRESSE = "http://127.0.0.1:8069"

# Exécuté dans « odoo shell » : règle la société et le mot de passe de l'administrateur.
REGLAGES = """
import os
societe = env.ref("base.main_company")
societe.write({
    "name": "Transports Lemaire SAS",
    "country_id": env.ref("base.fr").id,
    "currency_id": env.ref("base.EUR").id,
    "street": "Zone d'activité des Pins",
    "zip": "30900",
    "city": "Nîmes",
})
administrateur = env.ref("base.user_admin")
administrateur.write({"password": os.environ["ODOO_ADMIN_MOT_DE_PASSE"], "lang": "fr_FR", "tz": "Europe/Paris"})
env.cr.commit()
print("societe", societe.name, societe.country_id.code, societe.currency_id.name)
"""


def lire_env_odoo() -> dict[str, str]:
    valeurs = {}
    for ligne in (RACINE / "odoo" / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in ligne and not ligne.lstrip().startswith("#"):
            cle, valeur = ligne.split("=", 1)
            valeurs[cle.strip()] = valeur.strip()
    return valeurs


def dans_odoo(script_shell: str, entree: str | None = None, env: dict[str, str] | None = None) -> str:
    """Lance une commande dans le conteneur Odoo, avec les paramètres de connexion à sa base."""
    options_env = [option for nom in (env or {}) for option in ("-e", nom)]
    resultat = subprocess.run(
        [*COMPOSE, "exec", "-T", *options_env, "odoo", "sh", "-c", script_shell],
        input=entree,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )
    if resultat.returncode != 0:
        sys.exit(f"Échec dans le conteneur Odoo :\n{resultat.stderr[-3000:]}")
    return resultat.stdout


def attendre_odoo() -> None:
    for _ in range(90):
        try:
            if httpx.get(f"{ADRESSE}/web/health", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    sys.exit("Odoo ne répond pas sur le port 8069.")


def main() -> None:
    connexion = '--db_host "$HOST" --db_user "$USER" --db_password "$PASSWORD"'
    attendre_odoo()
    etat = dans_odoo(
        f"PGPASSWORD=\"$PASSWORD\" psql -h \"$HOST\" -U \"$USER\" -d {BASE} -Atc \"select state from ir_module_module where name = 'l10n_fr_account'\""
    )
    if etat.strip() == "installed":
        print("La comptabilité française est déjà installée : rien à faire.")
        return
    # La société doit être en France AVANT l'installation de la comptabilité :
    # c'est ce qui fait appliquer le plan comptable général et les taxes françaises.
    dans_odoo(f"odoo {connexion} -d {BASE} --load-language=fr_FR --stop-after-init --no-http")
    sortie = dans_odoo(
        f"odoo shell {connexion} -d {BASE} --no-http",
        entree=REGLAGES,
        env={"ODOO_ADMIN_MOT_DE_PASSE": lire_env_odoo()["ODOO_ADMIN_MOT_DE_PASSE"]},
    )
    print(next((ligne for ligne in sortie.splitlines() if ligne.startswith("societe")), "réglages appliqués"))
    print("Installation des modules (quelques minutes)…")
    debut = time.monotonic()
    dans_odoo(f"odoo {connexion} -d {BASE} -i {MODULES} --without-demo=all --stop-after-init --no-http")
    print(f"Modules installés en {time.monotonic() - debut:.0f} s.")
    subprocess.run([*COMPOSE, "restart", "odoo"], check=True, capture_output=True)
    attendre_odoo()
    print(f"Odoo prêt : {ADRESSE}/odoo  (identifiant : admin, mot de passe : ODOO_ADMIN_MOT_DE_PASSE dans odoo/.env)")


if __name__ == "__main__":
    main()
