import Link from "next/link";
import { DonneesStructurees } from "./DonneesStructurees";
import { filAriane, graphe } from "@/lib/schema";

/** Le fil d'Ariane visible, et sa version pour Google. Le dernier élément est la page elle-même. */
export function FilAriane({ etapes }: { etapes: [string, string][] }) {
  return (
    <>
      <nav className="chemin" aria-label="Fil d’Ariane">
        {etapes.map(([nom, chemin], rang) =>
          rang < etapes.length - 1 ? (
            <span key={chemin}>
              <Link href={chemin}>{nom}</Link>
              <span aria-hidden="true"> / </span>
            </span>
          ) : (
            <span key={chemin} aria-current="page">
              {nom}
            </span>
          ),
        )}
      </nav>
      <DonneesStructurees donnees={graphe(filAriane(etapes))} />
    </>
  );
}
