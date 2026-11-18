/** Une facture fictive passée aux contrôles de Verifac : trois vérifications passent, l'IBAN la retient.
 *  Les lignes apparaissent l'une après l'autre en CSS (rien d'animé si le mouvement réduit est demandé). */

const VERIFIE = (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="3"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M5 12.5l4.5 4.5L19 7" />
  </svg>
);

const ALERTE = (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="3"
    strokeLinecap="round"
    aria-hidden="true"
  >
    <path d="M12 7v6M12 17v.5" />
  </svg>
);

const CONTROLES = [
  {
    titre: "Pas de doublon",
    detail: "Aucune facture du même fournisseur avec ce numéro ou ce montant.",
    retenue: false,
  },
  {
    titre: "Montants justes",
    detail: "4 010,00 € HT + 802,00 € de TVA à 20 %.",
    retenue: false,
  },
  {
    titre: "Mentions obligatoires",
    detail: "SIREN, TVA intracommunautaire, date d’échéance.",
    retenue: false,
  },
  {
    titre: "IBAN différent de celui d’Odoo",
    detail: "La facture est retenue jusqu’à confirmation du fournisseur.",
    retenue: true,
  },
];

export function FactureExemple() {
  return (
    <figure
      className="exemple"
      aria-label="Exemple : une facture contrôlée par Verifac"
    >
      <div className="exemple__tete">
        <div>
          <small>Facture FA-2026-0412</small>
          <strong>Imprimerie Duval SARL</strong>
        </div>
        <div className="exemple__montant">
          <small>Montant TTC</small>
          <strong>4 812,00 €</strong>
        </div>
      </div>
      <ul className="exemple__controles">
        {CONTROLES.map((c) => (
          <li key={c.titre} className={c.retenue ? "retenue" : undefined}>
            <span className="exemple__puce">
              {c.retenue ? ALERTE : VERIFIE}
            </span>
            <span>
              <b>{c.titre}</b>
              <span>{c.detail}</span>
            </span>
            <em>{c.retenue ? "Retenue" : "Vérifié"}</em>
          </li>
        ))}
      </ul>
      <figcaption className="exemple__pied">
        <span>
          Prochaine étape : <b>confirmer l’IBAN auprès du fournisseur</b>
        </span>
        <span>Exemple</span>
      </figcaption>
    </figure>
  );
}
