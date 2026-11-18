import { getImageProps } from "next/image";
import Link from "next/link";
import { GUIDES } from "@/contenu/guides";
import { SITE } from "@/contenu/site";
import captureClaire from "@/public/captures/verifac-clair.jpg";
import captureSombre from "@/public/captures/verifac-sombre.jpg";
import { Controles } from "./composants/Controles";
import { FormulairePilote } from "./composants/FormulairePilote";
import { Coche, IconeDeGuide } from "./composants/Icones";
import { DonneesStructurees } from "./composants/DonneesStructurees";
import { Questions } from "./composants/Questions";
import { Videos } from "./composants/Videos";
import { LOGICIEL, graphe } from "@/lib/schema";
import { VIDEOS } from "@/contenu/videos";

const ETAPES = [
  { titre: "Réception", texte: "Par une adresse mail dédiée, un dépôt ou l’API. PDF, scan, photo ou Factur-X." },
  { titre: "Lecture", texte: "L’IA relève fournisseur, montants, échéance et IBAN en quelques secondes." },
  { titre: "Contrôles", texte: "Calculs, TVA, SIRET, doublons, IBAN, bon de commande : chaque règle est vérifiée." },
  { titre: "Approbation", texte: "Les bonnes personnes approuvent, par mail ou dans Verifac, selon vos règles." },
  { titre: "Comptabilité", texte: "La facture validée part dans Odoo ou votre logiciel, avec son journal complet." },
];

const CONTROLES: { titre: string; texte: string; issue: string; grave: boolean }[] = [
  { titre: "IBAN changé", texte: "Un fournisseur connu envoie soudain d’autres coordonnées bancaires. C’est la fraude la plus courante contre les PME.", issue: "Retenue pour vérification", grave: true },
  { titre: "Facture en double", texte: "La même facture arrive deux fois, par mail puis par dépôt, ou sous un autre nom de fichier.", issue: "Arrêtée", grave: true },
  { titre: "Erreur de calcul", texte: "Les lignes, le hors-taxe, la TVA et le total ne tombent pas juste.", issue: "Arrêtée", grave: true },
  { titre: "Écart avec la commande", texte: "Le prix facturé dépasse celui du bon de commande dans Odoo, ou il n’y a pas de commande.", issue: "À vérifier", grave: false },
  { titre: "Fournisseur inconnu", texte: "Un SIRET jamais vu, ou invalide, mérite un regard avant de payer.", issue: "À vérifier", grave: false },
];

const PILOTE = [
  { titre: "Installation faite pour vous", texte: "Adresse de réception, circuit d’approbation, branchement à votre comptabilité." },
  { titre: "Deux mois d’utilisation complète", texte: "Toutes les fonctions, sur vos factures réelles." },
  { titre: "Un interlocuteur direct", texte: "Un point chaque semaine, et une réponse sous un jour ouvré." },
  { titre: "Aucun engagement", texte: "À la fin, vous continuez ou vous arrêtez. Vos données vous sont rendues." },
];

const QUESTIONS = [
  {
    question: "Faut-il changer de logiciel comptable ?",
    reponse: "Non. Verifac se place avant votre comptabilité : il reçoit, vérifie et fait approuver. Les factures validées partent ensuite dans Odoo, ou dans un fichier pour votre logiciel actuel.",
  },
  {
    question: "Où sont gardées mes factures ?",
    reponse: "Sur un serveur dédié à votre installation, avec une base séparée. Les factures et leur journal ne sont jamais supprimés : ce sont des preuves.",
  },
  {
    question: "L’intelligence artificielle voit-elle mes données ?",
    reponse: "L’IA lit le contenu de la facture pour en relever les informations, rien d’autre. Les factures Factur-X sont lues sans IA. Une IA hébergée en Europe est prévue pour les entreprises qui l’exigent.",
  },
  {
    question: "Qui peut approuver, et comment ?",
    reponse: "Vous décidez des niveaux et des seuils. Chaque personne approuve depuis un lien reçu par mail ou dans Verifac. Tout est inscrit au journal : qui, quand, et sur quelle version de la facture.",
  },
  {
    question: "Que se passe-t-il à la fin du pilote ?",
    reponse: "Vous choisissez librement. Si vous continuez, nous vous proposons une mise en place et un forfait mensuel selon votre volume. Sinon, nous vous rendons vos données et fermons l’installation.",
  },
];

/** La capture de Verifac, claire ou sombre selon le thème de l'ordinateur : une seule image téléchargée. */
function CaptureVerifac() {
  const commun = { alt: "L’accueil de Verifac : factures à approuver, anomalies à régler, échéances proches et parcours d’une facture.", sizes: "(max-width: 1440px) 100vw, 1376px", quality: 70 };
  const sombre = getImageProps({ ...commun, src: captureSombre }).props;
  const claire = getImageProps({ ...commun, src: captureClaire, priority: true }).props;
  return (
    <picture>
      <source media="(prefers-color-scheme: dark)" srcSet={sombre.srcSet} sizes={sombre.sizes} />
      <img {...claire} alt={commun.alt} />
    </picture>
  );
}

export default function Accueil() {
  return (
    <main>
      <DonneesStructurees donnees={graphe(LOGICIEL)} />
      {VIDEOS.length > 0 && (
        <DonneesStructurees
          donnees={graphe(
            ...VIDEOS.map((v) => ({
              "@type": "VideoObject",
              name: v.titre,
              description: v.resume,
              thumbnailUrl: `${SITE.adresse}${v.vignette}`,
              contentUrl: `${SITE.adresse}${v.source}`,
              uploadDate: v.publiee,
              duration: `PT${v.secondes}S`,
              inLanguage: "fr-FR",
            })),
          )}
        />
      )}
      <section className="ouverture">
        <div className="conteneur ouverture__texte">
          <a className="annonce" href="#pilote">
            <b>Programme pilote</b> 5 places, deux mois offerts
          </a>
          <h1>Vos factures fournisseurs, vérifiées avant d’être payées.</h1>
          <p className="chapo">
            Verifac lit chaque facture qui arrive, arrête les doublons et les erreurs de montant, retient les IBAN suspects, puis la fait approuver par les bonnes personnes.
            Votre comptabilité ne reçoit que ce qui est juste.
          </p>
          <div className="ouverture__actions">
            <a className="bouton bouton--plein" href={SITE.demo}>
              Essayer la démo
            </a>
            <a className="bouton bouton--trait" href="#pilote">
              Rejoindre le programme pilote
            </a>
          </div>
          <p className="ouverture__note">Démo en un clic, sans adresse à donner.</p>
        </div>

        <div className="conteneur scene">
          <figure className="cadre">
            <div className="cadre__barre" aria-hidden="true">
              <i />
              <i />
              <i />
              <span>demo.verifac.company</span>
            </div>
            <CaptureVerifac />
          </figure>
          <Controles />
        </div>
      </section>

      <section className="reforme" aria-label="Facture électronique">
        <div className="conteneur reforme__ligne">
          <p>
            <strong>La facture électronique devient obligatoire.</strong> Verifac lit déjà le format <Link href="/ressources/factur-x">Factur-X</Link>, sans IA, et vos PDF et scans à côté.{" "}
            <Link href="/ressources/facturation-electronique-2026">Le calendrier expliqué</Link>.
          </p>
          <div className="date">
            <b>Sept. 2026</b>
            <span>Toutes les entreprises doivent pouvoir recevoir des factures électroniques.</span>
          </div>
          <div className="date">
            <b>Sept. 2027</b>
            <span>Les PME et micro-entreprises doivent aussi en émettre.</span>
          </div>
        </div>
      </section>

      <section className="section" id="fonctionnement">
        <div className="conteneur">
          <div className="section__tete">
            <h2>De la boîte mail à la comptabilité, sans ressaisie.</h2>
            <p className="chapo">
              Chaque facture suit le même chemin. Vous voyez à tout moment où elle en est, et qui doit agir. <Link href="/fonctionnalites">Toutes les fonctionnalités</Link>.
            </p>
          </div>
          <div className="parcours">
            {ETAPES.map((etape) => (
              <div className="etape" key={etape.titre}>
                <h3>{etape.titre}</h3>
                <p>{etape.texte}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="section" id="controles" style={{ paddingTop: 0 }}>
        <div className="conteneur">
          <div className="section__tete">
            <h2>Ce que Verifac arrête avant le paiement.</h2>
            <p className="chapo">
              Les erreurs qui coûtent cher ne se voient pas à l’œil nu. Verifac les cherche sur chaque facture, sans exception. Faites l’essai vous-même avec nos outils gratuits :{" "}
              <Link href="/outils/verifier-iban">vérifier un IBAN</Link> et <Link href="/outils/verifier-numero-tva-intracommunautaire">vérifier un numéro de TVA</Link>.
            </p>
          </div>
          <div className="registre">
            {CONTROLES.map((controle) => (
              <div className="registre__ligne" key={controle.titre}>
                <h3>{controle.titre}</h3>
                <p>{controle.texte}</p>
                <span className={`issue ${controle.grave ? "issue--bloque" : "issue--signale"}`}>{controle.issue}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <Videos />

      <section className="section" style={{ paddingTop: 0 }}>
        <div className="conteneur duo">
          <div className="panneau">
            <h3 style={{ fontSize: "1.375rem" }}>Un circuit d’approbation à votre image.</h3>
            <p>Vous dessinez les règles : qui approuve, à partir de quel montant, quand relancer. Chacun reçoit seulement ce qui le concerne.</p>
            <div className="circuit" aria-label="Exemple de circuit">
              <div className="niveau">
                <div>
                  Comptable
                  <br />
                  <span>Toutes les factures</span>
                </div>
                <b>Approuvée</b>
              </div>
              <div className="liaison" />
              <div className="niveau">
                <div>
                  Directeur financier
                  <br />
                  <span>Au-delà de 1 000 €, ou si l’IBAN a changé</span>
                </div>
                <b>Approuvée</b>
              </div>
              <div className="liaison" />
              <div className="niveau attente">
                <div>
                  Gérant
                  <br />
                  <span>Au-delà de 5 000 €</span>
                </div>
                <b>En attente</b>
              </div>
            </div>
          </div>
          <div className="panneau">
            <h3 style={{ fontSize: "1.375rem" }}>Vos factures, aussi dans Claude.</h3>
            <p>Branchez Verifac à Claude et posez vos questions en français. Claude lit, il ne décide jamais à votre place.</p>
            <div className="conversation">
              <p className="bulle bulle--question">Qu’est-ce qui attend mon accord cette semaine ?</p>
              <div className="bulle bulle--reponse">
                Trois factures, pour 7 840 € au total :
                <ul>
                  <li>Atelier Numérique du Midi, 5 900 €, échéance le 31/12</li>
                  <li>Imprimerie Lumière, 1 420 €</li>
                  <li>Papeterie Durand, 520 €</li>
                </ul>
              </div>
            </div>
            <div className="outils" aria-label="Branchements disponibles">
              <span className="outil">Odoo</span>
              <span className="outil">Claude</span>
              <span className="outil">Réception par mail</span>
              <span className="outil">API et webhooks</span>
            </div>
          </div>
        </div>
      </section>

      <section className="pilote" id="pilote">
        <div className="conteneur pilote__grille">
          <div>
            <h2>Programme pilote : deux mois offerts, cinq entreprises.</h2>
            <p className="chapo">Nous installons Verifac avec vous, sur vos vraies factures. En échange, vous nous dites franchement ce qui marche et ce qui manque.</p>
            <div className="places" aria-hidden="true">
              {Array.from({ length: 5 }, (_, rang) => (
                <i key={rang} />
              ))}
            </div>
            <p className="places__texte">5 places ouvertes</p>
            <ul className="inclus">
              {PILOTE.map((point) => (
                <li key={point.titre}>
                  <Coche />
                  <div>
                    <strong>{point.titre}</strong>
                    <br />
                    <span>{point.texte}</span>
                  </div>
                </li>
              ))}
            </ul>
            <p className="apres">Après le pilote, si vous continuez : une mise en place et un forfait mensuel, chiffrés selon votre volume de factures.</p>
          </div>
          <FormulairePilote />
        </div>
      </section>

      <section className="section" id="documentation">
        <div className="conteneur">
          <div className="section__tete">
            <h2>Documentation et support.</h2>
            <p className="chapo">Des guides courts, écrits pour ceux qui utilisent Verifac chaque jour. Et une vraie personne quand il faut.</p>
          </div>
          <div className="aide">
            <div className="guides">
              {GUIDES.map((guide) => (
                <Link className="guide" href={`/documentation/${guide.slug}`} key={guide.slug}>
                  <span className="guide__icone">
                    <IconeDeGuide nom={guide.icone} />
                  </span>
                  <span>
                    <strong>{guide.titre}</strong>
                    <span>{guide.resume}</span>
                  </span>
                  <time>{guide.duree}</time>
                </Link>
              ))}
            </div>
            <div className="support">
              <div className="panneau">
                <h3>Une question, un blocage ?</h3>
                <p>Écrivez-nous. Une personne qui connaît Verifac vous répond, pas un robot.</p>
                <div className="support__contact">
                  <a href={`mailto:${SITE.support}`}>{SITE.support}</a>
                  <span>Réponse sous un jour ouvré, du lundi au vendredi.</span>
                </div>
              </div>
              <div className="panneau developpeurs">
                <h3>Développeurs</h3>
                <p>
                  L’API publique est documentée sur <a href="https://app.verifac.company/api/v1/docs">app.verifac.company/api/v1/docs</a>. Chaque message envoyé à votre logiciel est signé.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="section" style={{ paddingTop: 0 }}>
        <div className="conteneur">
          <Questions liste={QUESTIONS} titre="Questions fréquentes." />
        </div>
      </section>

      <section className="final">
        <div className="conteneur">
          <h2>Voyez par vous-même, en un clic.</h2>
          <p className="chapo" style={{ marginInline: "auto" }}>
            La démo contient une fraude à l’IBAN, des doublons et un circuit à trois niveaux. Essayez de les laisser passer.
          </p>
          <div className="ouverture__actions">
            <a className="bouton bouton--plein" href={SITE.demo}>
              Essayer la démo
            </a>
            <a className="bouton bouton--trait" href="#pilote">
              Rejoindre le programme pilote
            </a>
          </div>
        </div>
      </section>
    </main>
  );
}
