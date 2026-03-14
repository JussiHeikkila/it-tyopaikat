#!/usr/bin/env python3
"""
IT-työpaikkojen päivittäinen seuranta.
Hakee avointen työpaikkojen lukumäärät Duunitorista
tehtäväkategorioittain ja tallentaa tulokset JSON-tiedostoon.
Generoi HTML-raporttisivun Chart.js-trendikaaviolla.
"""

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

# Hakukategoriat ja hakutermit
# Duunitori tekee OR-haun oletuksena. +-etuliite pakottaa AND-haun:
#   "+data +scientist" = sisältää molemmat sanat
#
# mode: "best" = synonyymit, otetaan suurin tulos (vältetään kaksoislaskenta)
#        "sum"  = eri käsitteet, summataan tulokset
CATEGORIES = {
    "Ohjelmistokehitys":      {"terms": ["ohjelmistokehitys", "+software +developer", "+software +engineer"], "mode": "sum"},
    "Fullstack":              {"terms": ["fullstack", "full-stack"], "mode": "best"},
    "Frontend":               {"terms": ["frontend", "front-end"], "mode": "best"},
    "Backend":                {"terms": ["backend", "back-end"], "mode": "best"},
    "Embedded / Sulautetut":  {"terms": ["+embedded +software", "+embedded +developer", "+sulautetut +järjestelmät"], "mode": "sum"},
    "Mobiilisovelluskehitys": {"terms": ["+mobile +developer", "+ios +developer", "+android +developer", "mobiilikehittäjä"], "mode": "sum"},
    "Design (UX/UI)":         {"terms": ["+ux +designer", "+ui +designer"], "mode": "sum"},
    "Testaus / QA":           {"terms": ["+test +engineer", "+qa +engineer", "testausinsinööri"], "mode": "sum"},
    "Data Scientist":         {"terms": ["+data +scientist"], "mode": "best"},
    "Data Engineer":          {"terms": ["+data +engineer"], "mode": "best"},
    "Data Architect":         {"terms": ["+data +architect"], "mode": "best"},
    "SW Architect":           {"terms": ["+software +architect", "+solution +architect"], "mode": "sum"},
    "Cloud Engineer":         {"terms": ["+cloud +engineer"], "mode": "best"},
    "Cloud Architect":        {"terms": ["+cloud +architect"], "mode": "best"},
    "GenAI Engineer":         {"terms": ["+genai +engineer", "+generative +ai +engineer"], "mode": "best"},
    "AI Engineer":            {"terms": ["+ai +engineer", "+machine +learning +engineer", "+ml +engineer"], "mode": "sum"},
    "GenAI Architect":        {"terms": ["+genai +architect", "+ai +architect"], "mode": "best"},
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "fi-FI,fi;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def fetch_duunitori_count(search_term: str) -> int:
    """Hae tulosten lukumäärä Duunitorista dataLayer-muuttujasta."""
    url = f"https://duunitori.fi/tyopaikat?haku={quote_plus(search_term)}&alue=suomi"
    try:
        resp = SESSION.get(url, timeout=15)
        resp.raise_for_status()
        match = re.search(r'"results_count"\s*:\s*"(\d+)"', resp.text)
        if match:
            return int(match.group(1))
        return 0
    except Exception as e:
        print(f"  [VIRHE] Duunitori '{search_term}': {e}", file=sys.stderr)
        return 0


def get_count(terms: list, mode: str) -> int:
    """Hae tulosmäärä: 'best' = suurin yksittäinen, 'sum' = kaikkien summa."""
    counts = []
    for term in terms:
        count = fetch_duunitori_count(term)
        counts.append(count)
        time.sleep(0.5)
    if mode == "sum":
        return sum(counts)
    else:
        return max(counts) if counts else 0


def scrape_all() -> dict:
    """Hae kaikkien kategorioiden tulokset."""
    today = date.today().isoformat()
    results = {"date": today, "categories": {}, "timestamp": datetime.now().isoformat()}

    total_categories = len(CATEGORIES)
    for i, (category, cfg) in enumerate(CATEGORIES.items(), 1):
        print(f"[{i}/{total_categories}] {category}...", end=" ", flush=True)
        count = get_count(cfg["terms"], cfg["mode"])
        print(count)
        results["categories"][category] = {"count": count}

    return results


def load_history() -> list:
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE) as f:
            return json.load(f)
    return []


def save_history(history: list):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def generate_html(history: list):
    """Generoi HTML-raporttisivu."""
    html_file = Path(__file__).parent / "index.html"

    today_data = history[-1] if history else None
    prev_data = history[-2] if len(history) >= 2 else None

    # Taulukkorivit
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
            table_rows.append({
                "category": cat,
                "count": count,
                "change": change,
                "change_class": change_class,
            })

    # Chart.js aikasarjadata
    categories = list(CATEGORIES.keys())
    dates = [h["date"] for h in history[-30:]]

    chart_datasets = []
    colors = [
        "#3B82F6", "#EF4444", "#10B981", "#F59E0B", "#8B5CF6",
        "#EC4899", "#06B6D4", "#84CC16", "#F97316", "#6366F1",
        "#14B8A6", "#E11D48", "#0EA5E9", "#A855F7", "#D946EF",
        "#22C55E", "#FF6B6B",
    ]
    for i, cat in enumerate(categories):
        values = []
        for h in history[-30:]:
            val = h["categories"].get(cat, {}).get("count", 0)
            values.append(val)
        chart_datasets.append({
            "label": cat,
            "data": values,
            "borderColor": colors[i % len(colors)],
            "backgroundColor": colors[i % len(colors)] + "20",
            "tension": 0.3,
            "borderWidth": 2,
        })

    grand_total = sum(r["count"] for r in table_rows) if table_rows else 0
    update_time = today_data["timestamp"][:16].replace("T", " ") if today_data else "-"

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
            background: #0f172a;
            color: #e2e8f0;
            min-height: 100vh;
        }}
        .header {{
            background: linear-gradient(135deg, #1e293b, #334155);
            padding: 2rem;
            border-bottom: 1px solid #475569;
        }}
        .header h1 {{ font-size: 1.75rem; font-weight: 700; color: #f8fafc; }}
        .header .subtitle {{ color: #94a3b8; margin-top: 0.25rem; font-size: 0.9rem; }}
        .header .sources {{ color: #64748b; font-size: 0.8rem; margin-top: 0.5rem; }}
        .header .sources a {{ color: #60a5fa; text-decoration: none; }}
        .kpi-bar {{
            display: flex; gap: 1.5rem; padding: 1.5rem 2rem;
            background: #1e293b; border-bottom: 1px solid #334155; flex-wrap: wrap;
        }}
        .kpi {{
            background: #334155; padding: 1rem 1.5rem;
            border-radius: 0.75rem; min-width: 180px;
        }}
        .kpi .label {{ color: #94a3b8; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; }}
        .kpi .value {{ font-size: 1.75rem; font-weight: 700; color: #f8fafc; margin-top: 0.25rem; }}
        .kpi .sub {{ color: #64748b; font-size: 0.8rem; margin-top: 0.25rem; }}
        .container {{ padding: 2rem; max-width: 1200px; margin: 0 auto; }}
        .card {{
            background: #1e293b; border: 1px solid #334155;
            border-radius: 0.75rem; padding: 1.5rem; margin-bottom: 2rem;
        }}
        .card h2 {{
            font-size: 1.1rem; color: #f8fafc; margin-bottom: 1rem;
            padding-bottom: 0.75rem; border-bottom: 1px solid #334155;
        }}
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
        .footer {{
            text-align: center; padding: 2rem; color: #475569; font-size: 0.8rem;
        }}
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
        <h1>IT-työpaikat Suomessa</h1>
        <div class="subtitle">Avointen työpaikkojen päivittäinen seuranta tehtävittäin</div>
        <div class="sources">
            Lähde: <a href="https://duunitori.fi" target="_blank">Duunitori</a>
            (aggregoi mm. TE-palvelut, yrityssivustot)
        </div>
    </div>

    <div class="kpi-bar">
        <div class="kpi">
            <div class="label">Avoimia yhteensä</div>
            <div class="value">{grand_total:,}</div>
            <div class="sub">seuratut kategoriat</div>
        </div>
        <div class="kpi">
            <div class="label">Kategorioita</div>
            <div class="value">{len(categories)}</div>
            <div class="sub">seurannassa</div>
        </div>
        <div class="kpi">
            <div class="label">Päivitetty</div>
            <div class="value" style="font-size:1.1rem">{update_time}</div>
            <div class="sub">automaattinen ajo</div>
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
            <h2>Hakutermit kategorioittain</h2>
            <p style="color:#94a3b8;font-size:0.85rem;margin-bottom:1rem;">
                Duunitori-haku: <code style="color:#60a5fa">+sana</code> = AND-pakotus.
                <strong>sum</strong> = eri käsitteet, tulokset lasketaan yhteen.
                <strong>best</strong> = synonyymit, suurin tulos valitaan.
            </p>
            <table>
                <thead>
                    <tr>
                        <th>Kategoria</th>
                        <th>Hakutermit</th>
                        <th class="num" style="width:80px">Tapa</th>
                    </tr>
                </thead>
                <tbody>
"""
    for cat in categories:
        cfg = CATEGORIES[cat]
        terms_str = " , ".join(f'<code style="color:#e2e8f0">{t}</code>' for t in cfg["terms"])
        mode_label = "summa" if cfg["mode"] == "sum" else "paras"
        mode_color = "#4ade80" if cfg["mode"] == "sum" else "#60a5fa"
        html += f"""                    <tr>
                        <td>{cat}</td>
                        <td>{terms_str}</td>
                        <td class="num" style="color:{mode_color}">{mode_label}</td>
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
        Automaattinen päivittäinen ajo &middot; Data: Duunitori
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
                        backgroundColor: '#1e293b',
                        borderColor: '#475569',
                        borderWidth: 1,
                        titleColor: '#f8fafc',
                        bodyColor: '#e2e8f0',
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
    print(f"=== IT-työpaikkojen seuranta {date.today().isoformat()} ===\n")

    today_results = scrape_all()

    history = load_history()
    today_str = date.today().isoformat()
    history = [h for h in history if h["date"] != today_str]
    history.append(today_results)

    save_history(history)
    print(f"\nData: {HISTORY_FILE}")

    generate_html(history)

    print("\n=== Yhteenveto ===")
    sorted_cats = sorted(
        today_results["categories"].items(),
        key=lambda x: x[1]["count"],
        reverse=True,
    )
    for cat, data in sorted_cats:
        print(f"  {cat:30s} {data['count']:5d}")

    total = sum(d["count"] for d in today_results["categories"].values())
    print(f"\n  {'YHTEENSÄ':30s} {total:5d}")


if __name__ == "__main__":
    main()
