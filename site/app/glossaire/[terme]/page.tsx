import type { Metadata } from "next";
import { alternatives, description, titre } from "@/lib/seo";
import Link from "next/link";
import { notFound } from "next/navigation";
import { GLOSSAIRE, terme as trouver } from "@/contenu/glossaire";
import { SITE } from "@/contenu/site";
import { graphe } from "@/lib/schema";
import { Appel } from "../../composants/Appel";
import { DonneesStructurees } from "../../composants/DonneesStructurees";
import { FilAriane } from "../../composants/FilAriane";

type Parametres = { params: Promise<{ terme: string }> };

export function generateStaticParams() {
  return GLOSSAIRE.map((t) => ({ terme: t.slug }));
}

// Seuls les termes de la liste existent : toute autre adresse répond 404.
export const dynamicParams = false;

export async function generateMetadata({ params }: Parametres): Promise<Metadata> {
  const t = trouver((await params).terme);
  if (!t) return {};
  // « Terme : définition » quand il tient en 60 caractères avec « , Verifac » ; sinon le terme seul.
  return { title: titre(`${t.terme} : définition`, t.terme), description: description(t.definition), alternates: alternatives(`/glossaire/${t.slug}`) };
}

export default async function PageTerme({ params }: Parametres) {
  const { terme: slug } = await params;
  const t = trouver(slug);
  if (!t) notFound();
  const chemin = `/glossaire/${slug}`;
  return (
    <main className="texte">
      <article className="conteneur article">
        <FilAriane etapes={[["Accueil", "/"], ["Glossaire", "/glossaire"], [t.terme, chemin]]} />
        <header className="article__tete">
          <h1>{t.terme}</h1>
        </header>
        <div className="prose">
          <p className="definition">{t.definition}</p>
          {t.sections.map((section) => (
            <section key={section.titre}>
              <h2>{section.titre}</h2>
              {section.paragraphes.map((p) => (
                <p key={p.slice(0, 40)}>{p}</p>
              ))}
            </section>
          ))}
          <h2>Voir aussi</h2>
          <ul>
            {t.voir.map((v) => (
              <li key={v.lien}>
                <Link href={v.lien}>{v.texte}</Link>
              </li>
            ))}
            <li>
              <Link href="/glossaire">Tout le glossaire</Link>
            </li>
          </ul>
        </div>
        <Appel />
      </article>
      <DonneesStructurees
        donnees={graphe({
          "@type": "DefinedTerm",
          name: t.terme,
          description: t.definition,
          url: `${SITE.adresse}${chemin}`,
          inDefinedTermSet: `${SITE.adresse}/glossaire#ensemble`,
        })}
      />
    </main>
  );
}
