// Annonce toutes les pages du site aux moteurs IndexNow (Bing, Yandex, Seznam…), après une mise en ligne.
//
//   INDEXNOW_KEY=<clé> npm run indexnow
//
// La même clé doit être posée dans les variables du projet Vercel « verifac-site » : le site la sert
// à https://verifac.company/<clé>.txt, et le moteur vient la lire pour vérifier l'annonce.
const SITE = process.env.VERIFAC_SITE ?? "https://verifac.company";
const cle = (process.env.INDEXNOW_KEY ?? "").trim();
if (!/^[0-9a-f]{32}$/.test(cle)) {
  console.error("INDEXNOW_KEY manquante ou invalide (32 caractères hexadécimaux). Pour en créer une : openssl rand -hex 16");
  process.exit(1);
}

const plan = await (await fetch(`${SITE}/sitemap.xml`)).text();
const adresses = [...plan.matchAll(/<loc>([^<]+)<\/loc>/g)].map(([, url]) => url);
const verification = await fetch(`${SITE}/${cle}.txt`);
if (!verification.ok || (await verification.text()).trim() !== cle) {
  console.error(`${SITE}/${cle}.txt ne sert pas la clé : posez INDEXNOW_KEY dans Vercel et redéployez d'abord.`);
  process.exit(1);
}

const reponse = await fetch("https://api.indexnow.org/indexnow", {
  method: "POST",
  headers: { "Content-Type": "application/json; charset=utf-8" },
  body: JSON.stringify({ host: new URL(SITE).host, key: cle, keyLocation: `${SITE}/${cle}.txt`, urlList: adresses }),
});
// 200 : reçu ; 202 : reçu, clé en cours de vérification. Le reste est une erreur.
console.log(`IndexNow : ${adresses.length} adresses annoncées, réponse ${reponse.status}.`);
if (![200, 202].includes(reponse.status)) process.exit(1);
