#!/usr/bin/env python3
"""Génère la carte de profil affichée dans le README : un SVG façon « neofetch ».

    python build.py             # met à jour les statistiques via l'API GitHub, puis génère les SVG
    python build.py --offline   # réutilise stats.json, sans appel réseau

Entrées  : profil.toml (textes), ascii/portrait_{dark,light}.txt (portrait), stats.json (dernières statistiques).
Sorties  : assets/profil-{fr,en}-{dark,light}.svg
Aucune dépendance hors bibliothèque standard (Python 3.11 ou plus).

Chaque ligne de texte est posée sur une grille fixe (attribut textLength) : l'alignement ne dépend
donc pas de la police à chasse fixe disponible chez le visiteur.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
STATS_FILE = ROOT / "stats.json"
LANGS = ("fr", "en")
API = "https://api.github.com"

# --------------------------------------------------------------------------- géométrie (pixels)
BAR_H = 36                      # barre de titre de la fenêtre
PAD_X = 24
ART_CW, ART_CH = 4.2, 8.4       # case du portrait (largeur, hauteur)
INFO_FS, INFO_LH = 14, 20       # corps et interligne du bloc d'informations
INFO_CW = INFO_FS * 0.6         # largeur d'un caractère : la plus large des polices à chasse fixe usuelles
INFO_COLS = 62                  # caractères disponibles par ligne
VAL_COL, PROJ_COL = 15, 25      # colonne où commencent les valeurs / les résultats de projets
FONT = "Consolas,'Cascadia Mono','SF Mono',SFMono-Regular,Menlo,'DejaVu Sans Mono','Liberation Mono','Courier New',monospace"

THEMES = {
    "dark": dict(bg="#0d1117", bar="#161b22", border="#30363d", text="#c9d1d9", key="#ffa657", value="#a5d6ff",
                 dots="#586069", ok="#56d364", warn="#e3b341", art="#c9d1d9", muted="#8b949e"),
    "light": dict(bg="#ffffff", bar="#f6f8fa", border="#d0d7de", text="#24292f", key="#953800", value="#0a3069",
                  dots="#afb8c1", ok="#1a7f37", warn="#9a6700", art="#24292f", muted="#57606a"),
}


# --------------------------------------------------------------------------- statistiques GitHub

def _get(url: str, raw: bool = False):
    headers = {"User-Agent": "profile-readme-builder", "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith(API):
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as resp:
        data = resp.read()
    return data.decode("utf-8", "replace") if raw else json.loads(data)


def collect_stats(login: str) -> dict:
    """Dépôts publics (hors forks, dépôts vides et dépôt de profil), tests pytest, état de la CI."""
    user = _get(f"{API}/users/{login}")
    repos = [r for r in _get(f"{API}/users/{login}/repos?per_page=100&type=owner")
             if not r["fork"] and not r["private"] and r["size"] > 0 and r["name"].lower() != login.lower()]
    tests = ci_ok = ci_total = 0
    for r in repos:
        name, branch = r["name"], r["default_branch"]
        tree = _get(f"{API}/repos/{login}/{name}/git/trees/{branch}?recursive=1")["tree"]
        for entry in tree:
            if entry["type"] == "blob" and re.search(r"(^|/)test_[^/]*\.py$", entry["path"]):
                source = _get(f"https://raw.githubusercontent.com/{login}/{name}/{branch}/{entry['path']}", raw=True)
                tests += len(re.findall(r"^\s*def test_", source, flags=re.M))
        runs = _get(f"{API}/repos/{login}/{name}/actions/runs?per_page=1&status=completed&branch={branch}")["workflow_runs"]
        if runs:
            ci_total += 1
            ci_ok += runs[0]["conclusion"] == "success"
    return {"repos": len(repos), "tests": tests, "ci_ok": ci_ok, "ci_total": ci_total,
            "stars": sum(r["stargazers_count"] for r in repos), "followers": user["followers"]}


def load_stats(login: str, offline: bool) -> dict:
    if not offline:
        try:
            stats = collect_stats(login)
            STATS_FILE.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8", newline="\n")
            return stats
        except Exception as exc:   # réseau coupé, quota dépassé : on garde les dernières valeurs connues
            print(f"! statistiques non mises à jour ({exc}) : réutilisation de stats.json", file=sys.stderr)
    if not STATS_FILE.exists():
        sys.exit("stats.json absent : lancer une première fois « python build.py » avec un accès réseau")
    return json.loads(STATS_FILE.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- mise en lignes

def tr(value, lang: str) -> str:
    return value[lang] if isinstance(value, dict) else value


def kv(key: str, value: str, col: int, value_cls: str = "v") -> list[tuple[str, str]]:
    """« Clé: ....... valeur » : les points de conduite alignent toutes les valeurs sur la colonne `col`."""
    dots = col - len(key) - 3
    if dots < 2:
        sys.exit(f"clé trop longue pour la colonne {col} : « {key} »")
    return [("k", key), ("t", ":"), ("d", " " + "." * dots + " "), (value_cls, value)]


def build_lines(cfg: dict, stats: dict, lang: str) -> list[dict]:
    """Liste de lignes : {segs: [(classe, texte)], indent: colonnes, rule: bool, cursor: bool}."""
    lines: list[dict] = [{"segs": [("k", cfg["user"]), ("t", "@"), ("k", cfg["host"])], "rule": True}]
    for item in cfg["info"]:
        if item.get("blank"):
            lines.append({"segs": []})
            continue
        cls = "ok" if item.get("highlight") else "v"
        lines.append({"segs": kv(tr(item["key"], lang), tr(item["value"], lang), VAL_COL, cls)})
        if "more" in item:
            lines.append({"segs": [("m", tr(item["more"], lang))], "indent": VAL_COL})
    lines += [{"segs": []}, {"segs": [("t", "- " + tr(cfg["titles"]["projects"], lang))], "rule": True}]
    lines += [{"segs": kv(p["repo"], tr(p["result"], lang), PROJ_COL)} for p in cfg["projects"]]
    lines += [{"segs": []}, {"segs": [("t", "- " + tr(cfg["titles"]["contact"], lang))], "rule": True}]
    lines += [{"segs": kv(tr(c["key"], lang), tr(c["value"], lang), VAL_COL)} for c in cfg["contact"]]

    labels = cfg["stats"]
    parts = [(tr(labels["repos"], lang), str(stats["repos"]), "v"), (tr(labels["tests"], lang), str(stats["tests"]), "v")]
    if stats["ci_total"]:
        ci_cls = "ok" if stats["ci_ok"] == stats["ci_total"] else "warn"
        parts.append((tr(labels["ci"], lang), f"{stats['ci_ok']}/{stats['ci_total']}", ci_cls))
    parts += [(tr(labels[k], lang), str(stats[k]), "v") for k in ("stars", "followers") if stats[k] > 0]
    segs: list[tuple[str, str]] = []
    for i, (label, value, cls) in enumerate(parts):
        segs += ([("d", " | ")] if i else []) + [("k", label), ("t", ": "), (cls, value)]
    lines += [{"segs": []}, {"segs": [("t", "- " + tr(cfg["titles"]["github"], lang))], "rule": True}, {"segs": segs}]
    lines += [{"segs": []}, {"segs": [("k", f"{cfg['user']}@{cfg['host']}"), ("t", ":"), ("v", "~"), ("t", "$")], "cursor": True}]

    for line in lines:
        width = line.get("indent", 0) + sum(len(text) for _, text in line["segs"])
        if width > INFO_COLS:
            sys.exit(f"ligne trop longue ({width} > {INFO_COLS} caractères, {lang}) : "
                     + "".join(text for _, text in line["segs"]))
    return lines


# --------------------------------------------------------------------------- SVG

def esc(text: str) -> str:
    return html.escape(text, quote=False)


def render(cfg: dict, stats: dict, lang: str, theme: str) -> str:
    c = THEMES[theme]
    lines = build_lines(cfg, stats, lang)
    art = (ROOT / "ascii" / f"portrait_{theme}.txt").read_text(encoding="utf-8").rstrip("\n").split("\n")
    art_cols = max(len(row) for row in art)
    art_w, art_h = art_cols * ART_CW, len(art) * ART_CH
    info_x = PAD_X + art_w + 28
    y0 = BAR_H + 36
    W = round(info_x + INFO_COLS * INFO_CW + 20)
    H = round(max(y0 + (len(lines) - 1) * INFO_LH + 24, BAR_H + art_h + 40))

    title = f"{cfg['user']}@{cfg['host']}"
    label = " · ".join("".join(" " if cls == "d" else text for cls, text in line["segs"])   # sans points de conduite
                       for line in lines[1:6] if line["segs"])
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'font-family="{FONT}" role="img" aria-label="{html.escape(title + " — " + label)}">',
        f"<title>{esc(title)}</title>",
        "<style>",
        f".t{{fill:{c['text']}}}.k{{fill:{c['key']}}}.v{{fill:{c['value']}}}.d{{fill:{c['dots']}}}"
        f".m{{fill:{c['muted']}}}.ok{{fill:{c['ok']}}}.warn{{fill:{c['warn']}}}",
        f".info{{font-size:{INFO_FS}px}}.art{{font-size:{ART_CW / 0.6:.2f}px;fill:{c['art']}}}",
        "@keyframes in{from{opacity:0}}@keyframes blink{50%{opacity:0}}",
        ".a{animation:in .4s ease-out both}.cur{animation:blink 1.1s steps(1) 2.4s infinite}",
        "@media (prefers-reduced-motion:reduce){.a,.cur{animation:none}}",
        "</style>",
        # Fenêtre : fond, barre de titre, trois pastilles.
        f'<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="10" fill="{c["bg"]}" stroke="{c["border"]}"/>',
        f'<path d="M.5 {BAR_H}V10.5a10 10 0 0 1 10-10H{W - 10.5}a10 10 0 0 1 10 10V{BAR_H}z" fill="{c["bar"]}" stroke="{c["border"]}"/>',
        '<circle cx="22" cy="18" r="5.5" fill="#ff5f57"/><circle cx="41" cy="18" r="5.5" fill="#febc2e"/>'
        '<circle cx="60" cy="18" r="5.5" fill="#28c840"/>',
        f'<text x="{W / 2}" y="22.5" text-anchor="middle" font-size="12.5" fill="{c["muted"]}">{esc(title)}: ~</text>',
    ]

    # Portrait : chaque suite de caractères est placée sur la grille, sans dépendre des espaces.
    art_y = BAR_H + (H - BAR_H - art_h) / 2 + ART_CH * 0.78
    out.append('<g class="art">')
    for r, row in enumerate(art):
        runs = "".join(
            f'<text x="{PAD_X + m.start() * ART_CW:.1f}" y="{art_y + r * ART_CH:.1f}" '
            f'textLength="{len(m.group()) * ART_CW:.1f}" lengthAdjust="spacing">{esc(m.group())}</text>'
            for m in re.finditer(r"\S+(?: \S+)*", row))
        if runs:
            out.append(f'<g class="a" style="animation-delay:{r * 22}ms">{runs}</g>')
    out.append("</g>")

    # Informations.
    out.append('<g class="info">')
    right = info_x + INFO_COLS * INFO_CW
    for i, line in enumerate(lines):
        if not line["segs"]:
            continue
        y = y0 + i * INFO_LH
        x = info_x + line.get("indent", 0) * INFO_CW
        n = sum(len(text) for _, text in line["segs"])
        spans = "".join(f'<tspan class="{cls}">{esc(text)}</tspan>' for cls, text in line["segs"])
        parts = [f'<text x="{x:.1f}" y="{y}" textLength="{n * INFO_CW:.1f}" lengthAdjust="spacing" xml:space="preserve">{spans}</text>']
        if line.get("rule"):
            parts.append(f'<line x1="{x + (n + 1) * INFO_CW:.1f}" y1="{y - 4.5}" x2="{right:.1f}" y2="{y - 4.5}" stroke="{c["dots"]}"/>')
        if line.get("cursor"):
            parts.append(f'<rect class="cur" x="{x + (n + 1) * INFO_CW:.1f}" y="{y - 12}" width="{INFO_CW:.1f}" height="15" fill="{c["text"]}"/>')
        out.append(f'<g class="a" style="animation-delay:{400 + i * 55}ms">{"".join(parts)}</g>')
    out += ["</g>", "</svg>"]
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="ne pas interroger l'API GitHub")
    args = ap.parse_args()
    cfg = tomllib.loads((ROOT / "profil.toml").read_text(encoding="utf-8"))
    stats = load_stats(cfg["login"], args.offline)
    ASSETS.mkdir(exist_ok=True)
    for lang in LANGS:
        for theme in THEMES:
            path = ASSETS / f"profil-{lang}-{theme}.svg"
            path.write_text(render(cfg, stats, lang, theme), encoding="utf-8", newline="\n")
    print(f"statistiques : {stats}")
    print(f"cartes : {ASSETS}{os.sep}profil-{{{','.join(LANGS)}}}-{{{','.join(THEMES)}}}.svg")


if __name__ == "__main__":
    main()
