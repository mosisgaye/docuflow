import { DonneesStructurees } from "./DonneesStructurees";
import { graphe, questions } from "@/lib/schema";

export type Question = { question: string; reponse: string };

/** Une liste de questions repliables, et sa version FAQPage pour Google. */
export function Questions({ liste, titre = "Questions fréquentes" }: { liste: Question[]; titre?: string }) {
  return (
    <section className="questions-bloc">
      <h2>{titre}</h2>
      <div className="questions">
        {liste.map((item) => (
          <details key={item.question}>
            <summary>{item.question}</summary>
            <p>{item.reponse}</p>
          </details>
        ))}
      </div>
      <DonneesStructurees donnees={graphe(questions(liste))} />
    </section>
  );
}
