"""Versions des consignes données à l'IA.

Chaque consigne (texte + format de réponse imposé) reçoit une empreinte calculée
depuis son contenu. Modifier un seul caractère change l'empreinte : il est
impossible d'oublier de « monter la version ».

Le texte complet est gardé en base, une seule fois par version. Chaque lecture
par l'IA note l'empreinte utilisée : on peut toujours retrouver la consigne
exacte qui a produit une donnée, même des mois plus tard.
"""

import hashlib
import json
from dataclasses import dataclass
from functools import cached_property

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from moteur.base import Consigne


@dataclass(frozen=True)
class VersionConsigne:
    usage: str  # "extraction" ou "assistant"
    texte: str
    schema: dict | list

    @cached_property
    def empreinte(self) -> str:
        contenu = json.dumps({"usage": self.usage, "texte": self.texte, "schema": self.schema}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(contenu.encode("utf-8")).hexdigest()[:12]


def enregistrer(session: Session, version: VersionConsigne) -> str:
    """Garde le texte de la consigne s'il n'est pas déjà connu. Renvoie son empreinte."""
    session.execute(
        insert(Consigne)
        .values(id=version.empreinte, usage=version.usage, texte=version.texte, schema=version.schema)
        .on_conflict_do_nothing(index_elements=[Consigne.id])
    )
    return version.empreinte
