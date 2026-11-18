// Le fichier de clé IndexNow, servi à la racine (/{clé}.txt, voir next.config.ts) : il prouve à Bing,
// Yandex et aux autres moteurs IndexNow que les annonces de pages viennent bien de nous.
// Introuvable tant que INDEXNOW_KEY n'est pas posée dans les variables du projet Vercel.
export const dynamic = "force-dynamic";

export async function GET(_: Request, { params }: { params: Promise<{ cle: string }> }) {
  const cle = (process.env.INDEXNOW_KEY ?? "").trim();
  const demandee = (await params).cle;
  if (!cle || demandee !== cle) return new Response("Introuvable", { status: 404 });
  return new Response(cle, { headers: { "Content-Type": "text/plain; charset=utf-8" } });
}
