import type { Metadata } from "next";
import { alternatives, description, titre } from "@/lib/seo";
import Link from "next/link";
import { GUIDES } from "@/contenu/guides";
import { SITE } from "@/contenu/site";
import { IconeDeGuide } from "../composants/Icones";
import { FilAriane } from "../composants/FilAriane";
import { Sommaire } from "./Sommaire";

export const metadata: Metadata = {
  title: titre("Documentation"),
  description: description("Les guides de Verifac : recevoir les factures, approuver, comprendre les anomalies, régler le circuit, brancher Odoo et Claude, utiliser l’API."),
  alternates: alternatives("/documentation"),
};

export default function Documentation() {
  return (
    <main className="texte">
      <div className="conteneur texte__grille">
        <Sommaire />
        <div>
          <FilAriane etapes={[["Accueil", "/"], ["Documentation", "/documentation"]]} />
          <div className="prose">
            <h1>Documentation</h1>
            <p>Des guides courts pour utiliser Verifac au quotidien. Chacun se lit en quelques minutes.</p>
          </div>
          <div className="guides" style={{ marginTop: "2rem" }}>
            {GUIDES.map((guide) => (
              <Link className="guide" href={`/documentation/${guide.slug}`} key={guide.slug}>
                <span className="guide__icone">
                  <IconeDeGuide nom={guide.icone} />
                </span>
                <span>
                  <strong>{guide.titre}</strong>
                  <span>{guide.resume}</span>
                </span>
                <time>{guide.duree}</time>
              </Link>
            ))}
          </div>
          <div className="panneau" style={{ marginTop: "1.25rem" }}>
            <h2 style={{ fontSize: "1.125rem" }}>Une question qui n’est pas ici ?</h2>
            <p style={{ color: "var(--texte-2)", marginTop: ".5rem" }}>
              Écrivez à <a href={`mailto:${SITE.support}`}>{SITE.support}</a>. Réponse sous un jour ouvré.
            </p>
          </div>
        </div>
      </div>
    </main>
  );
}
