"""Boox vesti: RSS opiniona i vesti -> DeepSeek sažeci -> sopstveni RSS feed + e-ink HTML.

Opinion tekstovi idu pojedinačno (teza, argumenti, zaključak, ton); naslovi vesti se
skupljaju u jedan digest grupisan po događaju. Stanje (obrađeni linkovi i stavke) je u
site/stanje.json, pa svako pokretanje obrađuje samo novo.

    python vesti.py             # obradi novo, upiši site/{feed,opinioni,vesti}.xml i index.html
    python vesti.py --max 1     # brza proba: najviše 1 opinion po izvoru
"""
import argparse
import html
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser
import requests
import trafilatura
import yaml
from openai import OpenAI

KOREN = Path(__file__).parent
SITE = KOREN / "site"
BG = ZoneInfo("Europe/Belgrade")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")
MIN_TEKST = 800     # kraće od ovoga = paywall ili neuspelo izvlačenje, ostaje samo najava

SISTEM_OPINION = """Praviš sažetke opinion tekstova (kolumne, komentari, eseji) za čitaoca na e-ink čitaču.
Piši na srpskom jeziku, latinicom, bez obzira na jezik originala.
Verno prenesi stav autora: ne ocenjuj ga, ne dodaj svoje mišljenje, ne ublažavaj ga.
Vrati JSON:
{"teza": "glavna tvrdnja autora, jedna rečenica",
 "argumenti": ["3-5 ključnih argumenata ili dokaza, svaki jedna rečenica"],
 "zakljucak": "šta autor predlaže ili čime zaključuje, jedna rečenica",
 "ton": "1-3 reči, npr. ironičan, analitičan, alarmantan"}"""

SISTEM_VESTI = """Dobijaš listu naslova vesti iz više izvora, u formatu [indeks] izvor | naslov | opis.
Grupiši ih po događaju (isti događaj iz više izvora = jedna stavka) i poređaj po važnosti.
Izostavi sport, zabavu, estradu, horoskop i promotivne tekstove, osim ako su zaista velika vest.
Piši na srpskom jeziku, latinicom, činjenično, bez ocena.
Vrati JSON:
{"dogadjaji": [{"naslov": "kratak naslov događaja",
                "sazetak": "2-3 rečenice: šta se desilo, ko, gde, zašto je bitno",
                "izvori": [indeksi vesti iz liste]}]}"""


def cist(s):
    """HTML iz RSS opisa u običan tekst u jednom redu."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def esc(s):
    return html.escape(s or "", quote=True)


def ucitaj_feed(izvor, od, videno):
    try:
        r = requests.get(izvor["url"], headers={"User-Agent": UA}, timeout=20)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"! {izvor['ime']}: {e}", file=sys.stderr)
        return []
    out = []
    for e in feedparser.parse(r.content).entries:
        t = e.get("published_parsed") or e.get("updated_parsed")
        kad = datetime(*t[:6], tzinfo=timezone.utc) if t else datetime.now(timezone.utc)
        link = e.get("link")
        if not link or link in videno or kad < od:
            continue
        naslov, autor = cist(e.get("title")), cist(e.get("author"))
        # "Piše Ivan Mrđen: Srbija nije Belgija" -> autor iz naslova (Nova i slični)
        m = re.match(r"Piše\s+([^:]{3,40}):\s*(.+)", naslov)
        if m:
            autor, naslov = m.groups()
        out.append({"izvor": izvor["ime"], "link": link, "naslov": naslov, "autor": autor,
                    "opis": cist(e.get("summary"))[:600], "kad": kad.isoformat()})
    return out


def preuzmi_tekst(url):
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=25)
        r.raise_for_status()
    except requests.RequestException:
        return "", ""
    # bajtovi, ne r.text: requests bez charset-a u zaglavlju pogađa latin-1 i kvari đ/č/ć
    d = trafilatura.bare_extraction(r.content, url=url, with_metadata=True)
    if not d:
        return "", ""
    d = d if isinstance(d, dict) else d.as_dict()
    return d.get("text") or "", d.get("author") or ""


def pitaj(client, sistem, tekst, max_tokens=1500):
    for _ in range(3):
        try:
            r = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": sistem}, {"role": "user", "content": tekst}],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=max_tokens,
                extra_body={"thinking": {"type": "disabled"}},
            )
            return json.loads(r.choices[0].message.content)
        except Exception as e:  # noqa: BLE001 - mreža, rate limit ili neispravan JSON: probaj ponovo
            greska = e
    print(f"! LLM: {greska}", file=sys.stderr)
    return None


def obradi_opinion(client, s):
    tekst, autor = preuzmi_tekst(s["link"])
    s["autor"] = s["autor"] or autor
    o = None
    if len(tekst) >= MIN_TEKST:
        o = pitaj(client, SISTEM_OPINION,
                  f"Izvor: {s['izvor']}\nAutor: {s['autor'] or 'nepoznat'}\nNaslov: {s['naslov']}\n\n{tekst[:14000]}")
    if o:
        delovi = [f"<p><b>Teza:</b> {esc(o.get('teza'))}</p>"]
        if o.get("argumenti"):
            delovi.append("<ul>" + "".join(f"<li>{esc(a)}</li>" for a in o["argumenti"]) + "</ul>")
        if o.get("zakljucak"):
            delovi.append(f"<p><b>Zaključak:</b> {esc(o['zakljucak'])}</p>")
        if o.get("ton"):
            delovi.append(f"<p><i>Ton: {esc(o['ton'])}</i></p>")
    else:
        delovi = [f"<p>{esc(s['opis'])}</p>", "<p><i>(samo najava: ceo tekst nije dostupan)</i></p>"]
    potpis = f"{esc(s['autor'])}, {esc(s['izvor'])}" if s["autor"] else esc(s["izvor"])
    delovi.append(f'<p><a href="{esc(s["link"])}">Ceo tekst</a> · {potpis}</p>')
    naslov = f"{s['autor']}: {s['naslov']}" if s["autor"] else s["naslov"]
    return {"id": s["link"], "vrsta": "opinion", "naslov": f"[{s['izvor']}] {naslov}", "link": s["link"],
            "autor": s["autor"], "izvor": s["izvor"], "kad": s["kad"], "html": "\n".join(delovi)}


def napravi_digest(client, vesti, sad, url):
    lista = "\n".join(f"[{i}] {v['izvor']} | {v['naslov']} | {v['opis'][:300]}" for i, v in enumerate(vesti))
    o = pitaj(client, SISTEM_VESTI, lista, max_tokens=6000)
    if not o or not o.get("dogadjaji"):
        return None
    delovi = []
    for d in o["dogadjaji"]:
        izv = {}     # po jedan link po izvoru, da ne piše "BBC · BBC · BBC"
        for i in d.get("izvori", []):
            if isinstance(i, int) and 0 <= i < len(vesti):
                izv.setdefault(vesti[i]["izvor"], vesti[i]["link"])
        linkovi = " · ".join(f'<a href="{esc(link)}">{esc(ime)}</a>' for ime, link in izv.items())
        delovi.append(f"<h3>{esc(d.get('naslov'))}</h3>\n<p>{esc(d.get('sazetak'))}</p>\n<p><small>{linkovi}</small></p>")
    lokalno = sad.astimezone(BG)
    oznaka = f"digest-{lokalno:%Y%m%d-%H%M}"
    return {"id": oznaka, "vrsta": "vesti", "naslov": f"Vesti {lokalno:%d.%m. u %H:%M} ({len(delovi)} događaja)",
            "link": f"{url}/#{oznaka}", "autor": "", "izvor": "Digest", "kad": sad.isoformat(),
            "html": "\n".join(delovi)}


def rss(naslov, opis, url, putanja, stavke):
    redovi = []
    for s in stavke:
        autor = f"<dc:creator>{esc(s['autor'])}</dc:creator>" if s.get("autor") else ""
        telo = s["html"].replace("]]>", "]]&gt;")
        redovi.append(
            f"<item><title>{esc(s['naslov'])}</title><link>{esc(s['link'])}</link>"
            f'<guid isPermaLink="false">{esc(s["id"])}</guid>'
            f"<pubDate>{format_datetime(datetime.fromisoformat(s['kad']))}</pubDate>{autor}"
            f"<category>{esc(s['izvor'])}</category><description><![CDATA[{telo}]]></description></item>")
    sad = format_datetime(datetime.now(timezone.utc))
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:atom="http://www.w3.org/2005/Atom">'
            f"<channel><title>{esc(naslov)}</title><link>{esc(url)}/</link><description>{esc(opis)}</description>"
            f'<language>sr</language><lastBuildDate>{sad}</lastBuildDate>'
            f'<atom:link href="{esc(url)}/{putanja}" rel="self" type="application/rss+xml"/>\n'
            + "\n".join(redovi) + "\n</channel></rss>\n")


def index_html(naslov, stavke):
    """Jedna strana za e-ink browser: poslednji digest pa opinioni, bez JS-a i slika."""
    digest = next((s for s in stavke if s["vrsta"] == "vesti"), None)
    opinioni = [s for s in stavke if s["vrsta"] == "opinion"][:60]
    telo = []
    if digest:
        telo.append(f'<h2 id="{esc(digest["id"])}">{esc(digest["naslov"])}</h2>\n{digest["html"]}')
    telo.append("<h2>Opinioni</h2>")
    for s in opinioni:
        telo.append(f'<article><h3>{esc(s["naslov"])}</h3>\n{s["html"]}</article>')
    return f"""<!doctype html>
<html lang="sr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(naslov)}</title>
<link rel="alternate" type="application/rss+xml" href="feed.xml">
<style>
body{{font:20px/1.5 Georgia,"Noto Serif",serif;color:#000;background:#fff;max-width:38em;margin:0 auto;padding:16px}}
a{{color:#000}} h2{{border-bottom:3px solid #000;margin-top:2em}} h3{{margin:1.4em 0 .3em}}
article{{border-bottom:1px solid #000;padding-bottom:.6em}} small{{font-size:16px}}
</style></head><body>
<h1>{esc(naslov)}</h1>
<p><small>Feed: <a href="feed.xml">sve</a> · <a href="opinioni.xml">opinioni</a> · <a href="vesti.xml">vesti</a></small></p>
{chr(10).join(telo)}
</body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, help="najviše N opinion tekstova po izvoru (pregazi podešavanje)")
    args = ap.parse_args()

    cfg = yaml.safe_load((KOREN / "sources.yaml").read_text())
    p = cfg["podesavanja"]
    url = os.environ.get("SITE_URL", p["url"]).rstrip("/")
    max_po_izvoru = args.max or p["max_po_izvoru"]
    kljuc = os.environ.get("DEEPSEEK_API_KEY") or sys.exit("Nema DEEPSEEK_API_KEY")
    client = OpenAI(api_key=kljuc, base_url="https://api.deepseek.com")

    SITE.mkdir(exist_ok=True)
    f_stanje = SITE / "stanje.json"
    stanje = json.loads(f_stanje.read_text()) if f_stanje.exists() else {"stavke": [], "videno": {}}
    videno = stanje["videno"]
    sad = datetime.now(timezone.utc)
    od = sad - timedelta(hours=p["starost_sati"])

    with ThreadPoolExecutor(8) as ex:
        opinioni = [s for lst in ex.map(lambda i: ucitaj_feed(i, od, videno), cfg["opinioni"])
                    for s in lst[:max_po_izvoru]]
        vesti = [s for lst in ex.map(lambda i: ucitaj_feed(i, od, videno), cfg["vesti"]) for s in lst]
        nove = list(ex.map(lambda s: obradi_opinion(client, s), opinioni))
    print(f"opinioni: {len(nove)}, vesti za digest: {len(vesti)}")

    vesti.sort(key=lambda v: v["kad"], reverse=True)
    vesti = vesti[:p["max_vesti_u_digestu"]]
    if vesti:
        digest = napravi_digest(client, vesti, sad, url)
        if digest:
            nove.append(digest)
        else:
            vesti = []      # digest nije uspeo: iste vesti ponovo sledeći put

    for s in opinioni + vesti:
        videno[s["link"]] = sad.isoformat()
    granica = (sad - timedelta(days=7)).isoformat()
    stanje["videno"] = {k: v for k, v in videno.items() if v >= granica}
    stavke = {s["id"]: s for s in stanje["stavke"] + nove}.values()
    stanje["stavke"] = sorted((s for s in stavke if s["kad"] >= granica), key=lambda s: s["kad"], reverse=True)
    f_stanje.write_text(json.dumps(stanje, ensure_ascii=False, indent=1))

    u_feedu = [s for s in stanje["stavke"] if s["kad"] >= (sad - timedelta(days=p["dana_u_feedu"])).isoformat()]
    naslov = p["naslov"]
    for ime, opis, vrste in (("feed.xml", "Opinioni i vesti, sažeto", ("opinion", "vesti")),
                             ("opinioni.xml", "Opinioni, sažeto", ("opinion",)),
                             ("vesti.xml", "Digest vesti po događaju", ("vesti",))):
        (SITE / ime).write_text(rss(f"{naslov}: {opis}", opis, url, ime,
                                    [s for s in u_feedu if s["vrsta"] in vrste]))
    (SITE / "index.html").write_text(index_html(naslov, u_feedu))
    (SITE / ".nojekyll").touch()


if __name__ == "__main__":
    main()
