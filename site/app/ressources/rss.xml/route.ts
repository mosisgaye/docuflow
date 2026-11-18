import { ARTICLES } from "@/contenu/ressources";
import { SITE } from "@/contenu/site";

export const dynamic = "force-static";

const echapper = (texte: string) => texte.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const dateRss = (iso: string) => new Date(`${iso}T08:00:00Z`).toUTCString();

/** Le flux RSS des ressources : agrégateurs, veilles et lecteurs RSS voient chaque nouvel article. */
export function GET() {
  const articles = [...ARTICLES].sort((a, b) => b.modifie.localeCompare(a.modifie));
  const elements = articles
    .map((a) => {
      const url = `${SITE.adresse}/ressources/${a.slug}`;
      return `    <item>
      <title>${echapper(a.titre)}</title>
      <link>${url}</link>
      <guid isPermaLink="true">${url}</guid>
      <description>${echapper(a.description)}</description>
      <pubDate>${dateRss(a.publie)}</pubDate>
    </item>`;
    })
    .join("\n");
  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Ressources Verifac</title>
    <link>${SITE.adresse}/ressources</link>
    <atom:link href="${SITE.adresse}/ressources/rss.xml" rel="self" type="application/rss+xml"/>
    <description>Guides pratiques sur les factures fournisseurs, la facture électronique et la fraude au faux RIB.</description>
    <language>fr-FR</language>
    <lastBuildDate>${dateRss(articles[0].modifie)}</lastBuildDate>
${elements}
  </channel>
</rss>
`;
  return new Response(xml, { headers: { "Content-Type": "application/rss+xml; charset=utf-8" } });
}
