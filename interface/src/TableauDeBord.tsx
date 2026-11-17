import type { FactureDetail, FactureResume, Statistiques } from './api'
import * as api from './api'
import { ETAPES, LIBELLE_ETAT, aRegler, aRisque, attenteLongue, avancement, echeanceProche, duree, euros, heureCourte, ilYA, initiales, jour, manquant, raconter, teinte } from './format'
import { Icone } from './Icones'

interface Props {
  statistiques: Statistiques
  vedette: FactureDetail | null
  depotEnCours: string | null
  auteur: string
  surOuverture: (id: string) => void
  surAssistant: (question?: string) => void
  surDocuments: () => void
  factures: FactureResume[]
  monTour: number | null // null : on ne sait pas qui vous êtes (votre nom n'est pas dans « Mon équipe »)
  surVue: (vue: 'mon_tour' | 'a_regler' | 'echeances' | 'attente') => void
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
      <polyline points={points.join(' ')} fill="none" stroke="currentColor" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
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
              <Icone nom={etat === 'faite' ? 'coche' : ICONES_ETAPES[rang]} taille={14} />
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
    { nom: 'À valider', nombre: parEtat.a_valider + (parEtat.en_approbation ?? 0), couleur: 'var(--bleu)' },
    { nom: 'En anomalie', nombre: parEtat.en_anomalie + parEtat.echec, couleur: 'var(--ambre)' },
    { nom: 'Validées', nombre: parEtat.validee, couleur: 'var(--vert-trait)' },
    { nom: 'En comptabilité', nombre: parEtat.exportee, couleur: 'var(--vert)' },
    { nom: 'Rejetées', nombre: parEtat.rejetee, couleur: 'var(--rouge)' },
  ]
  const total = statistiques.total || 1
  const perimetre = 2 * Math.PI * 42
  let depart = 0
  return (
    <div className="repartition bloc__corps">
      <svg viewBox="0 0 100 100" role="img" aria-label={`Répartition de ${statistiques.total} factures par état`}>
        <circle cx="50" cy="50" r="42" fill="none" stroke="var(--creux)" strokeWidth="10" />
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
              strokeWidth="10"
              strokeDasharray={`${longueur} ${perimetre - longueur}`}
              strokeDashoffset={-depart}
              transform="rotate(-90 50 50)"
            />
          )
          depart += longueur
          return part.nombre > 0 ? arc : null
        })}
        <text x="50" y="52" textAnchor="middle" className="repartition__total">
          {statistiques.total}
        </text>
        <text x="50" y="65" textAnchor="middle" className="repartition__legende">
          factures
        </text>
      </svg>
      <ul>
        {parts.map((part) => (
          <li key={part.nom}>
            <span className="puce" style={{ background: part.couleur }} />
            <span>{part.nom}</span>
            <strong>{part.nombre}</strong>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Ce qui demande une action aujourd'hui : trois cartes, chacune ouvre la liste des factures concernées. */
function AFaire({ factures, monTour, surVue }: { factures: FactureResume[]; monTour: number | null; surVue: Props['surVue'] }) {
  const cartes = [
    ...(monTour !== null
      ? [{ vue: 'mon_tour' as const, nombre: monTour, un: 'facture à approuver par vous', plusieurs: 'factures à approuver par vous', detail: 'C’est votre tour dans le circuit', icone: 'utilisateur' as const, ton: 'vert' }]
      : []),
    { vue: 'a_regler' as const, nombre: factures.filter((f) => aRegler(f)).length, un: 'anomalie ou risque à régler', plusieurs: 'anomalies et risques à régler', detail: factures.some((f) => aRisque(f)) ? 'Dont un risque de fraude à l’IBAN' : 'Arrêtées aux contrôles ou illisibles', icone: 'anomalie' as const, ton: 'ambre' },
    { vue: 'echeances' as const, nombre: factures.filter((f) => echeanceProche(f)).length, un: 'échéance sous 7 jours', plusieurs: 'échéances sous 7 jours', detail: 'Ou déjà passées : risque de pénalités', icone: 'horloge' as const, ton: 'rouge' },
    { vue: 'attente' as const, nombre: factures.filter((f) => attenteLongue(f)).length, un: 'approbation en attente depuis 48 h', plusieurs: 'approbations en attente depuis 48 h', detail: 'Une relance est partie toute seule', icone: 'utilisateur' as const, ton: 'bleu' },
  ]
  return (
    <section className={`a-faire${cartes.length === 4 ? ' a-faire--quatre' : ''}`} aria-label="À faire aujourd’hui">
      {cartes.map((carte) => (
        <button key={carte.vue} className={`a-faire__carte a-faire__carte--${carte.nombre ? carte.ton : 'calme'}`} onClick={() => surVue(carte.vue)} disabled={carte.nombre === 0}>
          <span className="a-faire__icone" aria-hidden="true">
            <Icone nom={carte.nombre ? carte.icone : 'coche'} taille={18} />
          </span>
          <span className="a-faire__texte">
            <strong>{carte.nombre === 0 ? `Aucune ${carte.un}` : `${carte.nombre} ${carte.nombre > 1 ? carte.plusieurs : carte.un}`}</strong>
            <small>{carte.nombre === 0 ? 'Rien à faire ici' : carte.detail}</small>
          </span>
          {carte.nombre > 0 && <Icone nom="suivant" taille={16} />}
        </button>
      ))}
    </section>
  )
}

export function TableauDeBord({ statistiques, vedette, depotEnCours, auteur, surOuverture, surAssistant, surDocuments, factures, monTour, surVue }: Props) {
  const total = statistiques.total
  const progression = vedette ? avancement(vedette.etat) : { faites: 1, alerte: false }
  const prenom = auteur.trim().split(/\s+/)[0]

  return (
    <div className="tableau">
      <header className="page__titre">
        <div>
          <h1>{prenom ? `Bonjour ${prenom}` : 'Vue d’ensemble'}</h1>
          <p>Vos factures fournisseurs, lues par l’IA, contrôlées par des règles, validées par vous.</p>
        </div>
      </header>

      <AFaire factures={factures} monTour={monTour} surVue={surVue} />

      <section className="indicateurs" aria-label="Chiffres clés">
        <div className="indicateur">
          <p>
            <Icone nom="document" taille={14} /> Factures reçues
          </p>
          <strong>{total}</strong>
          <small>{statistiques.lues_sans_ia > 0 ? `dont ${statistiques.lues_sans_ia} Factur-X lue${statistiques.lues_sans_ia > 1 ? 's' : ''} sans IA` : 'toutes sources confondues'}</small>
        </div>
        <div className="indicateur">
          <p>
            <Icone nom="bouclier" taille={14} /> Conformes dès la lecture
          </p>
          <strong>{total ? POURCENT.format(statistiques.conformes / total) : '—'}</strong>
          <small>sans aucune anomalie</small>
        </div>
        <div className="indicateur">
          <p>
            <Icone nom="horloge" taille={14} /> Temps moyen d’analyse
          </p>
          <strong>{statistiques.duree_moyenne_s === null ? '—' : duree(statistiques.duree_moyenne_s)}</strong>
          <small>par l’IA, mesuré</small>
          <Courbe valeurs={statistiques.durees_recentes_s} />
        </div>
        <div className="indicateur">
          <p>
            <Icone nom="alerte" taille={14} /> Anomalies attrapées
          </p>
          <strong>{statistiques.anomalies_detectees}</strong>
          <small>par les contrôles</small>
        </div>
      </section>

      <div className="tableau__principal">
        <section className="bloc">
          <header className="bloc__tete">
            <h2>
              <Icone nom="eclair" /> Parcours d’une facture
            </h2>
            {depotEnCours && <span className="etat etat--recue">Analyse en cours</span>}
          </header>
          {depotEnCours ? (
            <>
              <Parcours faites={1} alerte={false} heures={[]} enCours />
              <p className="attente">Lecture de « {depotEnCours} » par l’IA…</p>
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
              <div className="vedette">
                <iframe className="vedette__apercu" src={`${api.adresseFichier(vedette.id)}`} title={`Aperçu de ${vedette.nom_fichier}`} tabIndex={-1} />
                <div>
                  <div className="vedette__entete">
                    <h3>Facture n° {vedette.numero_facture ?? vedette.nom_fichier}</h3>
                    <span className={`etat etat--${vedette.etat}`}>{LIBELLE_ETAT[vedette.etat]}</span>
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
                  {vedette.anomalies[0] && <p className="vedette__anomalie">{vedette.anomalies[0].message}</p>}
                  <div className="progression" role="progressbar" aria-valuenow={progression.faites * 20} aria-valuemin={0} aria-valuemax={100} aria-label="Avancement">
                    <span className="progression__piste">
                      <span style={{ width: `${progression.faites * 20}%` }} className={progression.alerte ? 'progression--alerte' : undefined} />
                    </span>
                    {progression.faites * 20} %
                  </div>
                  <button className="bouton bouton--plein" onClick={() => surOuverture(vedette.id)}>
                    Ouvrir la facture <Icone nom="fleche" />
                  </button>
                </div>
              </div>
            </>
          ) : (
            <div className="vide">
              <Icone nom="reception" taille={28} />
              <strong>Aucune facture pour l’instant</strong>
              <p>Déposez une première facture pour voir son parcours ici.</p>
            </div>
          )}
        </section>

        <section className="bloc">
          <header className="bloc__tete">
            <h2>
              <Icone nom="document" /> Factures récentes
            </h2>
            <button className="bouton bouton--fantome bouton--petit" onClick={surDocuments}>
              Tout voir <Icone nom="suivant" taille={14} />
            </button>
          </header>
          {statistiques.recentes.length === 0 ? (
            <p className="attente">Aucune facture reçue.</p>
          ) : (
            <ul className="rangees">
              {statistiques.recentes.map((facture) => (
                <li key={facture.id}>
                  <button className="rangee" onClick={() => surOuverture(facture.id)}>
                    <span className={`avatar avatar--grand teinte-${teinte(facture.fournisseur_nom ?? facture.nom_fichier)}`} aria-hidden="true">
                      {initiales(facture.fournisseur_nom ?? facture.nom_fichier)}
                    </span>
                    <span className="rangee__texte">
                      <strong>{facture.fournisseur_nom ?? facture.nom_fichier}</strong>
                      <small>
                        {facture.numero_facture ? `n° ${facture.numero_facture}` : facture.nom_fichier}
                        {facture.total_ttc ? ` · ${euros(facture.total_ttc)}` : ''}
                      </small>
                    </span>
                    <span className={`etat etat--${facture.etat}`}>{LIBELLE_ETAT[facture.etat]}</span>
                    <span className="rangee__quand">{ilYA(facture.cree_le)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <div className="tableau__cote">
        <section className="bloc">
          <header className="bloc__tete">
            <h2>Répartition par état</h2>
          </header>
          <Repartition statistiques={statistiques} />
        </section>

        <section className="bloc">
          <header className="bloc__tete">
            <h2>
              <Icone nom="journal" /> Activité récente
            </h2>
          </header>
          {statistiques.activite.length === 0 ? (
            <p className="attente">Rien pour l’instant.</p>
          ) : (
            <ol className="activite" style={{ padding: '0.375rem 0' }}>
              {statistiques.activite.slice(0, 6).map((evenement) => (
                <li key={evenement.facture_id + evenement.rang}>
                  <time dateTime={evenement.cree_le}>{heureCourte(evenement.cree_le)}</time>
                  <button onClick={() => surOuverture(evenement.facture_id)}>
                    <strong>{evenement.numero_facture ?? evenement.nom_fichier}</strong> {raconter(evenement)}
                  </button>
                </li>
              ))}
            </ol>
          )}
        </section>

        <section className="bloc bloc--assistant">
          <h2>
            <Icone nom="assistant" /> Demandez à l’assistant
          </h2>
          <p>Il consulte vos factures, vérifie un fournisseur auprès de l’État et dans vos logiciels, puis prépare vos décisions.</p>
          <button className="question" onClick={() => surAssistant('Quelles factures posent problème, et pourquoi ?')}>
            <Icone nom="conversation" /> Quelles factures posent problème ?
          </button>
          <button className="bouton bouton--plein" onClick={() => surAssistant()}>
            Ouvrir l’assistant <Icone nom="fleche" />
          </button>
        </section>
      </div>
    </div>
  )
}
