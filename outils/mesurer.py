"""Mesure le moteur sur les factures d'exemple : temps, exactitude, contrôles.

Usage :
    uv run python -m outils.mesurer            # lecture + extraction par LLM + contrôles
    uv run python -m outils.mesurer --lecture  # lecture du PDF seule, sans LLM
"""

import json
import pathlib
import sys
import time

from moteur.controles import controler
from moteur.extraction_llm import ErreurExtraction, extraire
from moteur.lecture_pdf import lire_pdf
from moteur.modeles import Facture

FACTURES = pathlib.Path(__file__).resolve().parent.parent / "factures"


def compter_valeurs_justes(obtenue: Facture, attendue: Facture) -> tuple[int, int, list[str]]:
    """Compare champ par champ. Renvoie (justes, total, écarts)."""
    ecarts = []
    total = 0
    for champ in Facture.model_fields:
        if champ == "lignes":
            continue
        total += 1
        if getattr(obtenue, champ) != getattr(attendue, champ):
            ecarts.append(f"{champ} : attendu {getattr(attendue, champ)!r}, obtenu {getattr(obtenue, champ)!r}")
    for rang, ligne_attendue in enumerate(attendue.lignes):
        ligne_obtenue = obtenue.lignes[rang] if rang < len(obtenue.lignes) else None
        for champ in type(ligne_attendue).model_fields:
            total += 1
            valeur = getattr(ligne_obtenue, champ, None)
            if valeur != getattr(ligne_attendue, champ):
                ecarts.append(f"ligne {rang + 1}, {champ} : attendu {getattr(ligne_attendue, champ)!r}, obtenu {valeur!r}")
    if len(obtenue.lignes) > len(attendue.lignes):
        ecarts.append(f"{len(obtenue.lignes) - len(attendue.lignes)} ligne(s) en trop")
    return total - len(ecarts), total, ecarts


def main() -> None:
    lecture_seule = "--lecture" in sys.argv
    attendus = json.loads((FACTURES / "attendu.json").read_text(encoding="utf-8"))
    for nom, attendu in attendus.items():
        contenu = (FACTURES / nom).read_bytes()
        debut = time.monotonic()
        lu = lire_pdf(contenu)
        duree_lecture = time.monotonic() - debut
        ligne = f"{nom:26} lecture {duree_lecture * 1000:5.1f} ms"
        if lecture_seule:
            print(f"{ligne} | {len(lu.texte)} caractères")
            continue
        try:
            resultat = extraire(lu.texte)
        except ErreurExtraction as erreur:
            print(f"{ligne} | ÉCHEC : {erreur}")
            continue
        justes, total, ecarts = compter_valeurs_justes(resultat.facture, Facture.model_validate(attendu["facture"]))
        debut = time.monotonic()
        anomalies = controler(resultat.facture)
        duree_controles = time.monotonic() - debut
        codes = [anomalie.code for anomalie in anomalies]
        verdict = "conforme" if codes == attendu["anomalies"] else f"ATTENDU {attendu['anomalies']}"
        print(
            f"{ligne} | LLM {resultat.duree_s:4.2f} s | {justes}/{total} justes"
            f" | contrôles {duree_controles * 1000:.2f} ms : {codes or 'aucune anomalie'} ({verdict})"
        )
        for ecart in ecarts:
            print(f"    écart : {ecart}")
        for anomalie in anomalies:
            print(f"    {anomalie.gravite.value} : {anomalie.message}")


if __name__ == "__main__":
    main()
