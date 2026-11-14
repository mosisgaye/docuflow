import type { FactureDetail, Statistiques } from './api'
import * as api from './api'
import { ETAPES, LIBELLE_ETAT, avancement, duree, euros, heureCourte, ilYA, jour, manquant, raconter } from './format'
import { Icone } from './Icones'

interface Props {
  statistiques: Statistiques
  vedette: FactureDetail | null
  depotEnCours: string | null
  surOuverture: (id: string) => void
  surAssistant: (question?: string) => void
  surDocuments: () => void
}

const POURCENT = new Intl.NumberFormat('fr-FR', { style: 'percent', maximumFractionDigits: 1 })
const ICONES_ETAPES = ['reception', 'assistant', 'bouclier', 'utilisateur', 'coche'] as const

/** Petite courbe des dernières durées d'analyse, tracée avec les vraies mesures. */
function Courbe({ valeurs }: { valeurs: number[] }) {
  if (valeurs.length < 2) return null
  const max = Math.max(...valeurs)
  const min = Math.min(...valeurs)
  const points = valeurs.map((valeur, rang) => {
    const x = (rang / (valeurs.length - 1)) * 100
    const y = 26 - ((valeur - min) / (max - min || 1)) * 22
    return `${x.toFixed(1)},${y.toFixed(1)}`
  })
  return (
    <svg className="courbe" viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true">
      <polyline points={points.join(' ')} fill="none" stroke="currentColor" strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

function Parcours({ faites, alerte, heures, enCours, sansIA = false }: { faites: number; alerte: boolean; heures: (string | null)[]; enCours: boolean; sansIA?: boolean }) {
  const etapes = ETAPES.map((etape, rang) => (rang === 1 && sansIA ? 'Lecture Factur-X' : etape))
  return (
    <ol className="parcours">
      {etapes.map((etape, rang) => {
        const etat = rang < faites ? 'faite' : rang === faites ? (alerte ? 'alerte' : 'active') : 'attente'
        return (
          <li key={etape} className={`parcours__etape parcours__etape--${etat}${enCours && rang === faites ? ' parcours__etape--tourne' : ''}`}>
            <span className="parcours__rond">
              <Icone nom={ICONES_ETAPES[rang]} taille={18} />
            </span>
            <span className="parcours__nom">{etape}</span>
            <span className="parcours__heure">{heures[rang] ?? ''}</span>
          </li>
        )
      })}
    </ol>
  )
}

function heuresDesEtapes(facture: FactureDetail): (string | null)[] {
  const heureDe = (...types: string[]) => {
    const evenement = [...facture.evenements].reverse().find((e) => types.includes(e.type))
    return evenement ? heureCourte(evenement.cree_le) : null
  }
  const decision = heureDe('VALIDATION', 'REJET')
  const fin = facture.etat === 'rejetee' ? decision : heureDe('EXPORT')
  return [heureDe('RECEPTION'), heureDe('EXTRACTION', 'EXTRACTION_ECHOUEE', 'LECTURE_IMPOSSIBLE'), heureDe('CONTROLE'), decision, fin]
}

function Repartition({ statistiques }: { statistiques: Statistiques }) {
  const parEtat = statistiques.par_etat
  const parts = [
    { nom: 'À valider', nombre: parEtat.a_valider, couleur: 'var(--bleu)' },
    { nom: 'En anomalie', nombre: parEtat.en_anomalie + parEtat.echec, couleur: 'var(--orange)' },
    { nom: 'Validées', nombre: parEtat.validee, couleur: 'var(--vert)' },
    { nom: 'Envoyées en comptabilité', nombre: parEtat.exportee, couleur: 'var(--vert-fonce)' },
    { nom: 'Rejetées', nombre: parEtat.rejetee, couleur: 'var(--violet)' },
  ]
  const total = statistiques.total || 1
  const perimetre = 2 * Math.PI * 42
  let depart = 0
  return (
    <div className="repartition">
      <svg viewBox="0 0 100 100" role="img" aria-label={`Répartition de ${statistiques.total} factures par état`}>
        <circle cx="50" cy="50" r="42" fill="none" stroke="var(--creux)" strokeWidth="13" />
        {parts.map((part) => {
          const longueur = (part.nombre / total) * perimetre
          const arc = (
            <circle
              key={part.nom}
              cx="50"
              cy="50"
              r="42"
              fill="none"
              stroke={part.couleur}
              strokeWidth="13"
              strokeDasharray={`${longueur} ${perimetre - longueur}`}
              strokeDashoffset={-depart}
              transform="rotate(-90 50 50)"
            />
          )
          depart += longueur
          return part.nombre > 0 ? arc : null
        })}
        <text x="50" y="49" textAnchor="middle" className="repartition__total">
          {statistiques.total}
        </text>
        <text x="50" y="62" textAnchor="middle" className="repartition__legende">
          au total
        </text>
      </svg>
      <ul>
        {parts.map((part) => (
          <li key={part.nom}>
            <span className="repartition__puce" style={{ background: part.couleur }} />
            <span>{part.nom}</span>
            <strong>{part.nombre}</strong>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function TableauDeBord({ statistiques, vedette, depotEnCours, surOuverture, surAssistant, surDocuments }: Props) {
  const total = statistiques.total
  const progression = vedette ? avancement(vedette.etat) : { faites: 1, alerte: false }

  return (
    <div className="tableau">
      <header className="tableau__titre">
        <h1>Bienvenue sur DocuFlow AI</h1>
        <p>Vos factures fournisseurs, lues par l’IA, contrôlées par des règles, validées par vous.</p>
      </header>

      <section className="chiffres" aria-label="Chiffres clés">
        <article className="chiffre chiffre--bleu">
          <span className="chiffre__icone">
            <Icone nom="document" taille={24} />
          </span>
          <div>
            <strong>{total}</strong>
            <p>
              Factures reçues
              {statistiques.lues_sans_ia > 0 && `, dont ${statistiques.lues_sans_ia} Factur-X lue${statistiques.lues_sans_ia > 1 ? 's' : ''} sans IA`}
            </p>
          </div>
        </article>
        <article className="chiffre chiffre--vert">
          <span className="chiffre__icone">
            <Icone nom="bouclier" taille={24} />
          </span>
          <div>
            <strong>{total ? POURCENT.format(statistiques.conformes / total) : 'Aucune'}</strong>
            <p>Conformes dès la lecture</p>
          </div>
        </article>
        <article className="chiffre chiffre--violet">
          <span className="chiffre__icone">
            <Icone nom="horloge" taille={24} />
          </span>
          <div>
            <strong>{statistiques.duree_moyenne_s === null ? 'Aucune' : duree(statistiques.duree_moyenne_s)}</strong>
            <p>Temps moyen d’analyse par l’IA</p>
          </div>
          <Courbe valeurs={statistiques.durees_recentes_s} />
        </article>
        <article className="chiffre chiffre--orange">
          <span className="chiffre__icone">
            <Icone nom="alerte" taille={24} />
          </span>
          <div>
            <strong>{statistiques.anomalies_detectees}</strong>
            <p>Anomalies attrapées par les contrôles</p>
          </div>
        </article>
      </section>

      <section className="carte carte--workflow">
        <header className="carte__tete">
          <h2>
            <Icone nom="eclair" /> Parcours d’une facture
          </h2>
          {depotEnCours && <span className="pastille pastille--bleu">Analyse en cours</span>}
        </header>
        {depotEnCours ? (
          <>
            <Parcours faites={1} alerte={false} heures={[]} enCours />
            <p className="workflow__attente">Lecture de « {depotEnCours} » par l’IA…</p>
          </>
        ) : vedette ? (
          <>
            <Parcours
              faites={progression.faites}
              alerte={progression.alerte}
              heures={heuresDesEtapes(vedette)}
              enCours={false}
              sansIA={vedette.evenements.some((evenement) => evenement.type === 'EXTRACTION' && evenement.detail.source === 'factur-x')}
            />
            <div className="workflow__detail">
              <iframe className="workflow__apercu" src={api.adresseFichier(vedette.id)} title={`Aperçu de ${vedette.nom_fichier}`} tabIndex={-1} />
              <div className="workflow__fiche">
                <div className="workflow__entete">
                  <h3>Facture n° {vedette.numero_facture ?? vedette.nom_fichier}</h3>
                  <span className={`pastille pastille--${vedette.etat}`}>{LIBELLE_ETAT[vedette.etat]}</span>
                </div>
                <dl>
                  <div>
                    <dt>Fournisseur</dt>
                    <dd>{vedette.fournisseur_nom ?? manquant(vedette.etat)}</dd>
                  </div>
                  <div>
                    <dt>Montant TTC</dt>
                    <dd>{euros(vedette.total_ttc, manquant(vedette.etat))}</dd>
                  </div>
                  <div>
                    <dt>Échéance</dt>
                    <dd>{jour(vedette.donnees?.date_echeance ?? null, manquant(vedette.etat))}</dd>
                  </div>
                </dl>
                {vedette.anomalies[0] && <p className="workflow__anomalie">{vedette.anomalies[0].message}</p>}
                <div className="workflow__barre" role="progressbar" aria-valuenow={progression.faites * 20} aria-valuemin={0} aria-valuemax={100}>
                  <span style={{ width: `${progression.faites * 20}%` }} className={progression.alerte ? 'workflow__barre--alerte' : undefined} />
                  <strong>{progression.faites * 20} %</strong>
                </div>
                <button className="bouton bouton--plein" onClick={() => surOuverture(vedette.id)}>
                  Ouvrir la facture
                </button>
              </div>
            </div>
          </>
        ) : (
          <p className="carte__vide">Déposez une première facture pour voir son parcours ici.</p>
        )}
      </section>

      <section className="carte carte--recents">
        <header className="carte__tete">
          <h2>
            <Icone nom="document" /> Factures récentes
          </h2>
          <button className="lien" onClick={surDocuments}>
            Tout voir
          </button>
        </header>
        {statistiques.recentes.length === 0 ? (
          <p className="carte__vide">Aucune facture reçue.</p>
        ) : (
          <ul className="recents">
            {statistiques.recentes.map((facture) => (
              <li key={facture.id}>
                <button onClick={() => surOuverture(facture.id)}>
                  <span className="recents__pdf">PDF</span>
                  <span className="recents__nom">
                    <strong>{facture.fournisseur_nom ?? facture.nom_fichier}</strong>
                    <small>{facture.numero_facture ? `n° ${facture.numero_facture}` : facture.nom_fichier}</small>
                  </span>
                  <span className={`pastille pastille--${facture.etat}`}>{LIBELLE_ETAT[facture.etat]}</span>
                  <small className="recents__quand">{ilYA(facture.cree_le)}</small>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="carte carte--repartition">
        <header className="carte__tete">
          <h2>Répartition par état</h2>
        </header>
        <Repartition statistiques={statistiques} />
      </section>

      <section className="carte carte--activite">
        <header className="carte__tete">
          <h2>Activité récente</h2>
        </header>
        {statistiques.activite.length === 0 ? (
          <p className="carte__vide">Rien pour l’instant.</p>
        ) : (
          <ol className="activite">
            {statistiques.activite.slice(0, 5).map((evenement) => (
              <li key={evenement.facture_id + evenement.rang} className={`activite--${evenement.etat}`}>
                <time dateTime={evenement.cree_le}>{heureCourte(evenement.cree_le)}</time>
                <span className="activite__puce" />
                <button onClick={() => surOuverture(evenement.facture_id)}>
                  <strong>{evenement.numero_facture ?? evenement.nom_fichier}</strong> {raconter(evenement)}
                </button>
              </li>
            ))}
          </ol>
        )}
      </section>

      <section className="carte carte--assistant">
        <h2>
          <Icone nom="assistant" taille={22} /> Demandez à l’assistant
        </h2>
        <p>Il consulte vos factures, vérifie un fournisseur auprès de l’État et prépare vos décisions.</p>
        <button className="carte__question" onClick={() => surAssistant('Quelles factures posent problème, et pourquoi ?')}>
          Quelles factures posent problème ?
        </button>
        <button className="bouton bouton--plein" onClick={() => surAssistant()}>
          Ouvrir l’assistant <Icone nom="fleche" taille={16} />
        </button>
      </section>
    </div>
  )
}
