import type { Metadata } from "next";
import { alternatives, description, titre } from "@/lib/seo";
import Link from "next/link";
import { Appel } from "../../composants/Appel";
import { DonneesStructurees } from "../../composants/DonneesStructurees";
import { FilAriane } from "../../composants/FilAriane";
import { Questions } from "../../composants/Questions";
import { graphe } from "@/lib/schema";
import { SITE } from "@/contenu/site";
import { VerificateurIban } from "../VerificateurIban";

const TITRE = "Vérifier un IBAN gratuitement";
const DESCRIPTION = "Vérifiez un IBAN en un instant : format, longueur et clé de contrôle, pour la France et l’Europe. Gratuit, sans inscription, rien n’est envoyé.";

export const metadata: Metadata = {
  title: titre("Vérifier un IBAN : outil gratuit de contrôle"),
  description: description(DESCRIPTION),
  alternates: alternatives("/outils/verifier-iban"),
  openGraph: { title: TITRE, description: DESCRIPTION, url: "/outils/verifier-iban" },
};

const QUESTIONS = [
  {
    question: "Comment vérifier qu’un IBAN est valide ?",
    reponse:
      "Un IBAN contient une clé de contrôle : en déplaçant les quatre premiers caractères à la fin et en remplaçant les lettres par des nombres, le reste de la division par 97 doit valoir 1. L’outil ci-dessus fait ce calcul, et vérifie aussi la longueur attendue pour le pays.",
  },
  {
    question: "Combien de caractères compte un IBAN français ?",
    reponse: "27 caractères : FR, deux chiffres de clé, puis 23 caractères qui reprennent le RIB (code banque, code guichet, numéro de compte et clé RIB).",
  },
  {
    question: "Un IBAN valide est-il forcément sûr ?",
    reponse:
      "Non. L’outil prouve que le numéro est bien formé, pas qu’il appartient à votre fournisseur. Les fraudeurs au faux RIB donnent un vrai IBAN : le leur. Confirmez toujours un changement de coordonnées par téléphone, au numéro que vous connaissez déjà.",
  },
  {
    question: "Peut-on savoir à qui appartient un IBAN ?",
    reponse:
      "Pas avec un outil public. Depuis le 9 octobre 2025, les banques de la zone euro vérifient le nom du bénéficiaire avant un virement : si votre banque signale que le nom ne correspond pas, arrêtez-vous et vérifiez auprès du fournisseur.",
  },
  {
    question: "Mon IBAN est-il envoyé quelque part ?",
    reponse: "Non. Le calcul se fait entièrement dans votre navigateur. Rien n’est transmis ni enregistré.",
  },
];

export default function PageVerifierIban() {
  return (
    <main className="texte">
      <div className="conteneur page-outil">
        <FilAriane etapes={[["Accueil", "/"], ["Outils gratuits", "/outils"], ["Vérifier un IBAN", "/outils/verifier-iban"]]} />
        <header className="page-outil__tete">
          <h1>Vérifier un IBAN</h1>
          <p className="chapo">Collez un IBAN : l’outil contrôle son format, sa longueur et sa clé de contrôle. Gratuit, sans inscription, et rien ne quitte votre navigateur.</p>
        </header>
        <VerificateurIban />

        <div className="prose page-outil__texte">
          <h2>Ce que l’outil vérifie</h2>
          <ul>
            <li>
              <strong>Le pays</strong> : les deux premières lettres (FR pour la France).
            </li>
            <li>
              <strong>La longueur</strong> : chaque pays a la sienne, 27 caractères pour la France, 22 pour l’Allemagne, 16 pour la Belgique.
            </li>
            <li>
              <strong>La clé de contrôle</strong> : les deux chiffres après le pays. Une seule faute de frappe la rend fausse.
            </li>
          </ul>

          <h2>Lire un IBAN français</h2>
          <table>
            <thead>
              <tr>
                <th>Partie</th>
                <th>Exemple</th>
                <th>Ce que c’est</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Pays et clé</td>
                <td>
                  <code>FR76</code>
                </td>
                <td>Le code du pays, puis la clé de contrôle de l’IBAN.</td>
              </tr>
              <tr>
                <td>Code banque</td>
                <td>
                  <code>30006</code>
                </td>
                <td>L’établissement qui tient le compte.</td>
              </tr>
              <tr>
                <td>Code guichet</td>
                <td>
                  <code>00001</code>
                </td>
                <td>L’agence.</td>
              </tr>
              <tr>
                <td>Numéro de compte</td>
                <td>
                  <code>12345678901</code>
                </td>
                <td>11 caractères.</td>
              </tr>
              <tr>
                <td>Clé RIB</td>
                <td>
                  <code>89</code>
                </td>
                <td>La clé de contrôle de l’ancien RIB.</td>
              </tr>
            </tbody>
          </table>

          <h2>Un IBAN valide peut cacher une fraude</h2>
          <p>
            La fraude au faux RIB ne repose pas sur un IBAN mal formé. Un mail imite votre fournisseur, annonce un « changement de banque » et donne un IBAN parfaitement valide :
            celui du fraudeur. Les signes qui doivent alerter : un changement annoncé par mail, une urgence inhabituelle, un compte à l’étranger, une adresse d’expéditeur légèrement
            différente. Pour aller plus loin, lisez notre guide <Link href="/ressources/faux-rib-fraude-iban">Faux RIB et fraude à l’IBAN</Link>.
          </p>
        </div>

        <Questions liste={QUESTIONS} />
        <Appel
          titre="Verifac vérifie l’IBAN de chaque facture fournisseur."
          texte="Il compare l’IBAN de chaque facture aux coordonnées bancaires enregistrées pour ce fournisseur dans votre comptabilité, et retient la facture au moindre changement, avant tout paiement."
        />
      </div>
      <DonneesStructurees
        donnees={graphe({
          "@type": "WebApplication",
          name: "Vérificateur d’IBAN",
          url: `${SITE.adresse}/outils/verifier-iban`,
          applicationCategory: "FinanceApplication",
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
