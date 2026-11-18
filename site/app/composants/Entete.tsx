import Link from "next/link";
import { SITE } from "@/contenu/site";
import { Logo } from "./Icones";

/** Le haut de page, fixe, avec un trait fin qui le sépare du contenu. */
export function Entete() {
  return (
    <header className="entete">
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
