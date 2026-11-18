import { strict as assert } from "node:assert";
import { test } from "node:test";
import { ARTICLES } from "../contenu/ressources.ts";
import { GLOSSAIRE } from "../contenu/glossaire.ts";
import { GUIDES } from "../contenu/guides.ts";
import { DESCRIPTION_MAX, DESCRIPTION_MIN, SUFFIXE_TITRE, TITRE_MAX, alternatives, description, titre } from "./seo.ts";

const place = TITRE_MAX - SUFFIXE_TITRE.length;

test("titre() prend le premier candidat qui tient, sinon coupe sur un mot", () => {
  assert.equal(titre("Un titre court"), "Un titre court");
  assert.equal(titre("x".repeat(80), "Repli court"), "Repli court");
  const coupe = titre("Un titre beaucoup trop long pour tenir dans la limite de Google, vraiment");
  assert.ok(coupe.length <= place && coupe.endsWith("…"), coupe);
});

test("description() garde une description entre 70 et 160 caractères", () => {
  const juste = "Une description qui fait exactement ce qu’il faut pour être lue en entier dans Google.";
  assert.equal(description(juste), juste);
  assert.ok(description("mot ".repeat(60)).length <= DESCRIPTION_MAX);
});

test("alternatives() déclare la canonique et la langue, version par défaut comprise", () => {
  assert.deepEqual(alternatives("/glossaire"), { canonical: "/glossaire", languages: { "fr-FR": "/glossaire", "x-default": "/glossaire" } });
});

// Les contenus doivent tenir sans être coupés : une coupe est un filet, pas une habitude.
test("chaque article a un titre et une description qui tiennent", () => {
  for (const a of ARTICLES) {
    assert.ok(a.titreSeo.length <= place, `${a.slug} : titre de ${a.titreSeo.length} caractères`);
    assert.ok(a.description.length >= DESCRIPTION_MIN && a.description.length <= DESCRIPTION_MAX, `${a.slug} : description de ${a.description.length}`);
  }
});

test("chaque guide a une description qui tient", () => {
  for (const g of GUIDES) assert.ok(g.description.length >= DESCRIPTION_MIN && g.description.length <= DESCRIPTION_MAX, `${g.slug} : ${g.description.length}`);
});

test("chaque terme du glossaire donne un titre qui tient, sans être coupé", () => {
  for (const t of GLOSSAIRE) {
    const choisi = titre(`${t.terme} : définition`, t.terme);
    assert.ok(!choisi.endsWith("…"), `${t.slug} : terme trop long pour un titre (${t.terme.length})`);
    assert.ok(description(t.definition).length <= DESCRIPTION_MAX);
  }
});

test("aucune adresse en double dans les contenus", () => {
  for (const liste of [ARTICLES.map((a) => a.slug), GUIDES.map((g) => g.slug), GLOSSAIRE.map((t) => t.slug)])
    assert.equal(new Set(liste).size, liste.length);
});
