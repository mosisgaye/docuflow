import { ImageResponse } from "next/og";
import { SYMBOLE } from "@/lib/logo";

export const size = { width: 180, height: 180 };
export const contentType = "image/png";

/** L'icône quand on ajoute le site à l'écran d'accueil d'un iPhone. */
export default function IconeApple() {
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", background: "#0b7f57" }}>
        <svg width="118" height="118" viewBox="0 0 48 48" fill="none" stroke="#ffffff" strokeWidth="4.8" strokeLinecap="round" strokeLinejoin="round">
          <path d={SYMBOLE.document} />
          <path d={SYMBOLE.pli} />
          <path d={SYMBOLE.coche} strokeWidth="5.4" />
        </svg>
      </div>
    ),
    size,
  );
}
