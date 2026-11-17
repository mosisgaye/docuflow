"""Le circuit en graphe, comme dans n8n : des étapes que l'on crée, reliées par des liens.

Un graphe :
    {"noeuds": [{"id", "type", "x", "y", "nom", ...}], "liens": [{"de", "vers", "sortie"}]}
Les types d'étapes :
    debut        fixe, unique (id « debut ») : la facture a été reçue, lue et contrôlée
    condition    deux sorties, « oui » et « non » ; porte une condition (si) au format des règles
    approbation  une sortie ; ajoute un niveau (comptable, directeur_financier, gerant)
    blocage      aucune sortie : la facture ne peut pas être approuvée ; porte un message
    fin          fixe, unique (id « fin ») : enregistrer dans Odoo

Pour une facture, le moteur parcourt le graphe depuis « debut » : à chaque condition il suit « oui »
ou « non », chaque approbation ajoute son niveau, un blocage arrête tout, « fin » termine.
Le résultat a la même forme que celui des règles (approbation.circuit) : les garanties ne changent
pas (niveaux approuvés dans l'ordre, une personne différente à chaque niveau, et sans aucun niveau
le comptable valide quand même).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from moteur.approbation import LIBELLES, NIVEAUX, Condition, Regle

NOEUDS_MAX = 80
ID = r"^[a-z0-9][a-z0-9_-]{0,39}$"


class Noeud(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=ID)
    type: Literal["debut", "condition", "approbation", "blocage", "fin"]
    x: float = Field(ge=-100_000, le=100_000)
    y: float = Field(ge=-100_000, le=100_000)
    nom: str = Field(default="", max_length=200)
    si: Condition | None = None  # condition
    niveau: Literal["comptable", "directeur_financier", "gerant"] | None = None  # approbation
    message: str | None = Field(default=None, max_length=300)  # blocage

    @model_validator(mode="after")
    def reglages_du_type(self):
        attendus = {"condition": "si", "approbation": "niveau", "blocage": "message"}
        for type_, champ in attendus.items():
            present = getattr(self, champ) is not None
            if self.type == type_ and not present:
                raise ValueError(f"Une étape « {type_} » demande « {champ} ».")
            if self.type != type_ and present:
                raise ValueError(f"« {champ} » ne s'emploie que sur une étape « {type_} ».")
        if self.type == "blocage" and not self.message.strip():
            raise ValueError("Un blocage dit pourquoi : son message ne peut pas être vide.")
        if self.type in ("debut", "fin") and self.id != self.type:
            raise ValueError(f"L'étape « {self.type} » porte l'identifiant « {self.type} ».")
        return self


class Lien(BaseModel):
    model_config = ConfigDict(extra="forbid")

    de: str = Field(pattern=ID)
    vers: str = Field(pattern=ID)
    sortie: Literal["oui", "non"] | None = None


class GrapheInvalide(ValueError):
    """Un graphe refusé : le message dit, en français, quelle étape pose problème."""


def _nom(noeud: Noeud) -> str:
    return noeud.nom.strip() or {"debut": "Début", "fin": "Odoo", "condition": "Condition", "approbation": LIBELLES.get(noeud.niveau or "", "Approbation"), "blocage": "Blocage"}[noeud.type]


class Graphe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    noeuds: list[Noeud] = Field(min_length=2, max_length=NOEUDS_MAX)
    liens: list[Lien] = Field(max_length=NOEUDS_MAX * 2)

    @model_validator(mode="after")
    def bien_forme(self):
        par_id: dict[str, Noeud] = {}
        for noeud in self.noeuds:
            if noeud.id in par_id:
                raise ValueError(f"Deux étapes portent l'identifiant « {noeud.id} ».")
            par_id[noeud.id] = noeud
        for fixe in ("debut", "fin"):
            if sum(n.type == fixe for n in self.noeuds) != 1:
                raise ValueError(f"Le circuit a exactement une étape « {'Début' if fixe == 'debut' else 'Odoo'} ».")

        sorties: dict[str, list[Lien]] = {n.id: [] for n in self.noeuds}
        entrees: dict[str, int] = {n.id: 0 for n in self.noeuds}
        vus = set()
        for lien in self.liens:
            if lien.de not in par_id or lien.vers not in par_id:
                raise ValueError("Un lien relie une étape qui n'existe pas.")
            if lien.de == lien.vers:
                raise ValueError(f"L'étape « {_nom(par_id[lien.de])} » est reliée à elle-même.")
            cle = (lien.de, lien.sortie)
            if cle in vus:
                raise ValueError(f"L'étape « {_nom(par_id[lien.de])} » a deux liens sur la même sortie.")
            vus.add(cle)
            sorties[lien.de].append(lien)
            entrees[lien.vers] += 1

        for noeud in self.noeuds:
            nom, siennes = _nom(noeud), sorties[noeud.id]
            if noeud.type == "debut" and entrees[noeud.id]:
                raise ValueError("Rien ne peut revenir au Début.")
            if noeud.type == "condition":
                if sorted(lien.sortie or "" for lien in siennes) != ["non", "oui"]:
                    raise ValueError(f"La condition « {nom} » doit avoir une sortie Oui et une sortie Non.")
            elif noeud.type in ("blocage", "fin"):
                if siennes:
                    raise ValueError(f"« {nom} » termine le circuit : rien ne la suit.")
            elif len(siennes) != 1 or siennes[0].sortie is not None:
                raise ValueError(f"L'étape « {nom} » doit avoir une seule sortie, reliée à l'étape suivante.")

        # Toutes les étapes sont atteintes depuis le Début, et aucun chemin ne tourne en rond.
        atteintes: set[str] = set()
        en_cours: set[str] = set()

        def visiter(identifiant: str) -> None:
            if identifiant in en_cours:
                raise ValueError(f"Le circuit tourne en rond autour de « {_nom(par_id[identifiant])} ».")
            if identifiant in atteintes:
                return
            en_cours.add(identifiant)
            for lien in sorties[identifiant]:
                visiter(lien.vers)
            en_cours.discard(identifiant)
            atteintes.add(identifiant)

        visiter("debut")
        # Odoo peut rester hors d'atteinte : un circuit où tout chemin bloque est un choix possible (« en pause »).
        oubliees = [_nom(n) for n in self.noeuds if n.id not in atteintes and n.type != "fin"]
        if oubliees:
            raise ValueError(f"Étape non reliée au circuit : {', '.join(oubliees)}.")
        return self

    def suivant(self, identifiant: str, sortie: str | None = None) -> str:
        return next(lien.vers for lien in self.liens if lien.de == identifiant and lien.sortie == sortie)

    def noeud(self, identifiant: str) -> Noeud:
        return next(n for n in self.noeuds if n.id == identifiant)


class Esquisse(BaseModel):
    """Un graphe en cours de construction : chaque étape est bien réglée, mais tout n'est pas encore relié.

    C'est ce que le brouillon accepte (comme n8n garde un workflow inachevé). La publication, elle,
    exige un Graphe complet.
    """

    model_config = ConfigDict(extra="forbid")

    noeuds: list[Noeud] = Field(min_length=2, max_length=NOEUDS_MAX)
    liens: list[Lien] = Field(max_length=NOEUDS_MAX * 2)

    @model_validator(mode="after")
    def coherente(self):
        ids = [n.id for n in self.noeuds]
        if len(set(ids)) != len(ids):
            raise ValueError("Deux étapes portent le même identifiant.")
        for fixe in ("debut", "fin"):
            if sum(n.type == fixe for n in self.noeuds) != 1:
                raise ValueError(f"Le circuit a exactement une étape « {'Début' if fixe == 'debut' else 'Odoo'} ».")
        if any(lien.de not in ids or lien.vers not in ids for lien in self.liens):
            raise ValueError("Un lien relie une étape qui n'existe pas.")
        return self


def _message(erreur: ValidationError) -> str:
    premiere = erreur.errors()[0]
    message = premiere["msg"].removeprefix("Value error, ")
    if premiere["type"] != "value_error":
        chemin = " › ".join(str(p + 1) if isinstance(p, int) else str(p) for p in premiere["loc"])
        message = f"{chemin} : {message}"
    return message


def verifier_esquisse(graphe: dict) -> tuple[Esquisse, str | None]:
    """L'esquisse vérifiée, et ce qui reste à compléter pour la publier (None : le circuit est complet).

    Une étape mal réglée (montant illisible, message vide…) est refusée tout de suite : GrapheInvalide.
    """
    try:
        esquisse = Esquisse.model_validate(graphe)
    except ValidationError as erreur:
        raise GrapheInvalide(_message(erreur)) from erreur
    try:
        Graphe.model_validate(esquisse.model_dump(mode="json"))
    except ValidationError as erreur:
        return esquisse, _message(erreur)
    return esquisse, None


def verifier(graphe: dict) -> Graphe:
    """Le graphe vérifié, ou GrapheInvalide avec un message clair."""
    try:
        return Graphe.model_validate(graphe)
    except ValidationError as erreur:
        raise GrapheInvalide(_message(erreur)) from erreur


def parcourir(graphe: Graphe, donnees: dict, anomalies: list[dict]) -> dict:
    """Le chemin d'une facture dans le graphe : les étapes traversées, les niveaux exigés, le blocage."""
    chemin: list[dict] = []
    raisons: dict[str, list[str]] = {}
    bloque = None
    identifiant = "debut"
    while True:
        noeud = graphe.noeud(identifiant)
        if noeud.type == "condition":
            vraie = noeud.si.vraie(donnees, anomalies)
            chemin.append({"id": noeud.id, "sortie": "oui" if vraie else "non"})
            identifiant = graphe.suivant(noeud.id, "oui" if vraie else "non")
            continue
        chemin.append({"id": noeud.id, "sortie": None})
        if noeud.type == "approbation":
            raisons.setdefault(noeud.niveau, []).append(_nom(noeud))
        elif noeud.type == "blocage":
            bloque = f"{_nom(noeud)} : {noeud.message}"
            break
        elif noeud.type == "fin":
            break
        identifiant = graphe.suivant(noeud.id)
    niveaux = [{"niveau": niveau, "raisons": raisons[niveau]} for niveau in NIVEAUX if niveau in raisons]
    return {"niveaux": niveaux or [{"niveau": "comptable", "raisons": ["Aucune approbation sur ce chemin"]}], "bloque": bloque, "chemin": chemin}


def etapes_lisibles(graphe: Graphe, chemin: list[dict]) -> list[dict]:
    """Le chemin d'une facture en clair : le nom de chaque étape, la question posée et la réponse."""
    from moteur.editeur_circuit import resume_condition  # l'éditeur s'appuie sur ce module

    etapes = []
    for pas in chemin:
        noeud = graphe.noeud(pas["id"])
        etapes.append({
            "id": noeud.id,
            "type": noeud.type,
            "nom": _nom(noeud),
            "sortie": pas["sortie"],
            "condition": resume_condition(noeud.si.model_dump(mode="json", exclude_none=True)) if noeud.type == "condition" else None,
            "niveau": noeud.niveau,
            "message": noeud.message,
        })
    return etapes


def depuis_regles(regles: list[dict]) -> dict:
    """Un graphe qui donne le même circuit que ces règles (pour ouvrir dans l'éditeur une version d'avant).

    Les règles de blocage d'abord, puis les approbations, chacune à la suite de la précédente :
    une condition dont le « oui » mène à l'action, et dont le « non » passe à la règle suivante.
    Une règle « toujours » devient directement son action.
    """
    pas = 200  # écart entre deux colonnes du canevas ; une action se pose à mi-chemin, dessous (ou dessus)
    noeuds: list[dict] = [{"id": "debut", "type": "debut", "x": 0, "y": 0, "nom": "Début"}]
    liens: list[dict] = []
    precedents: list[tuple[str, str | None]] = [("debut", None)]  # ce qui mène à l'étape suivante
    colonne = 1

    def relier(vers: str) -> None:
        for de, sortie in precedents:
            liens.append({"de": de, "vers": vers, "sortie": sortie})

    regles_verifiees = [(brute, Regle.model_validate(brute)) for brute in regles]
    ordre = [r for r in regles_verifiees if r[1].bloque] + [r for r in regles_verifiees if not r[1].bloque]
    for rang, (brute, regle) in enumerate(ordre, start=1):
        x = colonne * pas
        if regle.bloque:
            arret = {"id": f"r{rang}-blocage", "type": "blocage", "x": x + pas // 2, "y": -160, "nom": regle.nom, "message": regle.bloque}
            if regle.si.toujours:  # toute facture est bloquée : la suite ne sert plus
                noeuds.append({**arret, "y": 0})
                relier(arret["id"])
                precedents = []
                break
            condition = {"id": f"r{rang}", "type": "condition", "x": x, "y": 0, "nom": regle.nom, "si": brute["si"]}
            noeuds += [condition, arret]
            relier(condition["id"])
            liens.append({"de": condition["id"], "vers": arret["id"], "sortie": "oui"})
            precedents = [(condition["id"], "non")]
            colonne += 1
            continue
        actions = [{"id": f"r{rang}-{niveau}", "type": "approbation", "x": x + pas // 2 + 140 * i, "y": 160, "nom": regle.nom, "niveau": niveau} for i, niveau in enumerate(regle.exige)]
        if regle.si.toujours:
            for i, action in enumerate(actions):
                action["x"], action["y"] = x + 140 * i, 0
            colonne += len(actions) - 1
            relier(actions[0]["id"])
            precedents = []
        else:
            condition = {"id": f"r{rang}", "type": "condition", "x": x, "y": 0, "nom": regle.nom, "si": brute["si"]}
            noeuds.append(condition)
            relier(condition["id"])
            liens.append({"de": condition["id"], "vers": actions[0]["id"], "sortie": "oui"})
            precedents = [(condition["id"], "non")]
        for avant, apres in zip(actions, actions[1:]):
            liens.append({"de": avant["id"], "vers": apres["id"], "sortie": None})
        noeuds += actions
        precedents.append((actions[-1]["id"], None))
        colonne += 1

    noeuds.append({"id": "fin", "type": "fin", "x": colonne * pas, "y": 0, "nom": "Enregistrer dans Odoo"})
    relier("fin")
    return {"noeuds": noeuds, "liens": liens}
