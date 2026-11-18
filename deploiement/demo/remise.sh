#!/bin/sh
# Remet la démo dans son état de référence chaque nuit (REMISE_HEURE, heure UTC, par défaut 0200 = 3 h à Paris en hiver).
# Tourne en boucle dans le service « remise » de compose.demo.yaml.
set -u
HEURE="${REMISE_HEURE:-0200}"
fait_le=""
echo "Remise à zéro de la démo programmée chaque jour à ${HEURE} UTC."
while true; do
  jour=$(date -u +%F)
  if [ "$(date -u +%H%M)" = "$HEURE" ] && [ "$fait_le" != "$jour" ]; then
    fait_le="$jour"  # une seule tentative par nuit, réussie ou non : l'échec est écrit au journal
    /scripts/remettre.sh || echo "Remise à zéro échouée le ${jour}."
  fi
  sleep 20
done
