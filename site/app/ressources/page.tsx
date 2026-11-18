import type { Metadata } from "next";
import { alternatives, description, titre } from "@/lib/seo";
import Link from "next/link";
import { ARTICLES } from "@/contenu/ressources";
import { FilAriane } from "../composants/FilAriane";

export const metadata: Metadata = {
  title: titre("Guides : factures et facture électronique"),
  description: description("Guides pratiques pour les PME : facturation électronique 2026, Factur-X, mentions obligatoires, faux RIB, dématérialisation des factures fournisseurs, Odoo."),
  alternates: { ...alternatives("/ressources"), types: { "application/rss+xml": [{ url: "/ressources/rss.xml", title: "Ressources Verifac" }] } },
};

export default function Ressources() {
  return (
    <main className="texte">
      <div className="conteneur page-outil">
        <FilAriane etapes={[["Accueil", "/"], ["Ressources", "/ressources"]]} />
        <header className="page-outil__tete">
          <h1>Ressources</h1>
          <p className="chapo">Des guides pratiques pour traiter les factures fournisseurs d’une PME : la réforme de la facture électronique, les contrôles, la fraude, les outils.</p>
        </header>
        <div className="cartes">
          {ARTICLES.map((a) => (
            <Link className="carte-lien" href={`/ressources/${a.slug}`} key={a.slug}>
              <h2>{a.titre.replace(/ ([:;?!])/g, "\u202f$1")}</h2>
              <p>{a.description}</p>
              <span className="carte-lien__meta">{a.lecture} de lecture</span>
            </Link>
          ))}
        </div>
      </div>
    </main>
  );
}
