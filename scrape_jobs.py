#!/usr/bin/env python3
"""
IT-työpaikkojen päivittäinen seuranta.

Kaksi datanlähdettä:
  1. Duunitori (automaattinen, ei vaadi kirjautumista)
  2. Joblistings API (manuaalinen, vaatii Bearer-tokenin)

Käyttö:
  python3 scrape_jobs.py                  # Duunitori (automaattinen)
  python3 scrape_jobs.py --token XXXX     # Joblistings API
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, date
from pathlib import Path
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

HISTORY_FILE = DATA_DIR / "history.json"

# === Kategorioiden luokittelusäännöt ===
# Käytetään sekä Duunitori-haussa että API-ilmoitusten luokittelussa.
# "keywords" = sanat joilla ilmoitus matchataan (job_title + required_skills)
CATEGORIES = {
    "Ohjelmistokehitys": {
        "duunitori": {"terms": ["ohjelmistokehitys", "+software +developer", "+software +engineer"], "mode": "sum"},
        "keywords": ["software developer", "software engineer", "ohjelmistokehit", "sovelluskehit",
                      "ohjelmistosuunnit", "ohjelmoija", "lead developer", "senior developer",
                      "developer,", "kehittäjä", "kehittaja", "graafikko"],
    },
    "Fullstack": {
        "duunitori": {"terms": ["fullstack", "full-stack"], "mode": "best"},
        "keywords": ["fullstack", "full-stack", "full stack"],
    },
    "Frontend": {
        "duunitori": {"terms": ["frontend", "front-end"], "mode": "best"},
        "keywords": ["frontend", "front-end", "front end", "react developer", "vue developer", "angular developer"],
    },
    "Backend": {
        "duunitori": {"terms": ["backend", "back-end"], "mode": "best"},
        "keywords": ["backend", "back-end", "back end"],
    },
    "Embedded / Sulautetut": {
        "duunitori": {"terms": ["+embedded +software", "+embedded +developer", "+sulautetut +järjestelmät"], "mode": "sum"},
        "keywords": ["embedded", "sulautettu", "sulautetut"],
    },
    "Mobiilisovelluskehitys": {
        "duunitori": {"terms": ["+mobile +developer", "+ios +developer", "+android +developer", "mobiilikehittäjä"], "mode": "sum"},
        "keywords": ["mobile developer", "ios developer", "android developer", "mobiili", "react native",
                      "flutter", "mobile engineer", "android engineer", "ios engineer", "kotlin"],
    },
    "Design (UX/UI)": {
        "duunitori": {"terms": ["+ux +designer", "+ui +designer"], "mode": "sum"},
        "keywords": ["ux designer", "ui designer", "ux/ui", "ux ", "ui "],
    },
    "Testaus / QA": {
        "duunitori": {"terms": ["+test +engineer", "+qa +engineer", "testausinsinööri"], "mode": "sum"},
        "keywords": ["test engineer", "qa engineer", "quality assurance", "testaus", "testaaja", "sdet",
                      "test lead", "validation engineer", "test automation", "robot framework", "playwright"],
    },
    "Data & BI": {
        "duunitori": {"terms": ["+data +analyst", "+power +bi", "+business +intelligence", "+data +analyytikko"], "mode": "sum"},
        "keywords": ["data analyst", "data-analyy", "liiketoiminta-analyy", "business analyst",
                      "power bi", "tableau", "analytics engineer", "analytiikka",
                      "tietovarasto", "data steward", "data governance", "raportointi"],
    },
    "Data Scientist": {
        "duunitori": {"terms": ["+data +scientist"], "mode": "best"},
        "keywords": ["data scientist", "data science"],
    },
    "Data Engineer": {
        "duunitori": {"terms": ["+data +engineer"], "mode": "best"},
        "keywords": ["data engineer"],
    },
    "Data Architect": {
        "duunitori": {"terms": ["+data +architect"], "mode": "best"},
        "keywords": ["data architect"],
    },
    "DevOps / SRE": {
        "duunitori": {"terms": ["+devops +engineer", "+site +reliability"], "mode": "sum"},
        "keywords": ["devops", "sre", "site reliability", "platform engineer", "infrastructure as code"],
    },
    "Tietoturva / IAM": {
        "duunitori": {"terms": ["+cybersecurity", "+tietoturva", "+information +security"], "mode": "sum"},
        "keywords": ["cybersecurity", "tietoturva", "information security", "security engineer",
                      "iam ", "identity management", "access management", "penetration test"],
    },
    "IT-projektinhallinta": {
        "duunitori": {"terms": ["+it +projektipäällikkö", "+scrum +master", "+agile +coach"], "mode": "sum"},
        "keywords": ["projektipäällikkö", "project manager", "scrum master", "agile coach",
                      "delivery manager"],
    },
    "Järjestelmäasiantuntija": {
        "duunitori": {"terms": ["järjestelmäasiantuntija", "+system +specialist", "+it +specialist"], "mode": "sum"},
        "keywords": ["järjestelmäasiantuntija", "system specialist", "system engineer",
                      "it operations", "it-tuki", "it specialist"],
    },
    "SAP / ERP": {
        "duunitori": {"terms": ["+sap +consultant", "+erp +developer", "+dynamics +365"], "mode": "sum"},
        "keywords": ["sap ", "erp", "dynamics 365", "dynamics365", "salesforce",
                      "successfactors", "guidewire"],
    },
    "SW Architect": {
        "duunitori": {"terms": ["+software +architect", "+solution +architect"], "mode": "sum"},
        "keywords": ["software architect", "ohjelmistoarkkitehti", "solution architect",
                      "solution designer", "solution engineer"],
    },
    "Cloud Engineer": {
        "duunitori": {"terms": ["+cloud +engineer"], "mode": "best"},
        "keywords": ["cloud engineer", "aws kehit", "azure engineer"],
    },
    "Cloud Architect": {
        "duunitori": {"terms": ["+cloud +architect"], "mode": "best"},
        "keywords": ["cloud architect"],
    },
    "GenAI Engineer": {
        "duunitori": {"terms": ["+genai +engineer", "+generative +ai +engineer"], "mode": "best"},
        "keywords": ["genai engineer", "generative ai engineer"],
    },
    "AI Engineer": {
        "duunitori": {"terms": ["+ai +engineer", "+machine +learning +engineer", "+ml +engineer"], "mode": "sum"},
        "keywords": ["ai engineer", "machine learning engineer", "ml engineer",
                      "ai performance", "agentic", "computer vision", "perception software"],
    },
    "GenAI Architect": {
        "duunitori": {"terms": ["+genai +architect", "+ai +architect"], "mode": "best"},
        "keywords": ["genai architect", "ai architect"],
    },
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept-Language": "fi-FI,fi;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

JOBLISTINGS_API = "https://joblistings-agent-lnojw7sokq-lz.a.run.app"


# =====================================================================
# Lähde 1: Duunitori (scraping)
# =====================================================================

def fetch_duunitori_count(search_term: str) -> int:
    url = f"https://duunitori.fi/tyopaikat?haku={quote_plus(search_term)}&alue=suomi"
    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()
        match = re.search(r'"results_count"\s*:\s*"(\d+)"', resp.text)
        return int(match.group(1)) if match else 0
    except Exception as e:
        print(f"  [VIRHE] Duunitori '{search_term}': {e}", file=sys.stderr)
        return 0


def get_duunitori_count(terms: list, mode: str) -> int:
    counts = []
    for term in terms:
        counts.append(fetch_duunitori_count(term))
        time.sleep(0.5)
    return sum(counts) if mode == "sum" else (max(counts) if counts else 0)


def scrape_duunitori() -> dict:
    today = date.today().isoformat()
    results = {"date": today, "source": "duunitori", "categories": {}, "timestamp": datetime.now().isoformat()}
    total = len(CATEGORIES)
    for i, (cat, cfg) in enumerate(CATEGORIES.items(), 1):
        d = cfg["duunitori"]
        print(f"[{i}/{total}] {cat}...", end=" ", flush=True)
        count = get_duunitori_count(d["terms"], d["mode"])
        print(count)
        results["categories"][cat] = {"count": count}
    return results


# =====================================================================
# Lähde 2: Joblistings API
# =====================================================================

def fetch_all_joblistings(token: str) -> list:
    """Hae kaikki ilmoitukset sivutetusti."""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    all_listings = []
    skip = 0
    limit = 100

    print("Haetaan ilmoituksia Joblistings API:sta...", flush=True)

    while True:
        url = f"{JOBLISTINGS_API}/api/v1/job-listings/?skip={skip}&limit={limit}"
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        listings = data.get("data", [])
        total = data.get("total", 0)
        all_listings.extend(listings)
        print(f"  Haettu {len(all_listings)}/{total}...", flush=True)

        if len(all_listings) >= total or not listings:
            break
        skip += limit
        time.sleep(0.3)

    print(f"  Yhteensä {len(all_listings)} ilmoitusta")
    return all_listings


def load_excel_listings(filepath: str) -> list:
    """Lue Excel-tiedosto ja muunna listaksi dictejä (sama muoto kuin API)."""
    import openpyxl
    wb = openpyxl.load_workbook(filepath)
    ws = wb.active
    headers = [cell.value for cell in ws[1]]
    listings = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        item = dict(zip(headers, row))
        listings.append({
            "job_title": item.get("Title") or "",
            "required_skills": [s.strip() for s in (item.get("Skills") or "").split(",") if s.strip()],
            "company_name": item.get("Company") or "",
            "location": item.get("Location") or "",
        })
    return listings


def classify_listing(listing: dict) -> list:
    """Luokittele yksittäinen ilmoitus kategorioihin job_title + required_skills perusteella."""
    title = (listing.get("job_title") or "").lower()
    skills = [s.lower() for s in (listing.get("required_skills") or [])]
    searchable = title + " " + " ".join(skills)

    matched = []
    for cat, cfg in CATEGORIES.items():
        for kw in cfg["keywords"]:
            if kw.lower() in searchable:
                matched.append(cat)
                break
    return matched


def classify_listings(listings: list) -> dict:
    """Luokittele valmiiksi haetut ilmoitukset."""
    today = date.today().isoformat()
    results = {
        "date": today,
        "source": "joblistings-api",
        "categories": {},
        "timestamp": datetime.now().isoformat(),
        "total_listings": len(listings),
    }

    counts = {cat: 0 for cat in CATEGORIES}
    unclassified = 0
    for listing in listings:
        cats = classify_listing(listing)
        if cats:
            for cat in cats:
                counts[cat] += 1
        else:
            unclassified += 1

    for cat, count in counts.items():
        results["categories"][cat] = {"count": count}

    print(f"Luokiteltu {len(listings)} ilmoitusta:")
    sorted_cats = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    for cat, count in sorted_cats:
        print(f"  {cat:30s} {count:5d}")
    print(f"\n  {'Luokittelematta':30s} {unclassified:5d}")
    print(f"  {'API ilmoituksia yhteensä':30s} {len(listings):5d}")

    return results


def scrape_joblistings(token: str) -> dict:
    """Hae ja luokittele kaikki Joblistings API:n ilmoitukset."""
    listings = fetch_all_joblistings(token)

    today = date.today().isoformat()
    results = {
        "date": today,
        "source": "joblistings-api",
        "categories": {},
        "timestamp": datetime.now().isoformat(),
        "total_listings": len(listings),
    }

    # Laske per kategoria
    counts = {cat: 0 for cat in CATEGORIES}
    unclassified = 0
    for listing in listings:
        cats = classify_listing(listing)
        if cats:
            for cat in cats:
                counts[cat] += 1
        else:
            unclassified += 1

    for cat, count in counts.items():
        results["categories"][cat] = {"count": count}

    # Tulosta yhteenveto
    print(f"\nLuokiteltu {len(listings)} ilmoitusta:")
    sorted_cats = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    for cat, count in sorted_cats:
        print(f"  {cat:30s} {count:5d}")
    print(f"\n  {'Luokittelematta':30s} {unclassified:5d}")
    print(f"  {'API ilmoituksia yhteensä':30s} {len(listings):5d}")

    return results


# =====================================================================
# HTML-generointi ja pääohjelma
# =====================================================================

def load_history() -> list:
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE) as f:
            return json.load(f)
    return []


def save_history(history: list):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def generate_html(history: list):
    html_file = Path(__file__).parent / "index.html"
    today_data = history[-1] if history else None
    prev_data = history[-2] if len(history) >= 2 else None

    source = today_data.get("source", "duunitori") if today_data else "duunitori"
    is_api = source == "joblistings-api"
    total_listings = today_data.get("total_listings", 0) if today_data else 0

    table_rows = []
    if today_data:
        for cat, data in today_data["categories"].items():
            count = data["count"]
            change = ""
            change_class = ""
            if prev_data and cat in prev_data["categories"]:
                prev_count = prev_data["categories"][cat]["count"]
                diff = count - prev_count
                if diff > 0:
                    change = f"+{diff}"
                    change_class = "positive"
                elif diff < 0:
                    change = str(diff)
                    change_class = "negative"
                else:
                    change = "0"
                    change_class = "neutral"
            table_rows.append({"category": cat, "count": count, "change": change, "change_class": change_class})

    categories = list(CATEGORIES.keys())
    dates = [h["date"] for h in history[-30:]]

    colors = [
        "#3B82F6", "#EF4444", "#10B981", "#F59E0B", "#8B5CF6",
        "#EC4899", "#06B6D4", "#84CC16", "#F97316", "#6366F1",
        "#14B8A6", "#E11D48", "#0EA5E9", "#A855F7", "#D946EF",
        "#22C55E", "#FF6B6B",
    ]
    chart_datasets = []
    for i, cat in enumerate(categories):
        values = [h["categories"].get(cat, {}).get("count", 0) for h in history[-30:]]
        chart_datasets.append({
            "label": cat, "data": values,
            "borderColor": colors[i % len(colors)],
            "backgroundColor": colors[i % len(colors)] + "20",
            "tension": 0.3, "borderWidth": 2,
        })

    grand_total = sum(r["count"] for r in table_rows) if table_rows else 0
    update_time = today_data["timestamp"][:16].replace("T", " ") if today_data else "-"

    source_label = "Joblistings API (joblistings.aiexp.fi)" if is_api else "Duunitori (aggregoi mm. TE-palvelut, yrityssivustot)"
    source_url = "https://joblistings.aiexp.fi" if is_api else "https://duunitori.fi"
    source_name = "Joblistings API" if is_api else "Duunitori"

    html = f"""<!DOCTYPE html>
<html lang="fi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IT-työpaikat Suomessa</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
            background: #0f172a; color: #e2e8f0; min-height: 100vh;
        }}
        .header {{
            background: linear-gradient(135deg, #1e293b, #334155);
            padding: 2rem; border-bottom: 1px solid #475569;
        }}
        .header h1 {{ font-size: 1.75rem; font-weight: 700; color: #f8fafc; }}
        .header .subtitle {{ color: #94a3b8; margin-top: 0.25rem; font-size: 0.9rem; }}
        .header .sources {{ color: #64748b; font-size: 0.8rem; margin-top: 0.5rem; }}
        .header .sources a {{ color: #60a5fa; text-decoration: none; }}
        .badge {{ display: inline-block; padding: 0.15rem 0.5rem; border-radius: 0.25rem; font-size: 0.75rem; font-weight: 600; }}
        .badge-api {{ background: #065f46; color: #6ee7b7; }}
        .badge-scrape {{ background: #1e3a5f; color: #93c5fd; }}
        .kpi-bar {{
            display: flex; gap: 1.5rem; padding: 1.5rem 2rem;
            background: #1e293b; border-bottom: 1px solid #334155; flex-wrap: wrap;
        }}
        .kpi {{ background: #334155; padding: 1rem 1.5rem; border-radius: 0.75rem; min-width: 180px; }}
        .kpi .label {{ color: #94a3b8; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; }}
        .kpi .value {{ font-size: 1.75rem; font-weight: 700; color: #f8fafc; margin-top: 0.25rem; }}
        .kpi .sub {{ color: #64748b; font-size: 0.8rem; margin-top: 0.25rem; }}
        .container {{ padding: 2rem; max-width: 1200px; margin: 0 auto; }}
        .card {{
            background: #1e293b; border: 1px solid #334155;
            border-radius: 0.75rem; padding: 1.5rem; margin-bottom: 2rem;
        }}
        .card h2 {{ font-size: 1.1rem; color: #f8fafc; margin-bottom: 1rem; padding-bottom: 0.75rem; border-bottom: 1px solid #334155; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
        th {{
            text-align: left; padding: 0.75rem 1rem; background: #334155;
            color: #94a3b8; font-weight: 600; font-size: 0.8rem;
            text-transform: uppercase; letter-spacing: 0.05em;
        }}
        th:first-child {{ border-radius: 0.5rem 0 0 0.5rem; }}
        th:last-child {{ border-radius: 0 0.5rem 0.5rem 0; }}
        td {{ padding: 0.75rem 1rem; border-bottom: 1px solid #0f172a; }}
        tr:nth-child(even) {{ background: #1e293b; }}
        tr:nth-child(odd) {{ background: #162032; }}
        tr:hover {{ background: #334155; transition: background 0.15s; }}
        .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
        .count-col {{ font-weight: 700; color: #f8fafc; font-size: 1rem; }}
        .bar-cell {{ width: 40%; }}
        .bar-bg {{ background: #334155; border-radius: 0.25rem; height: 1.25rem; overflow: hidden; }}
        .bar-fill {{ height: 100%; border-radius: 0.25rem; transition: width 0.3s; }}
        .positive {{ color: #4ade80; font-weight: 600; }}
        .negative {{ color: #f87171; font-weight: 600; }}
        .neutral {{ color: #64748b; }}
        .chart-container {{ position: relative; height: 420px; }}
        .footer {{ text-align: center; padding: 2rem; color: #475569; font-size: 0.8rem; }}
        @media (max-width: 768px) {{
            .kpi-bar {{ flex-direction: column; }}
            .container {{ padding: 1rem; }}
            .bar-cell {{ display: none; }}
            table {{ font-size: 0.8rem; }}
            td, th {{ padding: 0.5rem; }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>IT-työpaikat Suomessa
            <span class="badge {"badge-api" if is_api else "badge-scrape"}">{"API" if is_api else "SCRAPE"}</span>
        </h1>
        <div class="subtitle">Avointen työpaikkojen päivittäinen seuranta tehtävittäin</div>
        <div class="sources">
            Lähde: <a href="{source_url}" target="_blank">{source_label}</a>
        </div>
    </div>

    <div class="kpi-bar">
        <div class="kpi">
            <div class="label">IT-kategorioissa</div>
            <div class="value">{grand_total:,}</div>
            <div class="sub">luokitellut ilmoitukset</div>
        </div>"""

    if is_api:
        html += f"""
        <div class="kpi">
            <div class="label">API yhteensä</div>
            <div class="value">{total_listings:,}</div>
            <div class="sub">kaikki ilmoitukset</div>
        </div>"""

    html += f"""
        <div class="kpi">
            <div class="label">Kategorioita</div>
            <div class="value">{len(categories)}</div>
            <div class="sub">seurannassa</div>
        </div>
        <div class="kpi">
            <div class="label">Päivitetty</div>
            <div class="value" style="font-size:1.1rem">{update_time}</div>
            <div class="sub">{source_name}</div>
        </div>
        <div class="kpi">
            <div class="label">Historiaa</div>
            <div class="value">{len(history)}</div>
            <div class="sub">päivää</div>
        </div>
    </div>

    <div class="container">
        <div class="card">
            <h2>Avoimet työpaikat tehtävittäin</h2>
            <table>
                <thead>
                    <tr>
                        <th>Tehtävä</th>
                        <th class="num">Avoimia</th>
                        <th class="bar-cell"></th>
                        <th class="num">Muutos</th>
                    </tr>
                </thead>
                <tbody>
"""

    sorted_rows = sorted(table_rows, key=lambda r: r["count"], reverse=True)
    max_count = max((r["count"] for r in sorted_rows), default=1) or 1
    for row in sorted_rows:
        pct = (row["count"] / max_count) * 100
        color = colors[list(CATEGORIES.keys()).index(row["category"]) % len(colors)]
        html += f"""                    <tr>
                        <td>{row["category"]}</td>
                        <td class="num count-col">{row["count"]}</td>
                        <td class="bar-cell"><div class="bar-bg"><div class="bar-fill" style="width:{pct:.0f}%;background:{color}"></div></div></td>
                        <td class="num {row["change_class"]}">{row["change"]}</td>
                    </tr>
"""

    html += f"""                </tbody>
            </table>
        </div>

        <div class="card">
            <h2>Kehitys (viimeiset 30 päivää)</h2>
            <div class="chart-container">
                <canvas id="trendChart"></canvas>
            </div>
        </div>
    </div>

    <div class="footer">
        Data: {source_name}
    </div>

    <script>
        const ctx = document.getElementById('trendChart').getContext('2d');
        new Chart(ctx, {{
            type: 'line',
            data: {{
                labels: {json.dumps(dates)},
                datasets: {json.dumps(chart_datasets, ensure_ascii=False)}
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                interaction: {{ mode: 'index', intersect: false }},
                plugins: {{
                    legend: {{
                        position: 'bottom',
                        labels: {{ color: '#94a3b8', boxWidth: 12, padding: 15, font: {{ size: 11 }} }}
                    }},
                    tooltip: {{
                        backgroundColor: '#1e293b', borderColor: '#475569', borderWidth: 1,
                        titleColor: '#f8fafc', bodyColor: '#e2e8f0',
                    }}
                }},
                scales: {{
                    x: {{ ticks: {{ color: '#64748b' }}, grid: {{ color: '#1e293b' }} }},
                    y: {{ ticks: {{ color: '#64748b' }}, grid: {{ color: '#1e293b' }}, beginAtZero: true }}
                }}
            }}
        }});
    </script>
</body>
</html>"""

    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nHTML-raportti: {html_file}")


def main():
    parser = argparse.ArgumentParser(description="IT-työpaikkojen seuranta")
    parser.add_argument("--token", help="Joblistings API Bearer-token (manuaalinen ajo)")
    parser.add_argument("--file", help="JSON-tiedosto Joblistings API:n exportista (manuaalinen ajo)")
    args = parser.parse_args()

    print(f"=== IT-työpaikkojen seuranta {date.today().isoformat()} ===\n")

    if args.file:
        if args.file.endswith((".xlsx", ".xls")):
            print(f"Lähde: Excel-tiedosto {args.file}\n")
            listings = load_excel_listings(args.file)
        else:
            print(f"Lähde: JSON-tiedosto {args.file}\n")
            with open(args.file, encoding="utf-8") as f:
                listings = json.load(f)
        today_results = classify_listings(listings)
    elif args.token:
        print("Lähde: Joblistings API\n")
        today_results = scrape_joblistings(args.token)
    else:
        print("Lähde: Duunitori\n")
        today_results = scrape_duunitori()

    history = load_history()
    today_str = date.today().isoformat()
    history = [h for h in history if h["date"] != today_str]
    history.append(today_results)

    save_history(history)
    print(f"\nData: {HISTORY_FILE}")

    generate_html(history)

    total = sum(d["count"] for d in today_results["categories"].values())
    print(f"\nYHTEENSÄ: {total}")


if __name__ == "__main__":
    main()
