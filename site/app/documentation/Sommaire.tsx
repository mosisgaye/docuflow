import Link from "next/link";
import { GUIDES } from "@/contenu/guides";
import { SITE } from "@/contenu/site";

export function Sommaire({ actuel }: { actuel?: string }) {
  return (
    <nav className="sommaire" aria-label="Guides">
      <p>Guides</p>
      <Link href="/documentation" aria-current={actuel ? undefined : "page"}>
        Vue d’ensemble
      </Link>
      {GUIDES.map((guide) => (
        <Link key={guide.slug} href={`/documentation/${guide.slug}`} aria-current={guide.slug === actuel ? "page" : undefined}>
          {guide.titre}
        </Link>
      ))}
      <p style={{ marginTop: "1.5rem" }}>Besoin d’aide ?</p>
      <a href={`mailto:${SITE.support}`}>{SITE.support}</a>
    </nav>
  );
}
