import type { Metadata } from "next";
import { alternatives, description, titre } from "@/lib/seo";
import Link from "next/link";
import { SITE } from "@/contenu/site";
import { ACompleter } from "../composants/ACompleter";
import { Appel } from "../composants/Appel";
import { FilAriane } from "../composants/FilAriane";

export const metadata: Metadata = {
  title: titre("À propos : qui fait Verifac"),
  description: description("Qui conçoit Verifac, pourquoi, et selon quels principes : factures vérifiées avant le paiement, journal jamais effacé, une IA qui ne décide pas."),
  alternates: alternatives("/a-propos"),
};

const PRINCIPES = [
  { titre: "Rien n’est payé sans être vérifié", texte: "Chaque facture passe les mêmes contrôles, sans exception, avant d’entrer dans le circuit d’approbation." },
  { titre: "Une personne décide toujours", texte: "L’IA lit les factures et aide à comprendre une anomalie. Elle n’approuve jamais, ne paie jamais, ne publie jamais un circuit." },
  { titre: "Tout laisse une trace", texte: "Chaque décision est inscrite au journal de la facture : qui, quand, sur quelle version. Le journal n’est jamais effacé." },
  { titre: "Vos données restent les vôtres", texte: "Chaque client a son installation et sa base. À la fin d’un contrat, les données sont rendues." },
];

export default function APropos() {
  return (
    <main className="texte">
      <div className="conteneur article">
        <FilAriane etapes={[["Accueil", "/"], ["À propos", "/a-propos"]]} />
        <header className="article__tete">
          <h1>Qui fait Verifac</h1>
        </header>
        <div className="prose">
          <p>
            Verifac est conçu et développé par <strong>Moussa Gaye</strong>. <ACompleter>deux ou trois phrases : votre parcours, votre expérience, pourquoi vous
            êtes légitime sur les factures et l’automatisation</ACompleter>
          </p>

          <h2>Pourquoi Verifac existe</h2>
          <p>
            Dans une PME, une facture fournisseur passe par plusieurs mains avant d’être payée, et personne n’a le temps de tout vérifier. C’est là que passent les doublons,
            les erreurs de montant et les fraudes au faux RIB. Verifac fait ces vérifications sur chaque facture, et laisse la décision aux bonnes personnes.
          </p>

          <h2>Nos principes</h2>
          <ul>
            {PRINCIPES.map((principe) => (
              <li key={principe.titre}>
                <strong>{principe.titre}.</strong> {principe.texte}
              </li>
            ))}
          </ul>

          <h2>Où en est Verifac</h2>
          <p>
            Verifac est en <strong>programme pilote</strong> : cinq entreprises l’utilisent gratuitement pendant deux mois, sur leurs vraies factures, et nous aident à
            l’améliorer. Vous pouvez <a href={SITE.demo}>l’essayer en un clic</a> sur de fausses factures, ou <Link href="/#pilote">demander une place</Link>.
          </p>

          <h2>Nous contacter</h2>
          <ul>
            <li>
              Par mail : <a href={`mailto:${SITE.support}`}>{SITE.support}</a>
            </li>
            <li>
              Sur LinkedIn : <ACompleter>adresse de votre profil LinkedIn</ACompleter>
            </li>
          </ul>
        </div>
        <Appel titre="Voyez Verifac sur de vraies situations." texte="La démo contient une fraude à l’IBAN, des doublons et un circuit d’approbation à trois niveaux." />
      </div>
    </main>
  );
}
