import { useState } from 'react'
import { usePeut } from './droits'
import type { Etat, FactureResume, Statistiques } from './api'
import { LIBELLE_ETAT, ORDRE_ETATS, aRisque, euros, ilYA, initiales, jour, manquant, teinte, urgence } from './format'
import { Icone, type NomIcone } from './Icones'

interface PropsDocuments {
  factures: FactureResume[]
  recherche: string
  ouverte: string | null
  surOuverture: (id: string) => void
  surDepot: () => void
}

function Ligne({ facture, ouverte, surOuverture, avecEtat }: { facture: FactureResume; ouverte: boolean; surOuverture: (id: string) => void; avecEtat: boolean }) {
  const echeance = urgence(facture.date_echeance)
  const lue = facture.etat !== 'recue' && facture.etat !== 'echec'
  return (
    <tr className="liste__ligne" aria-selected={ouverte} onClick={() => surOuverture(facture.id)}>
      <td>
        <span className="liste__fournisseur">
          <span className={`avatar teinte-${teinte(facture.fournisseur_nom ?? facture.nom_fichier)}`} aria-hidden="true">
            {initiales(facture.fournisseur_nom ?? facture.nom_fichier)}
          </span>
          <button className="liste__nom" onClick={() => surOuverture(facture.id)}>
            {facture.fournisseur_nom ?? facture.nom_fichier}
          </button>
          {aRisque(facture) && (
            <span className="liste__risque" title="IBAN différent de celui connu, ou jamais vu : appelez le fournisseur avant de payer">
              <Icone nom="alerte" taille={12} /> IBAN
            </span>
          )}
        </span>
      </td>
      <td className="liste__col-numero liste__secondaire">{facture.numero_facture ?? manquant(facture.etat)}</td>
      <td className="liste__droite">{euros(facture.total_ttc, manquant(facture.etat))}</td>
      <td className={`liste__col-echeance ${echeance ? `echeance--${echeance}` : 'liste__secondaire'}`}>
        {facture.date_echeance ? jour(facture.date_echeance) : <span className="liste__muet">{lue ? 'Absente' : '—'}</span>}
      </td>
      <td className="liste__col-anomalies">
        {facture.nb_anomalies > 0 ? (
          <span className="liste__anomalies">
            <Icone nom="anomalie" taille={14} />
            {facture.nb_anomalies}
          </span>
        ) : (
          <span className="liste__muet">—</span>
        )}
      </td>
      {avecEtat && (
        <td>
          <span className={`etat etat--${facture.etat}`}>{LIBELLE_ETAT[facture.etat]}</span>
        </td>
      )}
      <td className="liste__col-recue liste__muet">{ilYA(facture.cree_le)}</td>
    </tr>
  )
}

/** Un groupe de la liste : un état, ou les factures à risque de fraude à l'IBAN (tous états à décider confondus). */
type Groupe = Etat | 'risque'

/** Les factures en liste dense, groupées par état comme une liste de tâches. */
export function Documents({ factures, recherche, ouverte, surOuverture, surDepot }: PropsDocuments) {
  const peut = usePeut()
  const [grouper, setGrouper] = useState(true)
  const [anomaliesSeules, setAnomaliesSeules] = useState(false)
  const [replies, setReplies] = useState<Set<Groupe>>(new Set())
  const visibles = anomaliesSeules ? factures.filter((facture) => facture.nb_anomalies > 0) : factures
  // Les risques de fraude à l'IBAN forment le premier groupe, devant tous les états : c'est ce qu'il faut voir d'abord.
  const groupes: { etat: Groupe | null; factures: FactureResume[] }[] = grouper
    ? [
        { etat: 'risque' as const, factures: visibles.filter(aRisque) },
        ...ORDRE_ETATS.map((etat) => ({ etat, factures: visibles.filter((facture) => facture.etat === etat && !aRisque(facture)) })),
      ].filter((groupe) => groupe.factures.length > 0)
    : [{ etat: null, factures: visibles }]

  const basculer = (etat: Groupe) =>
    setReplies((actuels) => {
      const suivants = new Set(actuels)
      if (suivants.has(etat)) suivants.delete(etat)
      else suivants.add(etat)
      return suivants
    })

  return (
    <>
      <div className="barre-outils">
        <button className="pastille-filtre" aria-pressed={grouper} onClick={() => setGrouper(!grouper)}>
          <Icone nom="grouper" taille={14} /> Grouper : état
        </button>
        <button className="pastille-filtre" aria-pressed={anomaliesSeules} onClick={() => setAnomaliesSeules(!anomaliesSeules)}>
          <Icone nom="anomalie" taille={14} /> Anomalies seulement
        </button>
        <span className="barre-outils__compte">
          {visibles.length} facture{visibles.length > 1 ? 's' : ''}
        </span>
      </div>

      {visibles.length === 0 ? (
        <div className="vide">
          <Icone nom={recherche.trim() ? 'recherche' : 'reception'} taille={28} />
          <strong>{recherche.trim() ? `Aucune facture ne correspond à « ${recherche.trim()} »` : 'Aucune facture ici'}</strong>
          <p>{recherche.trim() ? 'Essayez un nom de fournisseur, un numéro ou un SIRET.' : 'Déposez un PDF ou une photo de facture : elle est lue en quelques secondes.'}</p>
          {!recherche.trim() && peut('traiter') && (
            <button className="bouton bouton--plein" onClick={surDepot}>
              <Icone nom="deposer" /> Déposer des factures
            </button>
          )}
        </div>
      ) : (
        <table className="liste">
          <colgroup>
            <col />
            <col className="liste__col-numero" style={{ width: '8.125rem' }} />
            <col style={{ width: '7.5rem' }} />
            <col className="liste__col-echeance" style={{ width: '6.5rem' }} />
            <col className="liste__col-anomalies" style={{ width: '5.25rem' }} />
            {!grouper && <col style={{ width: '9.375rem' }} />}
            <col className="liste__col-recue" style={{ width: '6.25rem' }} />
          </colgroup>
          <thead>
            <tr>
              <th scope="col">Fournisseur</th>
              <th scope="col" className="liste__col-numero">
                Numéro
              </th>
              <th scope="col" className="liste__droite">
                Montant TTC
              </th>
              <th scope="col" className="liste__col-echeance">
                Échéance
              </th>
              <th scope="col" className="liste__col-anomalies">
                Anomalies
              </th>
              {/* Groupée par état, la liste ne répète pas l'état sur chaque ligne : le groupe le dit. */}
              {!grouper && <th scope="col">État</th>}
              <th scope="col" className="liste__col-recue">
                Reçue
              </th>
            </tr>
          </thead>
          {groupes.map((groupe) => {
            const replie = groupe.etat !== null && replies.has(groupe.etat)
            return (
              <tbody key={groupe.etat ?? 'toutes'}>
                {groupe.etat && (
                  <tr className={`liste__groupe${replie ? ' liste__groupe--replie' : ''}`}>
                    <th colSpan={grouper ? 6 : 7} scope="rowgroup">
                      <button aria-expanded={!replie} onClick={() => basculer(groupe.etat!)}>
                        <Icone nom="deplier" taille={14} />
                        <span className={`etat etat--${groupe.etat}`}>{groupe.etat === 'risque' ? 'Risque de fraude' : LIBELLE_ETAT[groupe.etat]}</span>
                        <span className="liste__groupe-compte">{groupe.factures.length}</span>
                      </button>
                    </th>
                  </tr>
                )}
                {!replie && groupe.factures.map((facture) => <Ligne key={facture.id} facture={facture} ouverte={facture.id === ouverte} surOuverture={surOuverture} avecEtat={!grouper} />)}
              </tbody>
            )
          })}
        </table>
      )}
    </>
  )
}

const pluriel = (nombre: number, singulier: string, plurielle: string) => `${nombre} ${nombre > 1 ? plurielle : singulier}`

const INTEGRATIONS: { nom: string; detail: string; icone: NomIcone }[] = [
  {
    nom: 'Réception par mail',
    detail: 'Les factures envoyées à depot@factures.moussagaye.com arrivent toutes seules, avec l’expéditeur et l’objet du mail. Chaque envoi est signé.',
    icone: 'mail',
  },
  {
    nom: 'IA d’extraction',
    detail: 'Lit la facture et en sort les données. Le fournisseur est interchangeable : OpenAI ou Gemini, par simple réglage.',
    icone: 'assistant',
  },
  {
    nom: 'Factures scannées et photos',
    detail: 'Un scan ou une photo prise au téléphone est lu sur l’image par l’IA, jusqu’à 3 pages. Le coût de chaque lecture est compté.',
    icone: 'document',
  },
  {
    nom: 'Factures électroniques (Factur-X)',
    detail: 'Format de la réforme française de 2026. Les données sont lues directement dans le XML de la facture, sans IA, en quelques millisecondes.',
    icone: 'facture',
  },
  {
    nom: 'Registre des entreprises',
    detail: 'Service de l’État français. L’assistant y vérifie qu’un fournisseur existe et qu’il est en activité.',
    icone: 'entreprise',
  },
  {
    nom: 'Annonces légales (BODACC)',
    detail: 'Service de l’État français. Signale un fournisseur en redressement ou en liquidation.',
    icone: 'alerte',
  },
  {
    nom: 'Mails d’approbation et relances',
    detail: 'Chaque approbateur reçoit un lien signé. Sans réponse après 48 heures, ou à 3 jours de l’échéance, il est relancé.',
    icone: 'sortie',
  },
  {
    nom: 'API publique',
    detail: 'D’autres logiciels déposent et lisent les factures avec une clé, dont les droits se règlent et qui se révoque en un clic.',
    icone: 'cle',
  },
  {
    nom: 'Événements sortants',
    detail: 'Un message signé part vers l’adresse de votre choix quand une facture change d’état. Retenté en cas d’échec.',
    icone: 'crochet',
  },
]

/** Ce qui fonctionne sans rien brancher : les services intégrés à Verifac (onglet de la page Connecteurs). */
export function ServicesIntegres({ statistiques }: { statistiques: Statistiques | null }) {
  return (
    <>
      <ul className="integrations">
        {INTEGRATIONS.map((integration) => (
          <li key={integration.nom}>
            <span className="integrations__icone">
              <Icone nom={integration.icone} />
            </span>
            <h2>{integration.nom}</h2>
            <p>{integration.detail}</p>
            <span className="etat etat--validee">En service</span>
          </li>
        ))}
      </ul>
      {statistiques && (
        <p className="note" style={{ marginTop: '0.875rem' }}>
          {pluriel(statistiques.lues_par_ia, 'facture lue', 'factures lues')} par l’IA d’extraction,{' '}
          {pluriel(statistiques.lues_sans_ia, 'facture électronique Factur-X lue', 'factures électroniques Factur-X lues')} sans IA.
        </p>
      )}
    </>
  )
}
