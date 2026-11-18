import { strict as assert } from "node:assert";
import { test } from "node:test";
import { cleTva, siretValide, verifierIban, verifierIdentifiant } from "./verifications.ts";

test("un IBAN juste passe, une faute de frappe est repérée", () => {
  const juste = verifierIban("fr76 3000 6000 0112 3456 7890 189");
  assert.equal(juste.valide, true);
  if (juste.valide) assert.equal(juste.groupes, "FR76 3000 6000 0112 3456 7890 189");
  assert.equal(verifierIban("FR76 3000 6000 0112 3456 7890 188").valide, false);
  assert.equal(verifierIban("DE89 3704 0044 0532 0130 00").valide, true);
  assert.equal(verifierIban("GB82 WEST 1234 5698 7654 32").valide, true);
});

test("un IBAN français de mauvaise longueur dit pourquoi", () => {
  const r = verifierIban("FR76 3000 6000 0112 3456 7890");
  assert.equal(r.valide, false);
  if (!r.valide) assert.match(r.raison, /27 caractères/);
});

test("SIRET, SIREN et numéro de TVA", () => {
  // SIREN de La Poste et un SIRET d'établissement : exceptions officielles.
  assert.equal(siretValide("35600000000010"), true); // somme des chiffres divisible par 5
  assert.equal(siretValide("73282932000074"), true);
  assert.equal(siretValide("73282932000075"), false);
  assert.equal(cleTva("732829320"), "44");
  const siret = verifierIdentifiant("732 829 320 00074");
  assert.equal(siret.valide, true);
  if (siret.valide) assert.equal(siret.tva, "FR44732829320");
  assert.equal(verifierIdentifiant("FR44732829320").valide, true);
  const fausse = verifierIdentifiant("FR45732829320");
  assert.equal(fausse.valide, false);
  if (!fausse.valide) assert.match(fausse.raison, /FR44732829320/);
});
