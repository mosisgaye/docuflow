import Link from "next/link";

export default function PageIntrouvable() {
  return (
    <main className="texte">
      <div className="conteneur introuvable">
        <p className="introuvable__code">404</p>
        <h1>Cette page n’existe pas.</h1>
        <p className="chapo">L’adresse a peut-être changé. Voici où aller :</p>
        <div className="ouverture__actions" style={{ justifyContent: "flex-start" }}>
          <Link className="bouton bouton--plein" href="/">
            Accueil
          </Link>
          <Link className="bouton bouton--trait" href="/ressources">
            Ressources
          </Link>
          <Link className="bouton bouton--trait" href="/documentation">
            Documentation
          </Link>
        </div>
      </div>
    </main>
  );
}
