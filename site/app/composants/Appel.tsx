import Link from "next/link";
import { SITE } from "@/contenu/site";

/** L'encart de fin d'article ou d'outil : passer de la lecture à l'essai. */
export function Appel({ titre = "Verifac fait ce contrôle sur chaque facture, automatiquement.", texte }: { titre?: string; texte?: string }) {
  return (
    <aside className="appel">
      <div>
        <h2>{titre}</h2>
        <p>
          {texte ??
            "Verifac lit vos factures fournisseurs, contrôle l’IBAN, le SIRET, la TVA, les doublons et les montants, puis les fait approuver par les bonnes personnes avant le paiement."}
        </p>
      </div>
      <div className="appel__actions">
        <a className="bouton bouton--plein" href={SITE.demo}>
          Essayer la démo
        </a>
        <Link className="bouton bouton--trait" href="/#pilote">
          Rejoindre le pilote
        </Link>
      </div>
    </aside>
  );
}
