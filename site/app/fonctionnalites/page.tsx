import type { Metadata } from "next";
import { alternatives, description, titre } from "@/lib/seo";
import Link from "next/link";
import { SITE } from "@/contenu/site";
import { Appel } from "../composants/Appel";
import { FilAriane } from "../composants/FilAriane";
import { Questions } from "../composants/Questions";

export const metadata: Metadata = {
  title: titre("Fonctionnalités : valider les factures fournisseurs"),
  description: description("Réception, lecture IA et Factur-X, contrôles (IBAN, doublons, TVA, SIRET, commande), circuit d’approbation, Odoo, Claude et API : tout ce que fait Verifac."),
  alternates: alternatives("/fonctionnalites"),
};

const SOMMAIRE: [string, string][] = [
  ["reception", "Réception"],
  ["lecture", "Lecture"],
  ["controles", "Contrôles"],
  ["circuit", "Circuit d’approbation"],
  ["approbation", "Approbation par mail"],
  ["journal", "Journal"],
  ["odoo", "Odoo"],
  ["claude", "Claude et assistant"],
  ["api", "API et webhooks"],
  ["acces", "Comptes et droits"],
];

const BLOQUANTES = [
  "Information obligatoire absente (numéro, date, SIRET, total…)",
  "Aucune ligne, ou ligne mal calculée",
  "Total HT, TVA ou TTC mal calculé",
  "SIRET ou numéro de TVA intracommunautaire invalide, ou qui ne se correspondent pas",
  "IBAN invalide",
  "Échéance antérieure à la date de facture",
  "Facture déjà reçue (même fournisseur, même numéro)",
];

const AVERTISSEMENTS = [
  "IBAN jamais vu pour ce fournisseur, ou différent de celui enregistré",
  "Écart avec le bon de commande Odoo, ou achat sans commande",
  "Fournisseur inconnu dans Odoo",
  "Taux de TVA inhabituel",
  "Facture datée dans le futur",
];

const QUESTIONS = [
  {
    question: "Verifac remplace-t-il mon logiciel comptable ?",
    reponse: "Non. Verifac traite les factures fournisseurs avant la comptabilité : il les reçoit, les vérifie et les fait approuver. Les factures validées sont ensuite enregistrées dans Odoo, en brouillon.",
  },
  {
    question: "Verifac paie-t-il les factures ?",
    reponse: "Non. Verifac ne touche jamais à votre banque. Il s’assure qu’une facture est juste et approuvée avant que vous la payiez, avec vos outils habituels.",
  },
  {
    question: "Que se passe-t-il si une facture est fausse ?",
    reponse: "Une anomalie bloquante arrête la facture : elle passe « en anomalie » et n’entre pas dans le circuit. Un avertissement, comme un IBAN changé, la fait passer par l’approbation que vous avez prévue, ou l’arrête si votre circuit le demande.",
  },
  {
    question: "Faut-il un compte pour approuver ?",
    reponse: "Non. Chaque personne reçoit un lien personnel et signé par mail, et approuve ou rejette en un clic, sans se connecter. Elle peut aussi le faire dans Verifac si elle a un compte.",
  },
];

export default function Fonctionnalites() {
  return (
    <main className="texte">
      <div className="conteneur page-outil" style={{ maxWidth: "64rem" }}>
        <FilAriane etapes={[["Accueil", "/"], ["Fonctionnalités", "/fonctionnalites"]]} />
        <header className="page-outil__tete">
          <h1>Fonctionnalités de Verifac</h1>
          <p className="chapo">
            Un logiciel de traitement des factures fournisseurs pour les PME : chaque facture est reçue, lue, contrôlée et approuvée par les bonnes personnes avant le paiement.
          </p>
        </header>
        <nav className="pastilles" aria-label="Sur cette page">
          {SOMMAIRE.map(([ancre, nom]) => (
            <a key={ancre} href={`#${ancre}`}>
              {nom}
            </a>
          ))}
        </nav>

        <div className="prose fonctions">
          <section id="reception">
            <h2>Réception : toutes les factures au même endroit</h2>
            <ul>
              <li>
                <strong>Une adresse mail dédiée</strong> par installation : vos fournisseurs y envoient leurs factures, ou votre boîte habituelle les transfère
                automatiquement (Gmail, Outlook).
              </li>
              <li>
                <strong>Le dépôt</strong> : glissez un ou plusieurs fichiers dans Verifac.
              </li>
              <li>
                <strong>L’API</strong> : votre logiciel envoie les factures lui-même.
              </li>
            </ul>
            <p>Un fichier déjà reçu, même renommé, n’est pas traité deux fois.</p>
          </section>

          <section id="lecture">
            <h2>Lecture : Factur-X sans IA, le reste avec</h2>
            <ul>
              <li>
                <strong>Factur-X</strong> : les données sont lues directement dans le XML de la facture, sans erreur et sans IA. Voir{" "}
                <Link href="/ressources/factur-x">le format Factur-X</Link>.
              </li>
              <li>
                <strong>PDF, scans et photos</strong> : une IA relève le fournisseur, le SIRET, les lignes, les montants, la TVA, l’échéance et l’IBAN, en quelques secondes.
              </li>
            </ul>
            <p>Chaque information lue reste visible à côté du document, pour être vérifiée d’un coup d’œil.</p>
          </section>

          <section id="controles">
            <h2>Contrôles : chaque facture, sans exception</h2>
            <p>
              Les contrôles se rangent en deux familles. Les <strong>anomalies bloquantes</strong> arrêtent la facture tant que le problème n’est pas réglé. Les{" "}
              <strong>avertissements</strong> la laissent continuer, et votre circuit décide quoi en faire.
            </p>
            <div className="deux-colonnes">
              <div>
                <h3>Bloquantes</h3>
                <ul>
                  {BLOQUANTES.map((ligne) => (
                    <li key={ligne}>{ligne}</li>
                  ))}
                </ul>
              </div>
              <div>
                <h3>Avertissements</h3>
                <ul>
                  {AVERTISSEMENTS.map((ligne) => (
                    <li key={ligne}>{ligne}</li>
                  ))}
                </ul>
              </div>
            </div>
            <p>
              Le détail de chaque anomalie, et que faire, est dans le guide <Link href="/documentation/anomalies">Comprendre une anomalie</Link>. Pour faire ces contrôles à
              la main : <Link href="/outils/verifier-iban">vérifier un IBAN</Link>, <Link href="/outils/verifier-numero-tva-intracommunautaire">vérifier un numéro de TVA</Link>.
            </p>
          </section>

          <section id="circuit">
            <h2>Circuit d’approbation : vos règles, sans développeur</h2>
            <p>Le circuit se dessine comme un schéma, dans l’écran Workflow :</p>
            <ul>
              <li>
                <strong>Conditions</strong> sur le montant TTC ou HT, le fournisseur, le SIRET ou les anomalies trouvées, avec deux sorties : Oui et Non.
              </li>
              <li>
                <strong>Approbations</strong> par niveau : comptable, directeur financier, gérant.
              </li>
              <li>
                <strong>Blocages</strong> : arrêter une facture tant qu’un point n’est pas réglé, par exemple un IBAN changé.
              </li>
              <li>
                <strong>Relances</strong> automatiques : après 48 heures par défaut, 24 heures si l’échéance approche, 2 relances au plus.
              </li>
            </ul>
            <p>
              Vos changements restent dans un <strong>brouillon</strong> : vous le <strong>testez sur une facture réelle</strong> avant de le publier. Chaque publication crée
              une <strong>version</strong> signée de son auteur, et chaque facture garde la version qui l’a traitée.
            </p>
          </section>

          <section id="approbation">
            <h2>Approbation par mail, sans compte</h2>
            <p>
              Chaque personne d’un niveau reçoit un mail avec la facture et deux boutons : <strong>Approuver</strong> et <strong>Rejeter</strong>. Le lien est personnel,
              signé, et mène à une page de confirmation : c’est le clic qui décide, pas l’ouverture du lien. Un rejet demande toujours un motif.
            </p>
          </section>

          <section id="journal">
            <h2>Journal : chaque décision gardée</h2>
            <p>
              Réception, lecture, contrôles, approbations, rejets, export : tout est inscrit au journal de la facture, avec qui, quand, et sur quelle version de la facture.
              Le journal n’est jamais effacé. Si une facture est corrigée après une approbation, les accords déjà donnés ne valent plus.
            </p>
          </section>

          <section id="odoo">
            <h2>Odoo : comparer, puis enregistrer</h2>
            <ul>
              <li>Chaque facture est comparée à Odoo : le fournisseur existe-t-il ? Y a-t-il un bon de commande, et le prix correspond-il ? L’IBAN est-il celui enregistré ?</li>
              <li>
                La facture validée est enregistrée dans Odoo comme <strong>facture fournisseur en brouillon</strong>, avec son PDF.
              </li>
            </ul>
            <p>
              Voir <Link href="/ressources/odoo-factures-fournisseurs">Odoo et factures fournisseurs</Link>.
            </p>
          </section>

          <section id="claude">
            <h2>Claude et l’assistant : poser vos questions en français</h2>
            <ul>
              <li>
                <strong>Le connecteur Claude</strong> : branchez Verifac à Claude et demandez « Qu’est-ce qui attend mon accord ? ». Claude lit seulement : il ne peut ni
                approuver, ni rejeter, ni modifier.
              </li>
              <li>
                <strong>L’assistant intégré</strong> explique une anomalie, prépare un mail au fournisseur, ou modifie le brouillon du circuit à votre demande. Il ne publie
                jamais : la décision reste la vôtre.
              </li>
            </ul>
          </section>

          <section id="api">
            <h2>API et webhooks</h2>
            <p>
              Clés d’API à droits choisis, dépôt et lecture des factures, et messages envoyés à votre logiciel à chaque étape (facture reçue, validée, rejetée…), signés en
              HMAC-SHA256. Voir <Link href="/documentation/api">la documentation de l’API</Link>.
            </p>
          </section>

          <section id="acces">
            <h2>Comptes et droits</h2>
            <table>
              <thead>
                <tr>
                  <th>Rôle</th>
                  <th>Ce qu’il peut faire</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Administrateur</td>
                  <td>Tout, plus l’équipe, les connecteurs, les clés d’API et la publication du circuit.</td>
                </tr>
                <tr>
                  <td>Membre</td>
                  <td>Déposer, traiter et exporter les factures, préparer le circuit, utiliser l’assistant.</td>
                </tr>
                <tr>
                  <td>Approbateur</td>
                  <td>Voir seulement les factures où c’est son tour, et les approuver ou les rejeter.</td>
                </tr>
                <tr>
                  <td>Lecture seule</td>
                  <td>Tout voir, rien changer.</td>
                </tr>
              </tbody>
            </table>
            <p>Connexion sans mot de passe, par lien ou code reçu par mail, à usage unique.</p>
          </section>
        </div>

        <Questions liste={QUESTIONS} />
        <Appel titre="Voyez tout cela en un clic." texte={`La démo contient une fraude à l’IBAN, des doublons et un circuit à trois niveaux, sur ${SITE.demo.replace("https://", "")}.`} />
      </div>
    </main>
  );
}
