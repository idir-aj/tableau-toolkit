"""
lineage_engine.py — Usage et lignage des champs d'un classeur Tableau.

Pour chaque champ (source, calculé, paramètre, groupe), le moteur cherche où il est utilisé :
  - dans un autre calcul, un groupe, ou la valeur par défaut d'un paramètre (`default-value-field`)
  - dans une feuille (shelves, filtres, encodages, titres), un dashboard (filtres, contrôles de paramètre)
  - dans une action (filtre, lien, paramètre)
  - dans une jointure/relation du modèle de données
  - dans une règle de visibilité dynamique de zone (section <datagraph> du classeur)

Il en déduit :
  - les champs utilisés (directement, ou via un calcul lui-même utilisé),
  - les champs inutilisés (aucune référence, ou référencés seulement par des éléments inutilisés = « cascade »),
  - les champs « intermédiaires » (utilisés uniquement dans d'autres calculs, jamais directement),
  - un graphe de lignage : sources → niveaux de calcul → feuilles/actions/visibilité → dashboards.

Choix volontaires :
  - Les groupes automatiques de Tableau (`auto-column="sheet_link"`, ex. « Action (…) », « Tooltip (…) »)
    servent à la propagation mais ne sont jamais signalés comme inutilisés.
  - L'état d'interface enregistré (<windows> : surbrillance, sélection) n'est pas un usage.
  - Un champ rangé seulement dans un dossier ou une hiérarchie n'est pas considéré comme utilisé.
"""

import json
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

from utils import parser_xml

USER_NS = "{http://www.tableausoftware.com/xml/user}"
PARAM_DS = "Parameters"
KINDS_RACINE = {"sheet", "dashboard", "action", "join", "dzv"}
KINDS_COSMETIQUES = {"folder", "hier"}

_QUALIFIE = re.compile(r"\[([^\[\]]+)\]\.\[([^\[\]]+)\]")
_JETON = re.compile(r"\[([^\[\]]+)\]")


# ═══════════════════════════════════════════════════════════════
# Utilitaires XML
# ═══════════════════════════════════════════════════════════════

def _texte(el, ignorer=()) -> str:
    """Concatène attributs et textes d'un élément et de ses descendants (hors balises ignorées)."""
    morceaux = []

    def rec(e):
        if not isinstance(e.tag, str) or e.tag in ignorer:
            return
        morceaux.extend(e.attrib.values())
        if e.text and e.text.strip():
            morceaux.append(e.text)
        for c in e:
            rec(c)

    rec(el)
    return "\n".join(morceaux)


def _sans_commentaires(formule: str) -> str:
    return re.sub(r"//[^\n]*", "", formule or "")


def _court(nom_table: str) -> str:
    """Nom lisible d'une table (retire le suffixe technique entre parenthèses)."""
    return (nom_table or "").strip("[]").split(" (")[0]


# ═══════════════════════════════════════════════════════════════
# Analyse
# ═══════════════════════════════════════════════════════════════

class _Index:
    """Résout des références textuelles ([ds].[champ], [champ], [none:champ:nk]) vers des ids de champs."""

    def __init__(self, champs: dict):
        self.par_ds = defaultdict(set)
        self.par_nom = defaultdict(set)
        for fid, f in champs.items():
            self.par_ds[f["ds"]].add(f["name"])
            self.par_nom[f["name"]].add(f["ds"])

    @staticmethod
    def _candidats(interne: str):
        yield interne
        if ":" in interne:
            for p in interne.split(":"):
                if p:
                    yield p

    def resoudre(self, texte: str, ds_defaut: str | None = None) -> set:
        trouves = set()
        for m in _QUALIFIE.finditer(texte):
            ds, interne = m.group(1), m.group(2)
            for c in self._candidats(interne):
                if c in self.par_ds.get(ds, ()):
                    trouves.add(f"{ds}::{c}")
        reste = _QUALIFIE.sub(" ", texte)
        for m in _JETON.finditer(reste):
            for c in self._candidats(m.group(1)):
                if ds_defaut and c in self.par_ds.get(ds_defaut, ()):
                    trouves.add(f"{ds_defaut}::{c}")
                elif len(self.par_nom.get(c, ())) == 1:
                    trouves.add(f"{next(iter(self.par_nom[c]))}::{c}")
        return trouves


def analyser_classeur(xml_content) -> dict:
    """Analyse complète d'un classeur (.twb). Retourne un dict exploité par les autres fonctions."""
    root = parser_xml(xml_content).getroot()
    datasources = root.find("datasources")
    if datasources is None:
        raise ValueError("Aucune source de données dans ce classeur.")

    # ── 1. Univers des champs ────────────────────────────────────
    champs: dict[str, dict] = {}
    ds_elems = {}
    for d in datasources.findall("datasource"):
        ds = d.get("name")
        if not ds:
            continue
        ds_elems[ds] = d
        physiques = {}
        for mr in d.iter("metadata-record"):
            if mr.get("class") != "column":
                continue
            ln = (mr.findtext("local-name") or "").strip("[]")
            if ln and "__tableau_internal_object_id__" not in ln:
                physiques[ln] = _court(mr.findtext("parent-name"))
        for c in d.findall("column"):
            nom = (c.get("name") or "").strip("[]")
            if not nom or "__tableau_internal_object_id__" in nom:
                continue
            calc = c.find("calculation")
            est_param = ds == PARAM_DS
            if est_param:
                type_ = "param"
            elif calc is not None:
                type_ = "calc"
            elif nom in physiques:
                type_ = "source"
            else:
                type_ = "orphan"
            champs[f"{ds}::{nom}"] = {
                "id": f"{ds}::{nom}", "ds": ds, "name": nom, "type": type_,
                "caption": c.get("caption") or nom, "datatype": c.get("datatype") or "",
                "hidden": c.get("hidden") == "true", "formula": (calc.get("formula") if calc is not None else "") or "",
                "table": physiques.get(nom, ""), "auto": False, "folder": "",
                "_elem": c,
            }
        for nom, table in physiques.items():
            fid = f"{ds}::{nom}"
            if fid not in champs:
                champs[fid] = {
                    "id": fid, "ds": ds, "name": nom, "type": "source", "caption": nom, "datatype": "",
                    "hidden": False, "formula": "", "table": table, "auto": False, "folder": "", "_elem": None,
                }
        for g in d.findall("group"):
            nom = (g.get("name") or "").strip("[]")
            if not nom:
                continue
            champs[f"{ds}::{nom}"] = {
                "id": f"{ds}::{nom}", "ds": ds, "name": nom, "type": "group",
                "caption": g.get("caption") or nom, "datatype": "", "hidden": g.get("hidden") == "true",
                "formula": "", "table": "", "auto": g.get(USER_NS + "auto-column") == "sheet_link",
                "folder": "", "_elem": g,
            }

    idx = _Index(champs)
    refs = defaultdict(lambda: defaultdict(set))   # champ -> kind -> {où}
    deps = defaultdict(set)                         # champ -> champs dont il dépend

    def noter(texte, kind, ou, ds_defaut=None, exclure=None):
        for fid in idx.resoudre(texte, ds_defaut):
            if fid != exclure:
                refs[fid][kind].add(ou)

    # ── 2. Dépendances entre champs (calculs, groupes, paramètres alimentés par un champ) ──
    for fid, f in champs.items():
        e = f["_elem"]
        if f["type"] == "calc":
            cibles = idx.resoudre(_sans_commentaires(f["formula"]), f["ds"])
        elif f["type"] == "group" and e is not None:
            cibles = idx.resoudre(_texte(e), f["ds"])
        else:
            cibles = set()
        if f["type"] in ("param", "calc", "source") and e is not None and not isinstance(e, str):
            autres = [v for k, v in e.attrib.items() if k != "name"]
            for ch in e:
                if ch.tag != "calculation":
                    autres.append(_texte(ch))
            cibles |= idx.resoudre("\n".join(autres), f["ds"])
        cibles.discard(fid)
        for c in cibles:
            deps[fid].add(c)
            refs[c]["calc" if f["type"] != "group" else "group"].add(fid)

    # ── 3. Dossiers, hiérarchies, jointures (par source de données) ──
    for ds, d in ds_elems.items():
        fc = d.find("folders-common")
        if fc is not None:
            for fo in fc.findall("folder"):
                for it in fo.findall("folder-item"):
                    fid = f"{ds}::{(it.get('name') or '').strip('[]')}"
                    if fid in champs:
                        champs[fid]["folder"] = fo.get("name") or ""
                        refs[fid]["folder"].add(fo.get("name") or "")
        dp = d.find("drill-paths")
        if dp is not None:
            noter(_texte(dp), "hier", "hierarchy", ds)
        og = d.find("object-graph")
        if og is not None:
            for rel in og.iter("relationship"):
                noter(_texte(rel), "join", "relationship", ds)

    # ── 4. Feuilles, dashboards, actions, visibilité dynamique ───
    feuilles = [w.get("name") for w in root.findall("worksheets/worksheet")]
    usages = {"sheet": set(), "dash": set(), "action": set(), "zone": {}}
    liens_feuille_dash = defaultdict(set)

    for w in root.findall("worksheets/worksheet"):
        nom = w.get("name")
        for dep in w.iter("datasource-dependencies"):
            ds = dep.get("datasource")
            for ci in dep.findall("column-instance"):
                fid = f"{ds}::{(ci.get('column') or '').strip('[]')}"
                if fid in champs:
                    refs[fid]["sheet"].add(nom)
        noter(_texte(w, ignorer=("datasource-dependencies", "style")), "sheet", nom)

    zones = {}
    uuid_dash = {}
    for dash in root.findall("dashboards/dashboard"):
        nom = dash.get("name")
        sid = dash.find("simple-id")
        if sid is not None:
            uuid_dash[sid.get("uuid")] = nom
        for z in dash.iter("zone"):
            zones[(nom, z.get("id"))] = z.get("name") or z.get("friendly-name") or z.get("type-v2") or "zone"
            if z.get("name") in feuilles:
                liens_feuille_dash[z.get("name")].add(nom)
        noter(_texte(dash, ignorer=("datasource-dependencies", "style")), "dashboard", nom)

    actions = root.find("actions")
    if actions is not None:
        for a in actions:
            noter(_texte(a), "action", a.get("caption") or a.get("name") or "action")

    dg = root.find("datagraph")
    if dg is not None:
        noeuds = dg.find(".//nodes")
        aretes = dg.find(".//edges")
        if noeuds is not None and aretes is not None:
            sortie_champ, entree_zone = {}, {}
            for n in noeuds:
                if n.tag == "single-value-field-node":
                    sortie_champ[n.get("value-output-guid")] = n.get("fieldname") or ""
                elif n.tag == "dashboard-zone-visibility-node":
                    entree_zone[n.get("visibility-input-guid")] = (uuid_dash.get(n.get("dashboard-identifier")), n.get("zone-id"))
            for e in aretes:
                champ, zone = sortie_champ.get(e.get("from")), entree_zone.get(e.get("to"))
                if champ and zone:
                    for fid in idx.resoudre(champ):
                        refs[fid]["dzv"].add(f"{zone[0]} › {zones.get(zone, 'zone ' + str(zone[1]))}")

    # ── 5. Propagation : un champ est utilisé s'il est utilisé directement, ou par un champ utilisé ──
    vivants = {fid for fid in champs if set(refs[fid]) & KINDS_RACINE}
    pile = list(vivants)
    while pile:
        for c in deps.get(pile.pop(), ()):
            if c not in vivants:
                vivants.add(c)
                pile.append(c)

    statuts = {}
    for fid, f in champs.items():
        if f["auto"]:
            continue
        kinds = set(refs[fid])
        if fid in vivants:
            statuts[fid] = "intermediate" if not (kinds & KINDS_RACINE) else "used"
        elif not kinds:
            statuts[fid] = "unused"
        elif kinds <= KINDS_COSMETIQUES:
            statuts[fid] = "cosmetic"
        else:
            statuts[fid] = "cascade"

    for f in champs.values():
        f.pop("_elem", None)
    return {
        "champs": champs, "refs": {k: {kk: sorted(map(str, vv)) for kk, vv in v.items()} for k, v in refs.items()},
        "deps": {k: sorted(v) for k, v in deps.items()}, "vivants": vivants, "statuts": statuts,
        "feuilles": feuilles, "feuilles_dashboards": {k: sorted(v) for k, v in liens_feuille_dash.items()},
        "dashboards": [d.get("name") for d in root.findall("dashboards/dashboard")],
        "feuilles_hors_dashboard": [s for s in feuilles if s not in liens_feuille_dash],
    }


def champs_inutilises(analyse: dict) -> list[dict]:
    """Liste des champs inutilisés : type, statut (unused/cascade/cosmetic), nom affiché, nom interne, etc."""
    sortie = []
    for fid, st in analyse["statuts"].items():
        if st not in ("unused", "cascade", "cosmetic"):
            continue
        f = analyse["champs"][fid]
        note = ""
        if st in ("cascade", "cosmetic"):
            ref = analyse["refs"].get(fid, {})
            parents = sorted({analyse["champs"][p]["caption"] for p in ref.get("calc", []) + ref.get("group", []) if p in analyse["champs"]})
            if parents:
                note = ", ".join(parents[:6]) + ("…" if len(parents) > 6 else "")
            elif ref.get("folder"):
                note = ", ".join(ref["folder"])
        sortie.append({
            "type": f["type"], "statut": st, "nom": f["caption"], "interne": f["name"], "datatype": f["datatype"],
            "masque": f["hidden"], "table": f["table"], "dossier": f["folder"], "note": note, "formule": f["formula"],
        })
    ordre = {"param": 0, "calc": 1, "group": 2, "source": 3, "orphan": 4}
    sortie.sort(key=lambda r: (ordre.get(r["type"], 9), r["statut"], r["nom"].lower()))
    return sortie


# ═══════════════════════════════════════════════════════════════
# Graphe de lignage
# ═══════════════════════════════════════════════════════════════

def construire_graphe(analyse: dict) -> dict:
    """Nœuds (champs utilisés + usages) et liens, avec colonne et position verticale calculées."""
    champs, refs, deps = analyse["champs"], analyse["refs"], analyse["deps"]
    gardes = {fid for fid, st in analyse["statuts"].items() if st in ("used", "intermediate") and champs[fid]["type"] != "orphan"}
    # Les groupes automatiques utilisés servent de relais : on relie leurs dépendances aux usages à leur place.
    noeuds, aretes = {}, set()
    for fid in gardes:
        f = champs[fid]
        noeuds[fid] = {
            "id": fid, "kind": f["type"], "label": f["caption"].strip(), "name": f["name"],
            "inter": analyse["statuts"][fid] == "intermediate", "hidden": f["hidden"],
            "formula": re.sub(r"[ \t]+\n", "\n", f["formula"])[:700], "dt": f["datatype"],
            "tbl": f["table"], "folder": f["folder"],
        }
        for d in deps.get(fid, ()):
            if d in gardes:
                aretes.add((d, fid))

    def usage(uid, kind, label):
        noeuds.setdefault(uid, {"id": uid, "kind": kind, "label": label, "name": label})
        return uid

    for fid in gardes:
        r = refs.get(fid, {})
        for s in r.get("sheet", []):
            if s in analyse["feuilles"]:
                sid = usage("S:" + s, "sheet", s)
                aretes.add((fid, sid))
                for dn in analyse["feuilles_dashboards"].get(s, ()):
                    aretes.add((sid, usage("D:" + dn, "dash", dn)))
        for dn in r.get("dashboard", []):
            if dn in analyse["dashboards"]:
                aretes.add((fid, usage("D:" + dn, "dash", dn)))
        for a in r.get("action", []):
            aretes.add((fid, usage("A:" + a, "action", a)))
        for z in r.get("dzv", []):
            aretes.add((fid, usage("Z:" + z, "zone", z)))
        if "join" in r:
            aretes.add((fid, usage("J:rel", "join", "Relations")))

    # profondeur
    profondeur = {}

    def prof(n, pile=()):
        if n in profondeur:
            return profondeur[n]
        if n in pile:
            return 0
        ds = [d for d in deps.get(n, ()) if d in gardes]
        profondeur[n] = 0 if not ds else 1 + max(prof(d, pile + (n,)) for d in ds)
        return profondeur[n]

    for n in gardes:
        prof(n)
    D = max(profondeur.values(), default=0)
    UL = D + 1
    col = {n: profondeur[n] for n in gardes}
    for nid, v in noeuds.items():
        if v["kind"] in ("sheet", "action", "zone", "join"):
            col[nid] = UL
        elif v["kind"] == "dash":
            col[nid] = UL + 1

    # ordre vertical : tri initial, balayages barycentriques, puis relaxation avec espacement minimal
    voisins = defaultdict(list)
    for a, b in aretes:
        voisins[a].append(b)
        voisins[b].append(a)
    groupe_usage = {"dash": 0, "sheet": 1, "action": 2, "zone": 3, "join": 4}
    colonnes = defaultdict(list)
    for nid in noeuds:
        colonnes[col[nid]].append(nid)

    def cle0(nid):
        v = noeuds[nid]
        if col[nid] >= UL:
            return (groupe_usage[v["kind"]], v["label"].lower())
        rang = {"param": 0, "source": 1}.get(v["kind"], 2) if col[nid] == 0 else 0
        return (rang, v.get("folder", ""), v["label"].lower())

    pos = {}
    for c, l in colonnes.items():
        l.sort(key=cle0)
        pos.update({n: i for i, n in enumerate(l)})
    for it in range(6):
        for c in (sorted(colonnes) if it % 2 == 0 else sorted(colonnes, reverse=True)):
            if c == UL:
                continue
            l = colonnes[c]

            def bc(n):
                ps = [pos[m] / max(1, len(colonnes[col[m]])) for m in voisins[n] if col[m] != c]
                return sum(ps) / len(ps) if ps else pos[n] / max(1, len(l))

            l.sort(key=bc)
            pos.update({n: i for i, n in enumerate(l)})
    if UL in colonnes:
        def bc2(n):
            ps = [pos[m] / max(1, len(colonnes[col[m]])) for m in voisins[n] if col[m] < UL]
            return (groupe_usage[noeuds[n]["kind"]], sum(ps) / len(ps) if ps else 0)
        colonnes[UL].sort(key=bc2)
        pos.update({n: i for i, n in enumerate(colonnes[UL])})

    RH = 25
    y = {n: pos[n] * RH for n in noeuds}
    tries = {c: sorted(l, key=lambda n: pos[n]) for c, l in colonnes.items()}

    def relaxer(c):
        l = tries[c]
        des = {}
        for n in l:
            ys = [y[m] for m in voisins[n] if col[m] != c]
            des[n] = sum(ys) / len(ys) if ys else y[n]
        cur = None
        for n in l:
            t = des[n]
            if cur is not None and t < cur + RH:
                t = cur + RH
            y[n], cur = t, t
        cur = None
        for n in reversed(l):
            t = y[n]
            if cur is not None and t > cur - RH:
                t = cur - RH
            cand = max(t, des[n])
            y[n] = cand if (cur is None or cand <= cur - RH) else t
            cur = y[n]

    ordre_cols = sorted(colonnes)
    for it in range(10):
        for c in (ordre_cols[1:] if it % 2 == 0 else ordre_cols[::-1][:-1]):
            relaxer(c)
    if y:
        mn = min(y.values())
        for n in y:
            y[n] -= mn
    for c, l in tries.items():
        cur = -RH
        for n in l:
            if y[n] < cur + RH:
                y[n] = cur + RH
            cur = y[n]

    return {
        "nodes": [dict(v, col=col[n], y=round(y[n], 1)) for n, v in noeuds.items()],
        "edges": sorted([a, b] for a, b in aretes if a in noeuds and b in noeuds),
        "maxdepth": D,
    }


# ═══════════════════════════════════════════════════════════════
# Sorties : page HTML autonome, Excel
# ═══════════════════════════════════════════════════════════════

LIBELLES_HTML = {
    "fr": {
        "title": "Lignage des champs",
        "intro": "Du champ source jusqu'à son usage : chaque colonne est un niveau de calcul, les dernières colonnes montrent où les champs servent (feuilles, actions, visibilité des zones, dashboards).",
        "search": "Rechercher un champ", "search_ph": "ex. NQC, Hierarchy, supplier",
        "dash_filter": "Remonter depuis un dashboard", "all_dash": "Tous les dashboards",
        "focus": "Focus sur la sélection", "unfocus": "Quitter le focus", "fullscreen": "Plein écran", "exit_fullscreen": "Quitter le plein écran",
        "labels": "Libellés", "caption": "Libellé", "internal": "Nom interne", "reset": "Tout réafficher",
        "lg_source": "Champ de la source", "lg_param": "Paramètre", "lg_calc": "Calcul ou groupe",
        "lg_inter": "Intermédiaire (à masquer)", "lg_use": "Usage : feuille ▪ action ▲ visibilité ● jointure ◆ dashboard",
        "hint": "Survole un champ pour voir d'où il vient et où il sert. Clique pour le figer, double-clique pour isoler son lignage.",
        "col_src": "Sources", "col_src_sub": "champs & paramètres", "col_calc": "Calculs", "col_level": "niveau",
        "col_use": "Usages", "col_use_sub": "feuilles, actions, visibilité", "col_dash": "Dashboards", "col_dash_sub": "où tout aboutit",
        "k_source": "Champ de la source", "k_param": "Paramètre", "k_calc": "Champ calculé", "k_group": "Groupe",
        "k_sheet": "Feuille", "k_action": "Action", "k_zone": "Visibilité dynamique d'une zone", "k_join": "Jointure", "k_dash": "Dashboard",
        "i_internal": "Nom interne", "i_folder": "Dossier", "i_table": "Table", "i_inter": "Intermédiaire : jamais utilisé directement dans une feuille, un dashboard ou une action",
        "i_hidden": "Déjà masqué", "i_up": "En amont : {a} champ(s) dont {s} de la source",
        "i_down": "En aval : {sh} feuille(s), {da} dashboard(s), {ac} action(s), {zo} zone(s) à visibilité dynamique",
        "i_nof": "Pas de formule (champ de la source ou paramètre).", "i_dash_hint": "Les champs qui l'alimentent sont mis en évidence.",
        "n_nodes": "{n} nœuds · {e} liens", "n_hi": "{n} nœud(s) en évidence",
    },
    "en": {
        "title": "Field lineage",
        "intro": "From source field to usage: each column is a calculation level, the last columns show where fields are used (sheets, actions, zone visibility, dashboards).",
        "search": "Search a field", "search_ph": "e.g. NQC, Hierarchy, supplier",
        "dash_filter": "Trace back from a dashboard", "all_dash": "All dashboards",
        "focus": "Focus on selection", "unfocus": "Exit focus", "fullscreen": "Fullscreen", "exit_fullscreen": "Exit fullscreen",
        "labels": "Labels", "caption": "Caption", "internal": "Internal name", "reset": "Reset view",
        "lg_source": "Source field", "lg_param": "Parameter", "lg_calc": "Calculation or group",
        "lg_inter": "Intermediate (hide it)", "lg_use": "Usage: sheet ▪ action ▲ visibility ● join ◆ dashboard",
        "hint": "Hover a field to see where it comes from and where it is used. Click to pin it, double-click to isolate its lineage.",
        "col_src": "Sources", "col_src_sub": "fields & parameters", "col_calc": "Calculations", "col_level": "level",
        "col_use": "Usage", "col_use_sub": "sheets, actions, visibility", "col_dash": "Dashboards", "col_dash_sub": "where it all ends",
        "k_source": "Source field", "k_param": "Parameter", "k_calc": "Calculated field", "k_group": "Group",
        "k_sheet": "Sheet", "k_action": "Action", "k_zone": "Dynamic zone visibility", "k_join": "Join", "k_dash": "Dashboard",
        "i_internal": "Internal name", "i_folder": "Folder", "i_table": "Table", "i_inter": "Intermediate: never used directly in a sheet, dashboard or action",
        "i_hidden": "Already hidden", "i_up": "Upstream: {a} field(s), {s} from the source",
        "i_down": "Downstream: {sh} sheet(s), {da} dashboard(s), {ac} action(s), {zo} zone(s) with dynamic visibility",
        "i_nof": "No formula (source field or parameter).", "i_dash_hint": "The fields feeding it are highlighted.",
        "n_nodes": "{n} nodes · {e} links", "n_hi": "{n} node(s) highlighted",
    },
}


def generer_html_lignage(graphe: dict, lang: str = "fr", titre: str = "") -> str:
    """Page HTML autonome (aucune dépendance externe) affichant le graphe de lignage interactif."""
    modele = (Path(__file__).parent / "lineage_template.html").read_text(encoding="utf-8")
    libs = LIBELLES_HTML.get(lang, LIBELLES_HTML["fr"])

    def js(obj):
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    return (modele.replace("__LANG__", lang)
                  .replace("__TITLE__", (titre or libs["title"]).replace("<", "&lt;"))
                  .replace("__I18N__", js(libs))
                  .replace("__DATA__", js(graphe)))


def exporter_excel(lignes: list[dict], colonnes: dict) -> bytes:
    """Exporte la liste des champs inutilisés en .xlsx. `colonnes` : {clé: libellé d'en-tête} (ordre conservé)."""
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.append(list(colonnes.values()))
    for r in lignes:
        ws.append([("Oui" if r[k] else "Non") if isinstance(r[k], bool) else r[k] for k in colonnes])
    fond = PatternFill("solid", fgColor="1F3A5F")
    for c in ws[1]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), fond
    for i, k in enumerate(colonnes, 1):
        ws.column_dimensions[get_column_letter(i)].width = 70 if k in ("formule", "note") else (45 if k in ("nom", "interne") else 22)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(vertical="top")
    out = BytesIO()
    wb.save(out)
    return out.getvalue()
