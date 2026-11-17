// Les versions publiées du circuit, de la plus récente à la plus ancienne, avec ce que chacune a changé.
import { useEffect, useState } from 'react'
import * as api from './api'
import type { Execution, VersionCircuit } from './api'
import { duree, euros, initiales, jourEtHeure, teinte } from './format'

export function Versions() {
  const [versions, setVersions] = useState<VersionCircuit[] | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)

  useEffect(() => {
    api.versionsCircuit().then(
      (reponse) => setVersions(reponse.versions),
      (probleme: Error) => setErreur(probleme.message),
    )
  }, [])

  return (
    <div className="page">
      <header className="page__titre">
        <div>
          <h1>Versions publiées</h1>
          <p>Chaque publication crée une version. Une facture garde la version avec laquelle son circuit a été calculé.</p>
        </div>
      </header>
      {erreur && <p className="connecteurs__message">{erreur}</p>}
      {!versions && !erreur && <p className="note">Chargement…</p>}
      {versions?.length === 0 && <p className="reglages__vide">Aucune version publiée : une seule validation, celle du comptable, suffit pour chaque facture.</p>}
      {versions && versions.length > 0 && (
        <ol className="versions">
          {versions.map((version) => (
            <li key={version.version} className={`versions__ligne${version.en_service ? ' versions__ligne--service' : ''}`}>
              <div className="versions__tete">
                <strong>Version {version.version}</strong>
                {version.en_service && <span className="etat etat--validee">En service</span>}
                <span className="versions__qui">
                  <span className={`avatar teinte-${teinte(version.publie_par)}`} aria-hidden="true">
                    {initiales(version.publie_par)}
                  </span>
                  {version.publie_par}, le {jourEtHeure(version.publie_le)}
                </span>
                <span className="versions__compte">
                  {version.nombre_regles} règle{version.nombre_regles > 1 ? 's' : ''}
                  {version.relances_reglees && ', relances réglées'}
                </span>
              </div>
              {version.changements === null ? (
                <p className="versions__avant">Publiée avant l’éditeur : le détail des changements n’est pas connu.</p>
              ) : (
                <details className="versions__details" open={version.en_service}>
                  <summary>
                    {version.changements.length} changement{version.changements.length > 1 ? 's' : ''}
                  </summary>
                  <ul className="differences">
                    {version.changements.map((texte) => (
                      <li key={texte}>{texte}</li>
                    ))}
                  </ul>
                </details>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

const ETAT_PASTILLE: Record<string, string> = {
  validee: 'etat--validee',
  exportee: 'etat--exportee',
  rejetee: 'etat--rejetee',
  en_anomalie: 'etat--en_anomalie',
  echec: 'etat--echec',
}

export function Executions({ surFacture }: { surFacture: (id: string) => void }) {
  const [lignes, setLignes] = useState<Execution[] | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)

  useEffect(() => {
    api.executions(30).then(
      (reponse) => setLignes(reponse.executions),
      (probleme: Error) => setErreur(probleme.message),
    )
  }, [])

  return (
    <div className="page">
      <header className="page__titre">
        <div>
          <h1>Exécutions</h1>
          <p>Le chemin réellement suivi par les 30 dernières factures, lu dans leur journal.</p>
        </div>
      </header>
      {erreur && <p className="connecteurs__message">{erreur}</p>}
      {!lignes && !erreur && <p className="note">Chargement…</p>}
      {lignes?.length === 0 && <p className="reglages__vide">Aucune facture reçue pour l’instant.</p>}
      {lignes && lignes.length > 0 && (
        <div className="executions">
          <table>
            <thead>
              <tr>
                <th scope="col">Facture</th>
                <th scope="col">Chemin suivi</th>
                <th scope="col">Durée</th>
                <th scope="col">Résultat</th>
                <th scope="col">Version</th>
              </tr>
            </thead>
            <tbody>
              {lignes.map((ligne) => (
                <tr key={ligne.facture_id}>
                  <td>
                    <button className="executions__facture" onClick={() => surFacture(ligne.facture_id)}>
                      <strong>{ligne.fournisseur ?? 'Fournisseur inconnu'}</strong>
                      <small>
                        {ligne.numero ?? 'sans numéro'}
                        {ligne.total_ttc && ` · ${euros(ligne.total_ttc)}`}
                      </small>
                    </button>
                  </td>
                  <td>
                    <ol className="executions__chemin">
                      {ligne.chemin.map((etape, rang) => (
                        <li key={`${etape}-${rang}`}>{etape}</li>
                      ))}
                    </ol>
                  </td>
                  <td className="executions__duree">
                    {duree(ligne.duree_s)}
                    {ligne.en_cours && <small>, en cours</small>}
                  </td>
                  <td>
                    <span className={`etat ${ETAT_PASTILLE[ligne.etat] ?? 'etat--en_approbation'}`}>{ligne.resultat}</span>
                  </td>
                  <td className="executions__version">{ligne.version_circuit ? `v${ligne.version_circuit}` : 'aucune'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
