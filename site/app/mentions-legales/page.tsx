import Link from "next/link";
import type { Metadata } from "next";
import { alternatives, description, titre } from "@/lib/seo";
import { SITE } from "@/contenu/site";
import { ACompleter } from "../composants/ACompleter";

export const metadata: Metadata = {
  title: titre("Mentions légales"),
  description: description("Mentions légales du site verifac.company : éditeur, directeur de la publication, hébergement, propriété intellectuelle et données personnelles."),
  alternates: alternatives("/mentions-legales"),
};

export default function MentionsLegales() {
  return (
    <main className="texte">
      <div className="conteneur" style={{ maxWidth: "46rem" }}>
        <div className="prose">
          <h1>Mentions légales</h1>

          <h2>Éditeur du site</h2>
          <p>
            Le site verifac.company est édité par <ACompleter>nom et prénom, ou raison sociale</ACompleter>, <ACompleter>statut : entrepreneur individuel, SASU…</ACompleter>.
          </p>
          <ul>
            <li>
              SIRET : <ACompleter>numéro SIRET</ACompleter>
            </li>
            <li>
              Adresse : <ACompleter>adresse postale</ACompleter>
            </li>
            <li>
              Numéro de TVA intracommunautaire : <ACompleter>numéro, ou « TVA non applicable, art. 293 B du CGI »</ACompleter>
            </li>
            <li>
              Contact : <a href={`mailto:${SITE.support}`}>{SITE.support}</a>
            </li>
          </ul>
          <p>
            Directeur de la publication : <ACompleter>nom et prénom</ACompleter>.
          </p>

          <h2>Hébergement</h2>
          <p>
            Le site est hébergé par Vercel Inc., 440 N Barranca Ave #4133, Covina, CA 91723, États-Unis (vercel.com).
          </p>
          <p>
            Le service Verifac et ses données sont hébergés par <ACompleter>nom, adresse et pays de l’hébergeur du serveur</ACompleter>.
          </p>

          <h2>Propriété intellectuelle</h2>
          <p>
            Les textes, captures d’écran et éléments graphiques de ce site appartiennent à leur éditeur. Toute reproduction sans autorisation est interdite. Les noms Odoo, Claude et
            les autres marques citées appartiennent à leurs propriétaires respectifs.
          </p>

          <h2>Données personnelles</h2>
          <p>
            Voir la page <Link href="/confidentialite">Confidentialité</Link>.
          </p>
        </div>
      </div>
    </main>
  );
}
