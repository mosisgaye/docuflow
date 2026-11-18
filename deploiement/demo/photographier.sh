#!/bin/sh
# Prend la photo de référence de la démo : la base, sa version de schéma et les fichiers rangés.
# À lancer quand la démo est dans l'état voulu (factures déposées, circuit publié), et après chaque migration :
#   docker compose -f compose.demo.yaml exec remise /scripts/photographier.sh
set -eu
REF="${REFERENCE:-/reference}"
DONNEES="${DONNEES:-/donnees}"
mkdir -p "$REF"
pg_dump --format=custom --no-owner --file "$REF/base.dump.nouveau"
psql -tAc "select version_num from alembic_version" > "$REF/version.nouveau"
mkdir -p "$DONNEES/fichiers"
tar -czf "$REF/fichiers.tgz.nouveau" -C "$DONNEES/fichiers" .
for nom in base.dump version fichiers.tgz; do mv "$REF/$nom.nouveau" "$REF/$nom"; done
echo "Photo prise : schéma $(cat "$REF/version"), $(psql -tAc 'select count(*) from factures') factures."
