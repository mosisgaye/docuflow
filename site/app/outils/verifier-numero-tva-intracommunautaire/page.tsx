import type { Metadata } from "next";
import { alternatives, description, titre } from "@/lib/seo";
import Link from "next/link";
import { Appel } from "../../composants/Appel";
import { DonneesStructurees } from "../../composants/DonneesStructurees";
import { FilAriane } from "../../composants/FilAriane";
import { Questions } from "../../composants/Questions";
import { graphe } from "@/lib/schema";
import { SITE } from "@/contenu/site";
import { VerificateurTva } from "../VerificateurTva";

const CHEMIN = "/outils/verifier-numero-tva-intracommunautaire";
const DESCRIPTION = "Vérifiez un numéro de TVA intracommunautaire français, un SIREN ou un SIRET, et calculez le numéro de TVA à partir du SIREN. Gratuit et instantané.";

export const metadata: Metadata = {
  title: titre("Vérifier un numéro de TVA intracommunautaire"),
  description: description(DESCRIPTION),
  alternates: alternatives(CHEMIN),
  openGraph: { title: "Vérifier un numéro de TVA intracommunautaire", description: DESCRIPTION, url: CHEMIN },
};

const QUESTIONS = [
  {
    question: "Comment est formé le numéro de TVA intracommunautaire français ?",
    reponse:
      "Il s’écrit FR, suivi d’une clé de deux chiffres, suivie des 9 chiffres du SIREN : 13 caractères en tout. La clé se calcule ainsi : (12 + 3 × (SIREN modulo 97)) modulo 97.",
  },
  {
    question: "Comment calculer le numéro de TVA à partir du SIREN ?",
    reponse: "Saisissez le SIREN ou le SIRET dans l’outil : il calcule la clé et donne le numéro de TVA complet. Par exemple, le SIREN 732 829 320 donne FR44 732 829 320.",
  },
  {
    question: "Quelle différence entre SIREN et SIRET ?",
    reponse:
      "Le SIREN (9 chiffres) identifie l’entreprise. Le SIRET (14 chiffres) identifie un établissement : ce sont les 9 chiffres du SIREN suivis de 5 chiffres propres à l’établissement. Les deux ont une clé de contrôle (algorithme de Luhn).",
  },
  {
    question: "Un numéro valide prouve-t-il que l’entreprise existe ?",
    reponse:
      "Non : l’outil vérifie le format et les clés de contrôle. Pour savoir si l’entreprise existe et si son numéro de TVA est actif, consultez l’annuaire des entreprises de l’État ou le service VIES de la Commission européenne.",
  },
  {
    question: "Pourquoi vérifier le numéro de TVA d’un fournisseur ?",
    reponse:
      "Une facture doit porter le numéro de TVA du vendeur. Un numéro faux peut signaler une erreur, une fausse facture, ou une TVA que vous ne pourrez pas déduire en cas de contrôle.",
  },
];

export default function PageVerifierTva() {
  return (
    <main className="texte">
      <div className="conteneur page-outil">
        <FilAriane etapes={[["Accueil", "/"], ["Outils gratuits", "/outils"], ["Vérifier un numéro de TVA", CHEMIN]]} />
        <header className="page-outil__tete">
          <h1>Vérifier un numéro de TVA intracommunautaire</h1>
          <p className="chapo">
            Collez un numéro de TVA français, un SIREN ou un SIRET. L’outil vérifie les clés de contrôle et calcule le numéro de TVA. Gratuit, sans inscription.
          </p>
        </header>
        <VerificateurTva />

        <div className="prose page-outil__texte">
          <h2>Les trois numéros d’une entreprise française</h2>
          <table>
            <thead>
              <tr>
                <th>Numéro</th>
                <th>Format</th>
                <th>Contrôle</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>SIREN</td>
                <td>9 chiffres</td>
                <td>Clé de Luhn</td>
              </tr>
              <tr>
                <td>SIRET</td>
                <td>SIREN + 5 chiffres (14 chiffres)</td>
                <td>Clé de Luhn sur les 14 chiffres</td>
              </tr>
              <tr>
                <td>TVA intracommunautaire</td>
                <td>FR + clé + SIREN (13 caractères)</td>
                <td>Clé = (12 + 3 × (SIREN mod 97)) mod 97</td>
              </tr>
            </tbody>
          </table>

          <h2>Sur une facture fournisseur</h2>
          <p>
            Le SIRET et le numéro de TVA du vendeur font partie des <Link href="/ressources/mentions-obligatoires-facture">mentions obligatoires d’une facture</Link>. Une
            clé fausse est souvent une faute de frappe, parfois le signe d’une fausse facture. Un numéro de TVA qui ne correspond pas au SIREN de la même facture doit toujours
            être vérifié avant le paiement.
          </p>
        </div>

        <Questions liste={QUESTIONS} />
        <Appel
          titre="Verifac contrôle le SIRET et la TVA de chaque facture."
          texte="Il vérifie les clés, s’assure que le numéro de TVA correspond bien au SIRET, et arrête la facture si quelque chose ne va pas."
        />
      </div>
      <DonneesStructurees
        donnees={graphe({
          "@type": "WebApplication",
          name: "Vérificateur de numéro de TVA intracommunautaire",
          url: `${SITE.adresse}${CHEMIN}`,
          applicationCategory: "BusinessApplication",
          operatingSystem: "Web",
          inLanguage: "fr-FR",
          isAccessibleForFree: true,
          offers: { "@type": "Offer", price: "0", priceCurrency: "EUR" },
          publisher: { "@id": `${SITE.adresse}/#organisation` },
        })}
      />
    </main>
  );
}
