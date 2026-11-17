"""Comptes et connexion : lien ou code à usage unique, 15 minutes, essais limités, session signée."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from moteur import comptes
from moteur.base import DemandeConnexion

MAINTENANT = datetime(2026, 11, 17, 9, tzinfo=UTC)


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("VERIFAC_SECRET_SESSION", "s" * 40)


@pytest.fixture
def claire(session):
    return comptes.creer(session, "Claire Fabre", "Claire@Exemple.fr ", "membre", ["comptable"], "Moussa")


# ───────── Les comptes ─────────


def test_un_compte_se_cree_avec_une_adresse_normalisee(claire):
    assert claire.email == "claire@exemple.fr" and claire.niveaux == ["comptable"] and claire.actif


@pytest.mark.parametrize(
    ("nom", "email", "role", "niveaux", "message"),
    [
        ("", "a@b.fr", "membre", [], "1 à 100"),
        ("Paul", "pas-une-adresse", "membre", [], "n'est pas une adresse"),
        ("Paul", "paul@b.fr", "patron", [], "Rôle inconnu"),
        ("Paul", "paul@b.fr", "membre", ["stagiaire"], "Niveau d'approbation inconnu"),
        ("Paul", "paul@b.fr", "lecture", ["comptable"], "n'approuve pas"),
        ("Paul", "paul@b.fr", "operateur", ["gerant"], "n'approuve pas"),
    ],
)
def test_un_compte_mal_forme_est_refuse(session, nom, email, role, niveaux, message):
    with pytest.raises(comptes.CompteInvalide, match=message):
        comptes.creer(session, nom, email, role, niveaux, "Moussa")


def test_une_adresse_n_a_qu_un_compte(session, claire):
    with pytest.raises(comptes.CompteInvalide, match="déjà un compte"):
        comptes.creer(session, "Autre Claire", "CLAIRE@exemple.fr", "lecture", [], "Moussa")


def test_il_reste_toujours_un_administrateur(session):
    seul = comptes.creer(session, "Moussa", "moussa@exemple.fr", "administrateur", ["gerant"], "installation")

    for changement in ({"role": "membre"}, {"actif": False}):
        with pytest.raises(comptes.CompteInvalide, match="au moins un administrateur"):
            comptes.modifier(session, seul, **changement)

    comptes.creer(session, "Paul", "paul@exemple.fr", "administrateur", [], "Moussa")
    assert comptes.modifier(session, seul, role="membre").role == "membre"  # possible dès qu'un autre l'est


@pytest.mark.parametrize(
    ("role", "droits"),
    [
        ("administrateur", {"voir", "approuver", "traiter", "circuit", "agent", "administrer"}),
        ("membre", {"voir", "approuver", "traiter", "circuit", "agent"}),
        ("approbateur", {"voir", "approuver"}),
        ("lecture", {"voir"}),
        ("operateur", {"voir", "operer"}),
    ],
)
def test_chaque_role_a_ses_droits_et_pas_plus(session, role, droits):
    compte = comptes.creer(session, "X", f"{role}@exemple.fr", role, [], "Moussa")

    assert {droit for droit in comptes.DROITS if comptes.peut(compte, droit)} == droits


def test_l_operateur_n_approuve_jamais_et_ne_publie_jamais(session):
    operateur = comptes.creer(session, "Moussa (Verifac)", "support@verifac.company", "operateur", [], "installation")

    assert not comptes.peut(operateur, "approuver") and not comptes.peut(operateur, "administrer")


# ───────── La connexion ─────────


def test_se_connecter_par_le_lien(session, claire):
    envoi = comptes.demander(session, "claire@exemple.fr", MAINTENANT)

    assert envoi is not None and len(envoi.jeton) >= 40 and len(envoi.code) == 6
    assert comptes.par_lien(session, envoi.jeton, MAINTENANT + timedelta(minutes=5)) is claire
    assert claire.derniere_connexion is not None


def test_le_lien_ne_sert_qu_une_fois_et_expire(session, claire):
    premier = comptes.demander(session, "claire@exemple.fr", MAINTENANT)
    comptes.par_lien(session, premier.jeton, MAINTENANT)
    with pytest.raises(comptes.ConnexionRefusee):
        comptes.par_lien(session, premier.jeton, MAINTENANT)  # déjà utilisé

    second = comptes.demander(session, "claire@exemple.fr", MAINTENANT)
    with pytest.raises(comptes.ConnexionRefusee):
        comptes.par_lien(session, second.jeton, MAINTENANT + timedelta(minutes=16))  # expiré


def test_rien_n_est_garde_en_clair(session, claire):
    envoi = comptes.demander(session, "claire@exemple.fr", MAINTENANT)
    demande = session.scalar(select(DemandeConnexion))

    assert envoi.jeton not in (demande.empreinte_jeton, demande.empreinte_code)
    assert envoi.code not in (demande.empreinte_jeton, demande.empreinte_code)


def test_se_connecter_par_le_code_espaces_compris(session, claire):
    envoi = comptes.demander(session, "claire@exemple.fr", MAINTENANT)

    assert comptes.par_code(session, " CLAIRE@exemple.fr", f"{envoi.code[:3]} {envoi.code[3:]}", MAINTENANT) is claire


def test_cinq_codes_faux_et_c_est_fini(session, claire):
    envoi = comptes.demander(session, "claire@exemple.fr", MAINTENANT)
    faux = "000000" if envoi.code != "000000" else "111111"

    for _ in range(comptes.ESSAIS_CODE_MAX):
        with pytest.raises(comptes.ConnexionRefusee):
            comptes.par_code(session, "claire@exemple.fr", faux, MAINTENANT)
    with pytest.raises(comptes.ConnexionRefusee, match="n'est plus valable"):
        comptes.par_code(session, "claire@exemple.fr", envoi.code, MAINTENANT)  # même le bon code ne passe plus


def test_une_adresse_inconnue_ou_inactive_ne_recoit_rien(session, claire):
    assert comptes.demander(session, "inconnu@exemple.fr", MAINTENANT) is None
    comptes.creer(session, "Admin", "admin@exemple.fr", "administrateur", [], "installation")
    comptes.modifier(session, claire, actif=False)
    assert comptes.demander(session, "claire@exemple.fr", MAINTENANT) is None


def test_trois_demandes_au_plus_par_quart_d_heure(session, claire):
    envois = [comptes.demander(session, "claire@exemple.fr", MAINTENANT + timedelta(minutes=i)) for i in range(4)]

    assert all(envois[:3]) and envois[3] is None
    assert comptes.demander(session, "claire@exemple.fr", MAINTENANT + timedelta(minutes=20)) is not None


def test_sans_secret_la_connexion_est_refusee(session, claire, monkeypatch):
    monkeypatch.setenv("VERIFAC_SECRET_SESSION", "trop-court")

    with pytest.raises(comptes.ConnexionRefusee, match="pas configurée"):
        comptes.demander(session, "claire@exemple.fr", MAINTENANT)


# ───────── La session ─────────


def test_la_session_ouvre_et_se_ferme(session, claire):
    jeton = comptes.jeton_session(claire, MAINTENANT)

    assert comptes.lire_session(session, jeton, MAINTENANT + timedelta(days=29)) is claire
    assert comptes.lire_session(session, jeton, MAINTENANT + timedelta(days=31)) is None  # expirée


@pytest.mark.parametrize("abimer", [lambda j: j[:-2] + "xx", lambda j: "x" + j, lambda j: j.split(".")[0], lambda j: "", lambda j: None])
def test_une_session_falsifiee_ne_vaut_rien(session, claire, abimer):
    assert comptes.lire_session(session, abimer(comptes.jeton_session(claire, MAINTENANT)), MAINTENANT) is None


def test_deconnecter_partout_ou_desactiver_ferme_les_sessions(session, claire):
    comptes.creer(session, "Admin", "admin@exemple.fr", "administrateur", [], "installation")
    jeton = comptes.jeton_session(claire, MAINTENANT)

    comptes.deconnecter_partout(session, claire)
    assert comptes.lire_session(session, jeton, MAINTENANT) is None

    nouveau = comptes.jeton_session(claire, MAINTENANT)
    comptes.modifier(session, claire, role="lecture", niveaux=[])  # un rôle qui change : on se reconnecte
    assert comptes.lire_session(session, nouveau, MAINTENANT) is None


def test_un_autre_secret_invalide_les_sessions(session, claire, monkeypatch):
    jeton = comptes.jeton_session(claire, MAINTENANT)
    monkeypatch.setenv("VERIFAC_SECRET_SESSION", "t" * 40)

    assert comptes.lire_session(session, jeton, MAINTENANT) is None
