import createMDX from "@next/mdx";
import type { NextConfig } from "next";

// Le site vitrine prend verifac.company ; le tableau de bord est sur app.verifac.company (projet Vercel « docuflow »).
// Les adresses d'avant restent valables :
// - /api/… et /.well-known/… vont toujours au moteur (anciens liens d'approbation, formulaire du pilote, API) ;
// - un lien de connexion reçu par mail (/?connexion=…), /connexion, ou une personne déjà connectée
//   sont redirigés vers le tableau de bord.
const MOTEUR = process.env.VERIFAC_MOTEUR ?? "https://api-docuflow.moussagaye.com";
const APPLICATION = process.env.VERIFAC_APPLICATION ?? "https://app.verifac.company";
const COOKIE_SESSION = "verifac_session"; // moteur/comptes.py

const nextConfig: NextConfig = {
  pageExtensions: ["ts", "tsx", "mdx"],
  // Vitesse (mesurée avec un tracé de performance, mobile lent) : captures servies en AVIF, plus légères.
  // inlineCss a été essayé puis retiré : le texte s'affichait avant la police, puis bougeait (LCP 2,3 s au lieu de 1,5 s).
  images: { formats: ["image/avif", "image/webp"], qualities: [70, 75] },
  async redirects() {
    return [
      // Une seule adresse pour Google : les variantes renvoient vers verifac.company (redirection permanente).
      // Les aperçus Vercel (verifac-site-xxxx.vercel.app) ne sont pas redirigés : Vercel les marque déjà « noindex ».
      ...["www.verifac.company", "verifac-site.vercel.app", "verifac-site-mosisgaye.vercel.app"].map((hote) => ({
        source: "/:chemin*",
        has: [{ type: "host" as const, value: hote }],
        destination: "https://verifac.company/:chemin*",
        permanent: true,
      })),
      // Le jeton du lien suit la redirection (la requête est conservée).
      { source: "/", has: [{ type: "query", key: "connexion" }], destination: `${APPLICATION}/`, permanent: false },
      { source: "/", has: [{ type: "cookie", key: COOKIE_SESSION }], destination: `${APPLICATION}/`, permanent: false },
      { source: "/connexion", destination: `${APPLICATION}/`, permanent: true },
    ];
  },
  async rewrites() {
    return {
      beforeFiles: [
        // La clé IndexNow, à la racine comme l'exige le protocole (app/indexnow/[cle]/route.ts).
        { source: "/:cle([0-9a-f]{32}).txt", destination: "/indexnow/:cle" },
        { source: "/api/:chemin*", destination: `${MOTEUR}/:chemin*` },
        { source: "/.well-known/:chemin*", destination: `${MOTEUR}/.well-known/:chemin*` },
      ],
      afterFiles: [],
      fallback: [],
    };
  },
  async headers() {
    return [
      {
        source: "/((?!api/).*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "SAMEORIGIN" },
        ],
      },
    ];
  },
};

// remark-gfm : les tableaux des guides. Avec Turbopack, le module se donne par son nom.
// rehype-slug : une ancre sur chaque titre, pour le sommaire des articles.
export default createMDX({ options: { remarkPlugins: [["remark-gfm"]], rehypePlugins: [["rehype-slug"]] } })(nextConfig);
