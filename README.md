# 🧰 Tableau Toolkit

A [Streamlit](https://streamlit.io) toolkit to **modify and analyze Tableau workbooks** (`.twb`, `.twbx`) and data sources (`.tds`) by working directly on their XML, without opening Tableau Desktop. The UI is bilingual (FR / EN).

## Tools

A single file is uploaded at the top of the page and shared across tabs (except the Performance tab, which has its own upload).

| Tab | What it does | Files | Module |
|---|---|---|---|
| 📐 **Resize** | Changes dashboard resolution (one common size or per dashboard) and automatically repositions objects. | `.twb`, `.twbx` | `resize_engine.py` |
| 🔽 **Format Filters** | Changes filter display modes, adds filters to a dashboard from a source sheet, or reassigns existing filters to another source sheet (styles are kept in sync). | `.twb`, `.twbx` | `filters_engine.py` |
| 🔌 **Change Connection** | For Databricks connections: changes the server / HTTP path (environment presets or custom host), replaces the catalog, renames tables (including in custom SQL). | `.twb`, `.twbx`, `.tds` | `connection_engine.py` |
| 📊 **Performance** | Analyzes a Tableau performance recording (`perf_gantt.tab`): KPIs, slowest events, summaries per sheet and per category, uncached queries, execution waves. Optional Gemini analysis. | recording `.twbx` | `performance_engine.py` |
| 🕸️ **Lineage** | Finds unused fields and traces lineage from source to usage (see below). | `.twb`, `.twbx` | `lineage_engine.py` |

The editing tools output a file in the **same format** as the input (a `.twbx` is repacked with its resources). Only the XML is modified: the content of `.hyper` extracts is never read.

### 🕸️ Lineage

- **Unused fields**: a field counts as used if it appears in a sheet, dashboard, action, join, dynamic zone visibility, or (by propagation) in a calculation, group or parameter default value that is itself used. Statuses: *unused*, *cascade* (only used by unused fields), *cosmetic* (only placed in a folder or hierarchy), *intermediate* (only used inside other calculations, a candidate for hiding). Filterable table with Excel export.
- **Interactive lineage graph**: sources → calculations → usages (sheets, actions, zones, joins) → dashboards. Click a field to see its upstream and downstream, double-click (or use the button) to isolate its lineage, plus search, trace back from a dashboard, caption / internal name toggle, node-type filter, *Columns* or *Free* layout (draggable nodes) and fullscreen. Exportable as a **standalone HTML page** (no external dependencies).

## Run locally

```bash
pip install -r requirements.txt
streamlit run tableau_toolkit.py
```

Python 3.10+ recommended.

### Gemini analysis (optional)

The Performance tab can send a summary to the Gemini API. Add to `.streamlit/secrets.toml` (or to the Streamlit Cloud *Secrets*):

```toml
GEMINI_API_KEY = "..."
GEMINI_MODEL   = "gemini-2.5-flash"   # optional
```

Without a key, the rest of the app works normally.

## Repository structure

```
tableau_toolkit.py      # Streamlit UI (tabs, session state, downloads)
translations.py         # FR / EN strings
utils.py                # .twb/.twbx loading, XML parsing/serialization, .twbx repacking
resize_engine.py        # Dashboard resizing
filters_engine.py       # Filter formatting, adding and reassignment
connection_engine.py    # Databricks catalog, server and tables
performance_engine.py   # perf_gantt.tab analysis + Gemini prompt
lineage_engine.py       # Usage analysis, lineage graph, HTML / Excel exports
lineage_template.html   # Standalone graph page (placeholders __DATA__, __I18N__…)
requirements.txt
```

Each `*_engine.py` is independent of Streamlit: functions take the XML content (`bytes`) and return Python structures or modified XML, which makes them testable and reusable in scripts.

## Design notes

- **XML through `xml.etree.ElementTree`** (no lxml). `utils.py` registers the `user:` prefix so Tableau still recognizes its attributes after re-serialization.
- **Privacy**: uploaded files transit through the server hosting the app (Streamlit Cloud when deployed). For a workbook whose extract contains sensitive data, upload the `.twb` instead of the `.twbx`, or run the app locally.
- The environment presets of the Connection tab (Databricks servers and HTTP paths) are defined in `tableau_toolkit.py`; adapt them to your organization.
- Adding a tool: create an `*_engine.py`, add the keys to `translations.py` (FR and EN), then add a tab in `main()` and its session-state keys to the reset list used when the uploaded file changes.

---
Tableau Toolkit · dev version · © Idir Saidani & AI
