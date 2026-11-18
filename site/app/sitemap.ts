import type { MetadataRoute } from "next";
import { ARTICLES } from "@/contenu/ressources";
import { GLOSSAIRE } from "@/contenu/glossaire";
import { GUIDES } from "@/contenu/guides";
import { SITE } from "@/contenu/site";

const MISE_A_JOUR = "2026-11-18";

export default function sitemap(): MetadataRoute.Sitemap {
  const page = (chemin: string, priorite: number, modifie = MISE_A_JOUR): MetadataRoute.Sitemap[number] => ({
    url: `${SITE.adresse}${chemin === "/" ? "" : chemin}`,
    lastModified: modifie,
    changeFrequency: "monthly",
    priority: priorite,
  });
  return [
    page("/", 1),
    page("/fonctionnalites", 0.9),
    page("/outils", 0.7),
    page("/outils/verifier-iban", 0.9),
    page("/outils/verifier-numero-tva-intracommunautaire", 0.9),
    page("/ressources", 0.7),
    ...ARTICLES.map((a) => page(`/ressources/${a.slug}`, 0.8, a.modifie)),
    page("/glossaire", 0.7),
    ...GLOSSAIRE.map((t) => page(`/glossaire/${t.slug}`, 0.5)),
    page("/documentation", 0.6),
    ...GUIDES.map((g) => page(`/documentation/${g.slug}`, 0.5)),
    page("/a-propos", 0.5),
    page("/contact", 0.5),
    page("/mentions-legales", 0.2),
    page("/confidentialite", 0.2),
  ];
}
