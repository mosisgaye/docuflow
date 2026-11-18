import Link from "next/link";
import { ARTICLES } from "@/contenu/ressources";
import { SITE } from "@/contenu/site";
import { Logo } from "./Icones";

/** Le pied de page : il relie toutes les pages du site entre elles. */
export function Pied() {
  return (
    <footer className="pied">
      <div className="conteneur pied__grille">
        <div className="pied__marque">
          <Link className="marque" href="/">
            <span className="marque__logo">
              <Logo />
            </span>
            Verifac
          </Link>
          <p>Les factures fournisseurs vérifiées avant le paiement.</p>
          <a href={`mailto:${SITE.support}`}>{SITE.support}</a>
        </div>
        <nav aria-label="Produit">
          <p>Produit</p>
          <Link href="/fonctionnalites">Fonctionnalités</Link>
          <Link href="/#controles">Contrôles</Link>
          <a href={SITE.demo}>Essayer la démo</a>
          <Link href="/#pilote">Programme pilote</Link>
          <Link href="/a-propos">À propos</Link>
          <Link href="/contact">Contact</Link>
          <a href={SITE.connexion}>Se connecter</a>
        </nav>
        <nav aria-label="Outils gratuits">
          <p>Outils gratuits</p>
          <Link href="/outils/verifier-iban">Vérifier un IBAN</Link>
          <Link href="/outils/verifier-numero-tva-intracommunautaire">Vérifier un numéro de TVA</Link>
          <Link href="/glossaire">Glossaire</Link>
          <Link href="/documentation">Documentation</Link>
          <Link href="/documentation/api">API</Link>
        </nav>
        <nav aria-label="Ressources">
          <p>Ressources</p>
          {ARTICLES.map((a) => (
            <Link key={a.slug} href={`/ressources/${a.slug}`}>
              {a.titreSeo.split(" : ")[0]}
            </Link>
          ))}
        </nav>
      </div>
      <div className="conteneur pied__bas">
        <span>© {new Date().getFullYear()} Verifac</span>
        <nav aria-label="Informations légales">
          <Link href="/mentions-legales">Mentions légales</Link>
          <Link href="/confidentialite">Confidentialité</Link>
        </nav>
      </div>
    </footer>
  );
}
