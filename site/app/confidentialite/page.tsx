import type { Metadata } from "next";
import { alternatives, description, titre } from "@/lib/seo";
import { SITE } from "@/contenu/site";
import { ACompleter } from "../composants/ACompleter";

export const metadata: Metadata = {
  title: titre("Confidentialité"),
  description: description("Quelles données verifac.company recueille, pourquoi, combien de temps, et comment exercer vos droits : formulaire du pilote, cookies, factures traitées."),
  alternates: alternatives("/confidentialite"),
};

export default function Confidentialite() {
  return (
    <main className="texte">
      <div className="conteneur" style={{ maxWidth: "46rem" }}>
        <div className="prose">
          <h1>Confidentialité</h1>
          <p>
            Cette page explique quelles données le site verifac.company recueille, pourquoi, et comment exercer vos droits. Le responsable du traitement est{" "}
            <ACompleter>nom ou raison sociale de l’éditeur</ACompleter>.
          </p>

          <h2>Le formulaire du programme pilote</h2>
          <table>
            <tbody>
              <tr>
                <th>Données</th>
                <td>Nom, entreprise, adresse professionnelle, nombre de factures par mois, logiciel comptable, et votre message s’il y en a un.</td>
              </tr>
              <tr>
                <th>Pourquoi</th>
                <td>Vous recontacter au sujet du programme pilote, à votre demande.</td>
              </tr>
              <tr>
                <th>Base légale</th>
                <td>Les mesures précontractuelles prises à votre demande.</td>
              </tr>
              <tr>
                <th>Durée</th>
                <td>Trois ans après notre dernier échange, puis suppression.</td>
              </tr>
              <tr>
                <th>Qui les voit</th>
                <td>Seulement l’équipe de Verifac. Le mail qui nous annonce votre demande passe par Resend, notre service d’envoi de mails.</td>
              </tr>
            </tbody>
          </table>

          <h2>Mesure d’audience et cookies</h2>
          <p>
            Pour savoir quelles pages sont lues et vérifier qu’elles s’affichent vite, le site utilise Vercel Web Analytics et Vercel Speed Insights. Ces outils ne
            déposent aucun cookie et ne suivent pas les visiteurs d’un site à l’autre : ils comptent des visites et mesurent la vitesse d’affichage, de façon anonyme.
          </p>
          <p>
            Le site vitrine ne dépose aucun cookie de publicité. Seul le cookie de session est posé quand vous vous connectez à Verifac : il est nécessaire au service et ne
            sert à rien d’autre.
          </p>

          <h2>Les factures traitées par Verifac</h2>
          <p>
            Les factures de nos clients sont traitées pour leur compte, dans le cadre de leur contrat, sur une installation dédiée. Elles ne servent à rien d’autre et ne sont
            jamais revendues.
          </p>

          <h2>Vos droits</h2>
          <p>
            Vous pouvez demander l’accès à vos données, leur correction ou leur suppression, et vous opposer à leur traitement. Écrivez à{" "}
            <a href={`mailto:${SITE.support}`}>{SITE.support}</a> : nous répondons sous un mois au plus. Si vous estimez que vos droits ne sont pas respectés, vous pouvez
            saisir la CNIL (cnil.fr).
          </p>
        </div>
      </div>
    </main>
  );
}
