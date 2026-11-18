import { Analytics } from "@vercel/analytics/next";
import { SpeedInsights } from "@vercel/speed-insights/next";
import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import { SITE } from "@/contenu/site";
import { Conversions } from "./composants/Conversions";
import { DonneesStructurees } from "./composants/DonneesStructurees";
import { Entete } from "./composants/Entete";
import { ORGANISATION, SITE_WEB, graphe } from "@/lib/schema";
import { LANGUE, SUFFIXE_TITRE, alternatives } from "@/lib/seo";
import { Pied } from "./composants/Pied";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });

export const metadata: Metadata = {
  metadataBase: new URL(SITE.adresse),
  title: { default: "Verifac, factures fournisseurs vérifiées avant le paiement", template: `%s${SUFFIXE_TITRE}` },
  description: SITE.description,
  openGraph: { type: "website", locale: "fr_FR", siteName: "Verifac", url: SITE.adresse },
  twitter: { card: "summary_large_image" },
  robots: { index: true, follow: true, "max-image-preview": "large", "max-snippet": -1 },
  formatDetection: { telephone: false },
  alternates: { ...alternatives("/"), types: { "application/rss+xml": [{ url: "/ressources/rss.xml", title: "Ressources Verifac" }] } },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f4f5f4" },
    { media: "(prefers-color-scheme: dark)", color: "#111111" },
  ],
};

export default function Mise({ children }: { children: React.ReactNode }) {
  return (
    <html lang={LANGUE} className={inter.variable}>
      <body>
        <DonneesStructurees donnees={graphe(ORGANISATION, SITE_WEB)} />
        <Entete />
        {children}
        <Pied />
        {/* Mesure d'audience et vitesse réelle des visiteurs, par Vercel : sans cookie. */}
        <Analytics />
        <SpeedInsights />
        <Conversions />
      </body>
    </html>
  );
}
