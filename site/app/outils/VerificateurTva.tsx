"use client";

import { useState } from "react";
import { verifierIdentifiant, type ResultatIdentifiant } from "@/lib/verifications";

const GENRE = { siren: "SIREN", siret: "SIRET", tva: "numéro de TVA" } as const;

/** Vérifie un numéro de TVA français, un SIREN ou un SIRET, et calcule le numéro de TVA. Dans le navigateur. */
export function VerificateurTva() {
  const [saisie, setSaisie] = useState("");
  const [resultat, setResultat] = useState<ResultatIdentifiant | null>(null);

  return (
    <div className="verificateur">
      <form
        onSubmit={(evenement) => {
          evenement.preventDefault();
          setResultat(verifierIdentifiant(saisie));
        }}
      >
        <label className="champ" htmlFor="identifiant">
          Numéro de TVA, SIREN ou SIRET
        </label>
        <div className="verificateur__ligne">
          <input
            id="identifiant"
            className="verificateur__saisie"
            value={saisie}
            onChange={(evenement) => {
              setSaisie(evenement.target.value);
              setResultat(null);
            }}
            placeholder="FR44 732 829 320 ou 732 829 320 00074"
            autoComplete="off"
            spellCheck={false}
          />
          <button className="bouton bouton--plein" type="submit">
            Vérifier
          </button>
        </div>
        <p className="verificateur__note">Le calcul se fait dans votre navigateur : le numéro n’est envoyé nulle part.</p>
      </form>
      {resultat && (
        <div className={`verdict ${resultat.valide ? "verdict--bon" : "verdict--faux"}`} role="status">
          {resultat.valide ? (
            <>
              <strong>Ce {GENRE[resultat.genre]} est valide.</strong>
              <ul>
                <li>
                  SIREN : <code>{resultat.siren}</code>
                </li>
                {resultat.siret && (
                  <li>
                    SIRET : <code>{resultat.siret}</code>
                  </li>
                )}
                <li>
                  Numéro de TVA intracommunautaire : <code>{resultat.tva}</code>
                </li>
              </ul>
              <p>
                Le format et les clés de contrôle sont justes. Pour savoir si l’entreprise existe et si son numéro de TVA est actif, consultez l’annuaire des entreprises
                (annuaire-entreprises.data.gouv.fr) ou le service VIES de la Commission européenne.
              </p>
            </>
          ) : (
            <>
              <strong>Ce numéro n’est pas valide.</strong>
              <p>{resultat.raison}</p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
