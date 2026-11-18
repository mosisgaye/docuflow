import type { Metadata } from "next";
import { alternatives, description, titre } from "@/lib/seo";
import Link from "next/link";
import { FilAriane } from "../composants/FilAriane";

export const metadata: Metadata = {
  title: titre("Outils gratuits : vérifier IBAN, TVA et SIRET"),
  description: description("Vérifiez un IBAN, un numéro de TVA intracommunautaire, un SIREN ou un SIRET. Outils gratuits, sans inscription, calculés dans votre navigateur."),
  alternates: alternatives("/outils"),
};

const OUTILS = [
  { chemin: "/outils/verifier-iban", titre: "Vérifier un IBAN", texte: "Format, longueur et clé de contrôle, pour la France et l’Europe." },
  {
    chemin: "/outils/verifier-numero-tva-intracommunautaire",
    titre: "Vérifier un numéro de TVA, un SIREN ou un SIRET",
    texte: "Clés de contrôle, et calcul du numéro de TVA à partir du SIREN.",
  },
];

export default function Outils() {
  return (
    <main className="texte">
      <div className="conteneur page-outil">
        <FilAriane etapes={[["Accueil", "/"], ["Outils gratuits", "/outils"]]} />
        <header className="page-outil__tete">
          <h1>Outils gratuits</h1>
          <p className="chapo">Les contrôles que Verifac fait sur chaque facture, à faire vous-même en un instant. Sans inscription, et rien ne quitte votre navigateur.</p>
        </header>
        <div className="cartes">
          {OUTILS.map((outil) => (
            <Link className="carte-lien" href={outil.chemin} key={outil.chemin}>
              <h2>{outil.titre}</h2>
              <p>{outil.texte}</p>
            </Link>
          ))}
        </div>
      </div>
    </main>
  );
}
