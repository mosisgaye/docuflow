"use client";

import { useState } from "react";
import { verifierIban, type ResultatIban } from "@/lib/verifications";

/** Le vérificateur d'IBAN : tout se calcule dans le navigateur, rien n'est envoyé. */
export function VerificateurIban() {
  const [saisie, setSaisie] = useState("");
  const [resultat, setResultat] = useState<ResultatIban | null>(null);

  return (
    <div className="verificateur">
      <form
        onSubmit={(evenement) => {
          evenement.preventDefault();
          setResultat(verifierIban(saisie));
        }}
      >
        <label className="champ" htmlFor="iban">
          IBAN à vérifier
        </label>
        <div className="verificateur__ligne">
          <input
            id="iban"
            className="verificateur__saisie"
            value={saisie}
            onChange={(evenement) => {
              setSaisie(evenement.target.value);
              setResultat(null);
            }}
            placeholder="FR76 3000 6000 0112 3456 7890 189"
            autoComplete="off"
            spellCheck={false}
            inputMode="text"
          />
          <button className="bouton bouton--plein" type="submit">
            Vérifier
          </button>
        </div>
        <p className="verificateur__note">Le calcul se fait dans votre navigateur : l’IBAN n’est envoyé nulle part.</p>
      </form>
      {resultat && (
        <div className={`verdict ${resultat.valide ? "verdict--bon" : "verdict--faux"}`} role="status">
          {resultat.valide ? (
            <>
              <strong>Cet IBAN est valide.</strong>
              <code>{resultat.groupes}</code>
              <ul>
                {resultat.pays && <li>Pays : {resultat.pays}</li>}
                {resultat.banque && <li>Code banque : {resultat.banque}</li>}
                <li>Clé de contrôle juste (norme ISO 13616).</li>
              </ul>
              <p>
                Valide ne veut pas dire sûr : un fraudeur utilise un vrai IBAN, le sien. Si ce numéro vient d’un mail annonçant un changement de coordonnées, appelez le
                fournisseur au numéro que vous connaissez déjà.
              </p>
            </>
          ) : (
            <>
              <strong>Cet IBAN n’est pas valide.</strong>
              <p>{resultat.raison}</p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
