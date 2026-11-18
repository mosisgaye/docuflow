import { ImageResponse } from "next/og";
import { SYMBOLE } from "@/lib/logo";

export const alt = "Verifac : vos factures fournisseurs, vérifiées avant d’être payées.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

/** L'image affichée quand on partage verifac.company (LinkedIn, messageries). */
export default function ImagePartage() {
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", justifyContent: "space-between", padding: "72px 80px", background: "#0a3527", color: "#ffffff" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 18, fontSize: 36, fontWeight: 700 }}>
          <div style={{ width: 64, height: 64, borderRadius: 15, background: "#0b7f57", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <svg width="42" height="42" viewBox="0 0 48 48" fill="none" stroke="#ffffff" strokeWidth="4.8" strokeLinecap="round" strokeLinejoin="round">
              <path d={SYMBOLE.document} />
              <path d={SYMBOLE.pli} />
              <path d={SYMBOLE.coche} strokeWidth="5.4" />
            </svg>
          </div>
          Verifac
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
          <div style={{ fontSize: 76, fontWeight: 700, lineHeight: 1.05, letterSpacing: -2, maxWidth: 960 }}>Vos factures fournisseurs, vérifiées avant d’être payées.</div>
          <div style={{ fontSize: 30, color: "#a9cdbd" }}>IBAN suspects, doublons, erreurs de montant : arrêtés avant le paiement.</div>
        </div>
      </div>
    ),
    size,
  );
}
