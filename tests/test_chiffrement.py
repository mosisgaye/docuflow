"""Changer la clé de chiffrement sans perdre les jetons des connecteurs ni les secrets des abonnements."""

import pytest
from cryptography.fernet import Fernet, InvalidToken

from moteur import chiffrement
from moteur.base import Abonnement, JetonConnecteur


@pytest.fixture
def cles(monkeypatch):
    ancienne, nouvelle = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setenv("CONNECTEURS_CLE_CHIFFREMENT", ancienne)
    return ancienne, nouvelle, monkeypatch


def test_sans_cle_il_n_y_a_pas_de_chiffreur():
    assert chiffrement.chiffreur() is None


def test_changer_de_cle_sans_rien_perdre(session, cles):
    ancienne, nouvelle, monkeypatch = cles
    outil = chiffrement.chiffreur()
    session.add(JetonConnecteur(connecteur="hubspot", acces=outil.encrypt(b"acces-1").decode(), renouvellement=outil.encrypt(b"renouv-1").decode()))
    session.add(Abonnement(url="https://exemple.test/crochet", evenements=["facture.validee"], secret=outil.encrypt(b"secret-1").decode(), actif=True, cree_par="test"))
    session.flush()

    # 1. Nouvelle clé en service, l'ancienne gardée pour relire : tout reste lisible.
    monkeypatch.setenv("CONNECTEURS_CLE_CHIFFREMENT", nouvelle)
    monkeypatch.setenv("CONNECTEURS_CLES_ANCIENNES", ancienne)
    jeton = session.get(JetonConnecteur, "hubspot")
    assert chiffrement.chiffreur().decrypt(jeton.acces.encode()) == b"acces-1"

    # 2. On rechiffre la base : 3 valeurs (accès, renouvellement, secret).
    assert chiffrement.rechiffrer(session) == 3
    session.flush()

    # 3. L'ancienne clé retirée : tout se relit avec la seule nouvelle clé.
    monkeypatch.delenv("CONNECTEURS_CLES_ANCIENNES")
    seule = chiffrement.chiffreur()
    abonnement = session.query(Abonnement).one()
    assert seule.decrypt(jeton.acces.encode()) == b"acces-1"
    assert seule.decrypt(jeton.renouvellement.encode()) == b"renouv-1"
    assert seule.decrypt(abonnement.secret.encode()) == b"secret-1"
    # et l'ancienne clé ne lit plus rien
    with pytest.raises(InvalidToken):
        Fernet(ancienne.encode()).decrypt(jeton.acces.encode())
