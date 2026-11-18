import type { Metadata } from "next";
import { alternatives, description, titre } from "@/lib/seo";
import Link from "next/link";
import { SITE } from "@/contenu/site";
import { graphe } from "@/lib/schema";
import { DonneesStructurees } from "../composants/DonneesStructurees";
import { FilAriane } from "../composants/FilAriane";

export const metadata: Metadata = {
  title: titre("Contact : une question, une démo, le pilote"),
  description: description("Contactez Verifac par mail : question sur le produit, démonstration, programme pilote ou support. Réponse sous un jour ouvré, par une personne."),
  alternates: alternatives("/contact"),
};

const RAISONS = [
  { titre: "Voir Verifac en action", texte: "Essayez la démo en un clic, ou écrivez-nous pour une démonstration de vingt minutes sur vos propres factures.", lien: SITE.demo, action: "Essayer la démo", externe: true },
  { titre: "Rejoindre le programme pilote", texte: "Deux mois offerts, installation faite pour vous. Cinq places.", lien: "/#pilote", action: "Demander une place", externe: false },
  { titre: "Une question sur le produit", texte: "Fonctionnement, sécurité, intégration à votre comptabilité : la documentation répond à la plupart des questions.", lien: "/documentation", action: "Lire la documentation", externe: false },
];

export default function Contact() {
  const sujet = encodeURIComponent("Question sur Verifac");
  return (
    <main className="texte">
      <div className="conteneur page-outil">
        <FilAriane etapes={[["Accueil", "/"], ["Contact", "/contact"]]} />
        <header className="page-outil__tete">
          <h1>Contacter Verifac</h1>
          <p className="chapo">Une personne qui connaît Verifac vous répond, pas un robot. Réponse sous un jour ouvré, du lundi au vendredi.</p>
        </header>

        <div className="contact-principal">
          <div>
            <h2>Par mail</h2>
            <p>Pour toute question, une démonstration, le pilote ou le support.</p>
          </div>
          <a className="bouton bouton--plein" href={`mailto:${SITE.support}?subject=${sujet}`}>
            {SITE.support}
          </a>
        </div>

        <div className="cartes" style={{ marginTop: "1.25rem" }}>
          {RAISONS.map((raison) =>
            raison.externe ? (
              <a className="carte-lien" href={raison.lien} key={raison.titre}>
                <h2>{raison.titre}</h2>
                <p>{raison.texte}</p>
                <span className="carte-lien__meta">{raison.action}</span>
              </a>
            ) : (
              <Link className="carte-lien" href={raison.lien} key={raison.titre}>
                <h2>{raison.titre}</h2>
                <p>{raison.texte}</p>
                <span className="carte-lien__meta">{raison.action}</span>
              </Link>
            ),
          )}
        </div>

        <div className="prose" style={{ marginTop: "3rem" }}>
          <h2>Pour aller plus vite</h2>
          <ul>
            <li>
              <strong>Un problème dans Verifac ?</strong> Indiquez l’écran concerné et, si possible, le numéro de la facture.
            </li>
            <li>
              <strong>Une question sur le pilote ?</strong> Précisez votre nombre de factures fournisseurs par mois et votre logiciel comptable.
            </li>
            <li>
              <strong>Développeurs</strong> : la référence de l’API est sur <a href="https://app.verifac.company/api/v1/docs">app.verifac.company/api/v1/docs</a>.
            </li>
          </ul>
        </div>
      </div>
      <DonneesStructurees
        donnees={graphe({
          "@type": "ContactPage",
          name: "Contacter Verifac",
          url: `${SITE.adresse}/contact`,
          inLanguage: "fr-FR",
          mainEntity: { "@id": `${SITE.adresse}/#organisation` },
        })}
      />
    </main>
  );
}
