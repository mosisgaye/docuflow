import type { FactureResume, Statistiques } from './api'
import { LIBELLE_ETAT, euros, ilYA, siret } from './format'
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
                  <td>{facture.numero_facture ?? 'Non lu'}</td>
                  <td>{siret(facture.fournisseur_siret)}</td>
                  <td className="liste__droite">{facture.total_ttc ? euros(facture.total_ttc) : 'Non lu'}</td>
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

const INTEGRATIONS = [
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

export function Integrations({ statistiques }: { statistiques: Statistiques | null }) {
  return (
    <div className="page">
      <header className="tableau__titre">
        <h1>Intégrations</h1>
        <p>Les services auxquels la plateforme est reliée, et ceux qui restent à brancher.</p>
      </header>
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
      {statistiques && <p className="page__note">{statistiques.total} facture{statistiques.total > 1 ? 's ont' : ' a'} été analysée{statistiques.total > 1 ? 's' : ''} par l’IA d’extraction jusqu’ici.</p>}
    </div>
  )
}
