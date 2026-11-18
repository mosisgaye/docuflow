"use client";

import { useEffect, useState } from "react";

const CONTROLES = ["Lue par l’IA en 2,3 s", "SIRET valide, total juste", "Aucun doublon"];

/** L'unique animation du site : les contrôles passent un à un, le dernier retient la facture sur un IBAN jamais vu. */
export function Controles() {
  const [vus, setVus] = useState(0);
  useEffect(() => {
    // Mouvement réduit demandé : tout apparaît d'un coup.
    const calme = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const minuteries = Array.from({ length: CONTROLES.length + 1 }, (_, rang) => window.setTimeout(() => setVus(rang + 1), calme ? 0 : 500 + rang * 650));
    return () => minuteries.forEach(window.clearTimeout);
  }, []);

  return (
    <div className="controles" role="list" aria-label="Contrôles de Verifac sur une facture">
      <p className="controles__titre">Garage Central Bertin, facture F26-1302</p>
      {CONTROLES.map((texte, rang) => (
        <div key={texte} className={`controle${vus > rang ? " vu" : ""}`} role="listitem">
          <span className="pastille">
            <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M2.5 6.2l2.3 2.3 4.7-5" />
            </svg>
          </span>
          {texte}
        </div>
      ))}
      <div className={`controle${vus > CONTROLES.length ? " vu bloque" : ""}`} role="listitem">
        <span className="pastille">
          <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M3.5 3.5l5 5M8.5 3.5l-5 5" />
          </svg>
        </span>
        <span>
          IBAN jamais vu pour ce fournisseur
          <small>Facture retenue : appelez le garage à son numéro habituel avant de payer.</small>
        </span>
      </div>
    </div>
  );
}
