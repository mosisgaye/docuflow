import type { FactureResume, Statistiques } from './api'
import { LIBELLE_ETAT, euros, ilYA, manquant, siret } from './format'
import { Icone } from './Icones'

interface PropsDocuments {
  titre: string
  sousTitre: string
  factures: FactureResume[]
  recherche: string
  ouverte: string | null
  surOuverture: (id: string) => void
}

export function Documents({ titre, sousTitre, factures, recherche, ouverte, surOuverture }: PropsDocuments) {
  const mots = recherche.trim().toLowerCase()
  const visibles = factures.filter((facture) =>
    [facture.fournisseur_nom, facture.numero_facture, facture.nom_fichier, facture.fournisseur_siret].some((valeur) => valeur?.toLowerCase().includes(mots)),
  )
  return (
    <div className="page">
      <header className="tableau__titre">
        <h1>{titre}</h1>
        <p>{sousTitre}</p>
      </header>
      <section className="carte">
        {visibles.length === 0 ? (
          <p className="carte__vide">{mots ? `Aucune facture ne correspond à « ${recherche} ».` : 'Aucune facture ici.'}</p>
        ) : (
          <table className="liste">
            <thead>
              <tr>
                <th scope="col">Fournisseur</th>
                <th scope="col">Numéro</th>
                <th scope="col">SIRET</th>
                <th scope="col" className="liste__droite">
                  Montant TTC
                </th>
                <th scope="col">État</th>
                <th scope="col">Reçue</th>
              </tr>
            </thead>
            <tbody>
              {visibles.map((facture) => (
                <tr key={facture.id} aria-selected={facture.id === ouverte} onClick={() => surOuverture(facture.id)}>
                  <td>
                    <button className="liste__nom" onClick={() => surOuverture(facture.id)}>
                      {facture.fournisseur_nom ?? facture.nom_fichier}
                    </button>
                  </td>
                  <td>{facture.numero_facture ?? manquant(facture.etat)}</td>
                  <td>{siret(facture.fournisseur_siret)}</td>
                  <td className="liste__droite">{euros(facture.total_ttc, manquant(facture.etat))}</td>
                  <td>
                    <span className={`pastille pastille--${facture.etat}`}>{LIBELLE_ETAT[facture.etat]}</span>
                    {facture.nb_anomalies > 0 && <small className="liste__anomalies">{facture.nb_anomalies} anomalie{facture.nb_anomalies > 1 ? 's' : ''}</small>}
                  </td>
                  <td>{ilYA(facture.cree_le)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}

const pluriel = (nombre: number, singulier: string, plurielle: string) => `${nombre} ${nombre > 1 ? plurielle : singulier}`

const INTEGRATIONS = [
  {
    nom: 'Réception par mail',
    detail: 'Les factures envoyées à depot@factures.moussagaye.com arrivent toutes seules, avec l’expéditeur et l’objet du mail. Chaque envoi est signé.',
    etat: 'actif',
    icone: 'document',
  },
  {
    nom: 'IA d’extraction',
    detail: 'Lit le texte de la facture et en sort les données. Le fournisseur est interchangeable : OpenAI ou Gemini, par simple réglage.',
    etat: 'actif',
    icone: 'assistant',
  },
  {
    nom: 'Registre des entreprises',
    detail: 'Service de l’État français. L’assistant y vérifie qu’un fournisseur existe et qu’il est en activité.',
    etat: 'actif',
    icone: 'bouclier',
  },
  {
    nom: 'Annonces légales (BODACC)',
    detail: 'Service de l’État français. Signale un fournisseur en redressement ou en liquidation.',
    etat: 'actif',
    icone: 'alerte',
  },
  {
    nom: 'Logiciel de comptabilité',
    detail: 'Chaque facture validée devient une écriture au journal des achats, en fichier CSV importable. L’envoi direct au logiciel du client se règle par une simple adresse.',
    etat: 'actif',
    icone: 'integration',
  },
  {
    nom: 'Factures électroniques (Factur-X)',
    detail: 'Format de la réforme française de 2026. Les données sont lues directement dans le XML de la facture, sans IA, en quelques millisecondes.',
    etat: 'actif',
    icone: 'document',
  },
  {
    nom: 'Lecture des scans',
    detail: 'Reconnaissance de texte pour les factures photographiées ou scannées.',
    etat: 'prevu',
    icone: 'recherche',
  },
] as const

/** Ce qui fonctionne sans rien brancher : les services intégrés à DocuFlow (onglet de la page Connecteurs). */
export function ServicesIntegres({ statistiques }: { statistiques: Statistiques | null }) {
  return (
    <>
      <ul className="integrations">
        {INTEGRATIONS.map((integration) => (
          <li key={integration.nom} className="carte">
            <span className="integrations__icone">
              <Icone nom={integration.icone} taille={22} />
            </span>
            <h2>{integration.nom}</h2>
            <p>{integration.detail}</p>
            <span className={`pastille pastille--${integration.etat === 'actif' ? 'validee' : 'recue'}`}>{integration.etat === 'actif' ? 'En service' : 'Prévue'}</span>
          </li>
        ))}
      </ul>
      {statistiques && (
        <p className="page__note">
          {pluriel(statistiques.lues_par_ia, 'facture lue', 'factures lues')} par l’IA d’extraction,{' '}
          {pluriel(statistiques.lues_sans_ia, 'facture électronique Factur-X lue', 'factures électroniques Factur-X lues')} sans IA.
        </p>
      )}
    </>
  )
}
