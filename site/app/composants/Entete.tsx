"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { SITE } from "@/contenu/site";
import { Logo } from "./Icones";

/** Le haut de page, fixe : il prend un trait dès qu'on défile. */
export function Entete() {
  const [defile, setDefile] = useState(false);
  useEffect(() => {
    const surDefilement = () => setDefile(window.scrollY > 8);
    surDefilement();
    window.addEventListener("scroll", surDefilement, { passive: true });
    return () => window.removeEventListener("scroll", surDefilement);
  }, []);

  return (
    <header className={`entete${defile ? " defile" : ""}`}>
      <div className="conteneur entete__ligne">
        <Link className="marque" href="/">
          <span className="marque__logo">
            <Logo />
          </span>
          Verifac
        </Link>
        <nav className="navigation" aria-label="Sections">
          <Link href="/fonctionnalites">Fonctionnalités</Link>
          <Link href="/outils">Outils gratuits</Link>
          <Link href="/ressources">Ressources</Link>
          <Link href="/documentation">Documentation</Link>
          <Link href="/#pilote">Programme pilote</Link>
        </nav>
        <div className="entete__actions">
          {/* Le tableau de bord est sur app.verifac.company : un lien simple, pas une page de ce site. */}
          <a className="lien-discret" href={SITE.connexion}>
            Se connecter
          </a>
          <a className="bouton bouton--plein" href={SITE.demo}>
            Essayer la démo
          </a>
        </div>
      </div>
    </header>
  );
}
