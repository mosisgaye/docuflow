"use client";

import { track } from "@vercel/analytics";
import { useEffect } from "react";
import { SITE } from "@/contenu/site";

/** Compte les clics qui comptent (essai de la démo, connexion), sans donnée personnelle : la page d'origine seulement. */
export function Conversions() {
  useEffect(() => {
    const surClic = (evenement: MouseEvent) => {
      const lien = (evenement.target as Element | null)?.closest?.("a");
      if (!lien) return;
      const page = window.location.pathname;
      if (lien.href.startsWith(SITE.demo)) track("essai_demo", { page });
      else if (lien.href.startsWith(SITE.application)) track("connexion", { page });
    };
    document.addEventListener("click", surClic);
    return () => document.removeEventListener("click", surClic);
  }, []);
  return null;
}
