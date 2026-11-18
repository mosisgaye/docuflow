/** Données structurées schema.org (JSON-LD) : ce que Google lit pour comprendre la page. */
export function DonneesStructurees({ donnees }: { donnees: Record<string, unknown> | Record<string, unknown>[] }) {
  // « < » échappé : le JSON ne peut pas fermer la balise script.
  const json = JSON.stringify(donnees).replace(/</g, "\\u003c");
  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: json }} />;
}
