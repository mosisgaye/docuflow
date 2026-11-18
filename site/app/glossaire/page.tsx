import type { Metadata } from "next";
import { alternatives, description, titre } from "@/lib/seo";
import Link from "next/link";
import { GLOSSAIRE } from "@/contenu/glossaire";
import { SITE } from "@/contenu/site";
import { graphe } from "@/lib/schema";
import { DonneesStructurees } from "../composants/DonneesStructurees";
import { FilAriane } from "../composants/FilAriane";

export const metadata: Metadata = {
  title: titre("Glossaire des factures fournisseurs"),
  description: description("Les mots des factures fournisseurs et de la facture électronique expliqués simplement : autoliquidation, avoir, Factur-X, SIRET, IBAN, plateforme agréée…"),
  alternates: alternatives("/glossaire"),
};

const parLettre = () => {
  const groupes = new Map<string, typeof GLOSSAIRE>();
  for (const t of [...GLOSSAIRE].sort((a, b) => a.terme.localeCompare(b.terme, "fr"))) {
    const lettre = t.terme.normalize("NFD")[0].toUpperCase();
    groupes.set(lettre, [...(groupes.get(lettre) ?? []), t]);
  }
  return [...groupes.entries()];
};

export default function Glossaire() {
  const groupes = parLettre();
  return (
    <main className="texte">
      <div className="conteneur page-outil">
        <FilAriane etapes={[["Accueil", "/"], ["Glossaire", "/glossaire"]]} />
        <header className="page-outil__tete">
          <h1>Glossaire des factures fournisseurs</h1>
          <p className="chapo">Les mots qu’on croise en traitant les factures fournisseurs et la facture électronique, expliqués simplement, avec ce qu’il faut vérifier.</p>
        </header>
        <nav className="pastilles" aria-label="Lettres">
          {groupes.map(([lettre]) => (
            <a key={lettre} href={`#lettre-${lettre}`}>
              {lettre}
            </a>
          ))}
        </nav>
        <div className="glossaire">
          {groupes.map(([lettre, termes]) => (
            <section key={lettre} id={`lettre-${lettre}`}>
              <h2>{lettre}</h2>
              <dl>
                {termes.map((t) => (
                  <div key={t.slug}>
                    <dt>
                      <Link href={`/glossaire/${t.slug}`}>{t.terme}</Link>
                    </dt>
                    <dd>{t.definition}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}
        </div>
      </div>
      <DonneesStructurees
        donnees={graphe({
          "@type": "DefinedTermSet",
          "@id": `${SITE.adresse}/glossaire#ensemble`,
          name: "Glossaire des factures fournisseurs",
          inLanguage: "fr-FR",
          hasDefinedTerm: GLOSSAIRE.map((t) => ({ "@type": "DefinedTerm", name: t.terme, description: t.definition, url: `${SITE.adresse}/glossaire/${t.slug}` })),
        })}
      />
    </main>
  );
}
