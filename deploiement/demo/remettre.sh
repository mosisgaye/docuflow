#!/bin/sh
# Remet la base et les fichiers de la démo tels qu'ils étaient au moment de la photo (photographier.sh).
# Refuse si le schéma a changé depuis la photo : il faut d'abord refaire la photo.
set -eu
REF="${REFERENCE:-/reference}"
DONNEES="${DONNEES:-/donnees}"
if [ ! -f "$REF/base.dump" ] || [ ! -f "$REF/version" ] || [ ! -f "$REF/fichiers.tgz" ]; then
  echo "Pas de photo de référence complète dans $REF : rien n'est remis."
  exit 1
fi
actuelle=$(psql -tAc "select version_num from alembic_version")
attendue=$(cat "$REF/version")
if [ "$actuelle" != "$attendue" ]; then
  echo "La base est au schéma $actuelle, la photo au schéma $attendue : refaire la photo. Rien n'est remis."
  exit 1
fi

# La base, en une seule transaction : si quelque chose échoue, rien ne change.
pg_restore --clean --if-exists --single-transaction --no-owner --dbname "$PGDATABASE" "$REF/base.dump"

# Les fichiers : on prépare le nouveau dossier à côté, puis on l'échange avec l'ancien.
proprietaire=$(stat -c %u:%g "$DONNEES")
rm -rf "$DONNEES/fichiers.nouveau" "$DONNEES/fichiers.ancien"
mkdir "$DONNEES/fichiers.nouveau"
tar -xzf "$REF/fichiers.tgz" -C "$DONNEES/fichiers.nouveau"
chown -R "$proprietaire" "$DONNEES/fichiers.nouveau"
if [ -d "$DONNEES/fichiers" ]; then mv "$DONNEES/fichiers" "$DONNEES/fichiers.ancien"; fi
mv "$DONNEES/fichiers.nouveau" "$DONNEES/fichiers"
rm -rf "$DONNEES/fichiers.ancien" "$DONNEES/exports"
echo "Démo remise à zéro ($(date -u '+%F %H:%M') UTC)."
