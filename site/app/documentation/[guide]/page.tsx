import type { Metadata } from "next";
import { alternatives, description, titre } from "@/lib/seo";
import Link from "next/link";
import { notFound } from "next/navigation";
import { GUIDES, guide as trouver } from "@/contenu/guides";
import { FilAriane } from "../../composants/FilAriane";
import { Sommaire } from "../Sommaire";

type Parametres = { params: Promise<{ guide: string }> };

export function generateStaticParams() {
  return GUIDES.map((guide) => ({ guide: guide.slug }));
}

// Seuls les guides de la liste existent : toute autre adresse répond 404.
export const dynamicParams = false;


export async function generateMetadata({ params }: Parametres): Promise<Metadata> {
  const fiche = trouver((await params).guide);
  return fiche ? { title: titre(fiche.titre), description: description(fiche.description, fiche.resume), alternates: alternatives(`/documentation/${fiche.slug}`) } : {};
}

export default async function PageGuide({ params }: Parametres) {
  const { guide: slug } = await params;
  const fiche = trouver(slug);
  if (!fiche) notFound();
  const { default: Contenu } = await import(`@/contenu/guides/${slug}.mdx`);
  const rang = GUIDES.indexOf(fiche);
  const precedent = GUIDES[rang - 1];
  const suivant = GUIDES[rang + 1];

  return (
    <main className="texte">
      <div className="conteneur texte__grille">
        <Sommaire actuel={slug} />
        <article>
          <FilAriane etapes={[["Accueil", "/"], ["Documentation", "/documentation"], [fiche.titre, `/documentation/${slug}`]]} />
          <div className="prose">
            <Contenu />
          </div>
          <nav className="suite" aria-label="Guides voisins">
            {precedent ? <Link href={`/documentation/${precedent.slug}`}>{precedent.titre}</Link> : <span />}
            {suivant && <Link href={`/documentation/${suivant.slug}`}>{suivant.titre}</Link>}
          </nav>
        </article>
      </div>
    </main>
  );
}
