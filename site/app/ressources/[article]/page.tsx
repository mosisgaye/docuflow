import { readFileSync } from "node:fs";
import { join } from "node:path";
import GithubSlugger from "github-slugger";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ARTICLES, article as trouver } from "@/contenu/ressources";
import { SITE } from "@/contenu/site";
import { graphe } from "@/lib/schema";
import { alternatives, description, titre } from "@/lib/seo";
import { Appel } from "../../composants/Appel";
import { DonneesStructurees } from "../../composants/DonneesStructurees";
import { FilAriane } from "../../composants/FilAriane";

type Parametres = { params: Promise<{ article: string }> };

export function generateStaticParams() {
  return ARTICLES.map((a) => ({ article: a.slug }));
}

// Seuls les articles de la liste existent : toute autre adresse répond 404.
export const dynamicParams = false;

export async function generateMetadata({ params }: Parametres): Promise<Metadata> {
  const fiche = trouver((await params).article);
  if (!fiche) return {};
  const chemin = `/ressources/${fiche.slug}`;
  return {
    title: titre(fiche.titreSeo),
    description: description(fiche.description),
    alternates: alternatives(chemin),
    authors: [{ name: "Moussa Gaye", url: "/a-propos" }],
    openGraph: { type: "article", title: fiche.titre, description: fiche.description, url: chemin, publishedTime: fiche.publie, modifiedTime: fiche.modifie },
  };
}

/** Typographie française : espace insécable fine avant « : ; ? ! », pour qu’ils ne commencent jamais une ligne. */
const insecable = (texte: string) => texte.replace(/ ([:;?!])/g, "\u202f$1");

const date = (iso: string) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" });

/** Le sommaire : les titres de niveau 2 du texte, avec les mêmes ancres que rehype-slug. */
function sommaire(slug: string): { id: string; texte: string }[] {
  const source = readFileSync(join(process.cwd(), "contenu", "ressources", `${slug}.mdx`), "utf8");
  const slugger = new GithubSlugger();
  return [...source.matchAll(/^## (.+)$/gm)].map(([, texte]) => {
    const propre = texte.replace(/[*_`]/g, "").trim();
    return { id: slugger.slug(propre), texte: propre };
  });
}

export default async function PageArticle({ params }: Parametres) {
  const { article: slug } = await params;
  const fiche = trouver(slug);
  if (!fiche) notFound();
  const { default: Contenu } = await import(`@/contenu/ressources/${slug}.mdx`);
  const liees = fiche.liees.map(trouver).filter((a) => a !== undefined);
  const chemin = `/ressources/${slug}`;
  const titres = sommaire(slug);

  return (
    <main className="texte">
      <div className="conteneur article-grille">
        <article className="article">
          <FilAriane etapes={[["Accueil", "/"], ["Ressources", "/ressources"], [fiche.titre, chemin]]} />
          <header className="article__tete">
            <h1>{insecable(fiche.titre)}</h1>
            <p className="article__meta">
              Par <Link href="/a-propos">Moussa Gaye</Link>, mis à jour le <time dateTime={fiche.modifie}>{date(fiche.modifie)}</time>. {fiche.lecture} de lecture.
            </p>
          </header>

          <aside className="en-bref" aria-label="En bref">
            <p className="en-bref__titre">En bref</p>
            <ul>
              {fiche.enBref.map((point) => (
                <li key={point}>{point}</li>
              ))}
            </ul>
          </aside>

          <div className="prose">
            <Contenu />
          </div>

          {fiche.sources.length > 0 && (
            <section className="sources" aria-labelledby="sources">
              <h2 id="sources">Sources</h2>
              <ol>
                {fiche.sources.map((source) => (
                  <li key={source.url}>
                    <a href={source.url} rel="noopener" target="_blank">
                      {source.titre}
                    </a>
                  </li>
                ))}
              </ol>
            </section>
          )}

          <Appel />

          {liees.length > 0 && (
            <nav className="a-lire" aria-label="À lire aussi">
              <h2>À lire aussi</h2>
              <div className="cartes">
                {liees.map((liee) => (
                  <Link className="carte-lien" href={`/ressources/${liee.slug}`} key={liee.slug}>
                    <h3>{insecable(liee.titre)}</h3>
                    <p>{liee.description}</p>
                  </Link>
                ))}
              </div>
            </nav>
          )}
        </article>

        {titres.length > 2 && (
          <nav className="sommaire-article" aria-label="Sommaire de l’article">
            <p>Sur cette page</p>
            <ol>
              {titres.map((t) => (
                <li key={t.id}>
                  <a href={`#${t.id}`}>{t.texte}</a>
                </li>
              ))}
            </ol>
          </nav>
        )}
      </div>
      <DonneesStructurees
        donnees={graphe({
          "@type": "Article",
          headline: fiche.titre,
          description: fiche.description,
          datePublished: fiche.publie,
          dateModified: fiche.modifie,
          inLanguage: "fr-FR",
          mainEntityOfPage: `${SITE.adresse}${chemin}`,
          image: `${SITE.adresse}/opengraph-image`,
          author: { "@type": "Person", name: "Moussa Gaye", url: `${SITE.adresse}/a-propos` },
          publisher: { "@id": `${SITE.adresse}/#organisation` },
          citation: fiche.sources.map((s) => s.url),
        })}
      />
    </main>
  );
}
