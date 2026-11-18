"use client";

import { track } from "@vercel/analytics";
import Link from "next/link";
import { useState } from "react";

// Les mêmes listes que le moteur (moteur/pilote.py) : une valeur hors liste y est refusée.
const VOLUMES = ["Moins de 50", "50 à 200", "200 à 1 000", "Plus de 1 000"];
const LOGICIELS = ["Odoo", "Pennylane", "Sage", "Cegid", "Expert-comptable externe", "Autre"];

type Etat = { type: "saisie" } | { type: "envoi" } | { type: "envoye" } | { type: "erreur"; message: string };

/** La demande de place au programme pilote. Elle part au moteur (POST /api/pilote), qui la garde et l'annonce par mail. */
export function FormulairePilote() {
  const [etat, setEtat] = useState<Etat>({ type: "saisie" });

  async function envoyer(evenement: { preventDefault(): void; currentTarget: HTMLFormElement }) {
    evenement.preventDefault();
    const donnees = Object.fromEntries(new FormData(evenement.currentTarget));
    setEtat({ type: "envoi" });
    try {
      const reponse = await fetch("/api/pilote", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(donnees) });
      if (reponse.ok) {
        // La conversion principale du site : seulement la taille et le logiciel, jamais le nom ni l'adresse.
        track("demande_pilote", { volume: String(donnees.volume), logiciel: String(donnees.logiciel) });
        return setEtat({ type: "envoye" });
      }
      const corps = await reponse.json().catch(() => null);
      const detail = typeof corps?.detail === "string" ? corps.detail : "Vérifiez les champs : une information manque ou n’est pas valide.";
      setEtat({ type: "erreur", message: detail });
    } catch {
      setEtat({ type: "erreur", message: "La demande n’est pas partie. Vérifiez votre connexion, ou écrivez-nous directement." });
    }
  }

  if (etat.type === "envoye")
    return (
      <div className="formulaire">
        <div className="merci" role="status" style={{ display: "block" }}>
          <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <circle cx="12" cy="12" r="10" />
            <path d="M7.5 12.5l3 3 6-6.5" />
          </svg>
          <h3>Demande envoyée</h3>
          <p>Merci. Nous vous écrivons sous deux jours ouvrés pour convenir d’un appel.</p>
        </div>
      </div>
    );

  return (
    <div className="formulaire">
      <form onSubmit={envoyer}>
        <h3>Demander une place</h3>
        <p>Nous vous répondons sous deux jours ouvrés pour un appel de vingt minutes.</p>
        <div className="champs">
          <label className="champ">
            Nom et prénom
            <input name="nom" autoComplete="name" required minLength={2} maxLength={100} />
          </label>
          <label className="champ">
            Entreprise
            <input name="entreprise" autoComplete="organization" required minLength={2} maxLength={150} />
          </label>
          <label className="champ champ--large">
            Adresse professionnelle
            <input name="email" type="email" autoComplete="email" required maxLength={320} />
          </label>
          <label className="champ">
            Factures fournisseurs par mois
            <select name="volume" required defaultValue="">
              <option value="" disabled>
                Choisir
              </option>
              {VOLUMES.map((volume) => (
                <option key={volume}>{volume}</option>
              ))}
            </select>
          </label>
          <label className="champ">
            Logiciel comptable
            <select name="logiciel" required defaultValue="">
              <option value="" disabled>
                Choisir
              </option>
              {LOGICIELS.map((logiciel) => (
                <option key={logiciel}>{logiciel}</option>
              ))}
            </select>
          </label>
          <label className="champ champ--large">
            <span>
              Ce qui vous fait perdre du temps aujourd’hui <small>(facultatif)</small>
            </span>
            <textarea name="message" maxLength={3000} />
          </label>
          {/* Champ piège : invisible pour une personne, rempli par les robots. */}
          <label className="piege" aria-hidden="true">
            Site web
            <input name="site_web" tabIndex={-1} autoComplete="off" />
          </label>
        </div>
        {etat.type === "erreur" && (
          <p className="formulaire__erreur" role="alert">
            {etat.message}
          </p>
        )}
        <button className="bouton bouton--plein" type="submit" disabled={etat.type === "envoi"}>
          {etat.type === "envoi" ? "Envoi…" : "Envoyer ma demande"}
        </button>
        <p className="formulaire__mention">
          Vos informations servent seulement à vous recontacter pour le pilote. <Link href="/confidentialite">Confidentialité</Link>
        </p>
      </form>
    </div>
  );
}
