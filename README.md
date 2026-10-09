# 🧰 Tableau Toolkit

Boîte à outils [Streamlit](https://streamlit.io) pour **modifier et analyser des classeurs Tableau** (`.twb`, `.twbx`) et des sources de données (`.tds`) en agissant directement sur leur XML, sans ouvrir Tableau Desktop. Interface bilingue FR / EN.

## Outils

Un seul fichier est uploadé en haut de la page, puis partagé entre les onglets (sauf l'onglet Performances, qui a son propre upload).

| Onglet | Ce que ça fait | Fichiers | Module |
|---|---|---|---|
| 📐 **Redimensionner** | Change la résolution des dashboards (taille commune ou par dashboard) et repositionne automatiquement les objets. | `.twb`, `.twbx` | `resize_engine.py` |
| 🔽 **Formater les filtres** | Change le mode d'affichage des filtres, ajoute des filtres à un dashboard à partir d'une feuille source, ou réassocie des filtres existants à une autre feuille (styles synchronisés). | `.twb`, `.twbx` | `filters_engine.py` |
| 🔌 **Changer la connexion** | Pour les connexions Databricks : change le serveur / chemin HTTP (presets d'environnement ou hôte personnalisé), remplace le catalogue, renomme les tables (y compris dans le SQL personnalisé). | `.twb`, `.twbx`, `.tds` | `connection_engine.py` |
| 📊 **Performances** | Analyse un enregistrement de performances Tableau (`perf_gantt.tab`) : KPIs, événements les plus lents, résumé par feuille et par catégorie, requêtes sans cache, vagues d'exécution. Analyse optionnelle par Gemini. | `.twbx` d'enregistrement | `performance_engine.py` |
| 🕸️ **Lignage** | Détecte les champs inutilisés et trace le lignage de la source jusqu'aux usages (voir ci-dessous). | `.twb`, `.twbx` | `lineage_engine.py` |

Les outils de modification produisent un fichier du **même format** que celui d'entrée (un `.twbx` est remballé avec ses ressources). Seul le XML est modifié : le contenu des extraits `.hyper` n'est jamais lu.

### 🕸️ Lignage

- **Champs inutilisés** : un champ est considéré comme utilisé s'il sert dans une feuille, un dashboard, une action, une jointure, la visibilité dynamique d'une zone, ou (par propagation) dans un calcul, un groupe ou la valeur par défaut d'un paramètre eux-mêmes utilisés. Statuts : *inutilisé*, *en cascade* (utilisé seulement par des champs inutilisés), *cosmétique* (seulement rangé dans un dossier ou une hiérarchie), *intermédiaire* (utilisé uniquement dans d'autres calculs, candidat au masquage). Tableau filtrable et export Excel.
- **Graphe de lignage interactif** : sources → calculs → usages (feuilles, actions, zones, jointures) → dashboards. Clic pour voir l'amont et l'aval d'un champ, double-clic (ou bouton) pour isoler son lignage, recherche, remontée depuis un dashboard, bascule libellé / nom interne, filtre par type de nœud, mode *Colonnes* ou *Libre* (nœuds déplaçables), plein écran. Exportable en **page HTML autonome** (aucune dépendance externe).

## Lancer en local

```bash
pip install -r requirements.txt
streamlit run tableau_toolkit.py
```

Python 3.10+ recommandé.

### Analyse Gemini (optionnelle)

L'onglet Performances peut envoyer un résumé à l'API Gemini. Ajouter dans `.streamlit/secrets.toml` (ou dans les *Secrets* de Streamlit Cloud) :

```toml
GEMINI_API_KEY = "..."
GEMINI_MODEL   = "gemini-2.5-flash"   # optionnel
```

Sans clé, le reste de l'application fonctionne normalement.

## Structure du dépôt

```
tableau_toolkit.py      # UI Streamlit (onglets, état de session, téléchargements)
translations.py         # Textes FR / EN
utils.py                # Lecture .twb/.twbx, parsing/sérialisation XML, remballage .twbx
resize_engine.py        # Redimensionnement des dashboards
filters_engine.py       # Formatage, ajout et réassociation de filtres
connection_engine.py    # Catalogue, serveur et tables Databricks
performance_engine.py   # Analyse de perf_gantt.tab + prompt Gemini
lineage_engine.py       # Analyse des usages, graphe de lignage, exports HTML / Excel
lineage_template.html   # Page HTML autonome du graphe (placeholders __DATA__, __I18N__…)
requirements.txt
```

Chaque `*_engine.py` ne dépend pas de Streamlit : les fonctions prennent le contenu XML (`bytes`) et renvoient des structures Python ou un XML modifié, ce qui les rend testables et réutilisables en script.

## Notes de conception

- **XML via `xml.etree.ElementTree`** (pas de lxml). `utils.py` enregistre le préfixe `user:` pour que Tableau reconnaisse les attributs après re-sérialisation.
- **Confidentialité** : les fichiers uploadés transitent par le serveur qui héberge l'application (Streamlit Cloud en ligne). Pour un classeur dont l'extrait contient des données sensibles, uploader le `.twb` plutôt que le `.twbx`, ou lancer l'application en local.
- Les presets d'environnement de l'onglet Connexion (serveurs et chemins HTTP Databricks) sont définis dans `tableau_toolkit.py` ; à adapter à votre organisation.
- Ajouter un outil : créer un `*_engine.py`, ajouter les clés dans `translations.py` (FR et EN), puis un onglet dans `main()` et ses clés d'état à la liste de réinitialisation du changement de fichier.

---
Tableau Toolkit · dev version · © Idir Saidani & AI
