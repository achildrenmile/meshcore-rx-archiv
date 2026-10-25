"""Zusatzwerkzeug, kein Datenweg: der Normalfall ist der Sammler, der alles ueber die Schnittstelle holt
(auch den Erstimport, siehe run.py). Das hier ist fuer den UMZUG eines Archivs und fuer gespeicherte Antworten.

    python -m collector.importieren --db /import/anderes-archiv.db
    python -m collector.importieren --geojson /import/rx-coverage.json --tag 2026-10-20 [--tagesscheibe]
    python -m collector.importieren --rauschen /import/rf-noise.json --tag 2026-10-20

--db            Umzug: fuehrt ein zweites Archiv (gleiches Schema) ein: erster Tag = frueheste, letzter = spaetester,
                bester SNR und hoechste Anzahl bleiben, Tagesscheiben und Zuordnungen werden vereinigt.
--geojson       liest eine gespeicherte Antwort der Karte (rx-coverage, auch mit "gaps"). --tag ist das Datum,
                das die Daten stammen; mit --tagesscheibe zaehlt die Antwort als 24-h-Fenster dieses Tages,
                ohne die Datei nur als Bestand.
--rauschen      liest eine gespeicherte rf-noise-Antwort.
Alle Angaben ueberschreiben nichts Besseres. Nach dem Import wird der Viewer-Export neu geschrieben.
Umgebung wie beim Sammler: DATA_DIR, WEB_DATA_DIR.
"""
import argparse, json, os, sys

from . import archiv, export

DATA = os.environ.get("DATA_DIR", "./data")
WEB = os.environ.get("WEB_DATA_DIR", "./web/data")
NIE = -9999.0


def _gr(a, b):    # groesser, NULL zaehlt als "nichts"
    return f"NULLIF(max(COALESCE({a},{NIE}),COALESCE({b},{NIE})),{NIE})"


def _kl(a, b):
    return f"NULLIF(min(COALESCE({a},{-NIE}),COALESCE({b},{-NIE})),{-NIE})"


# Tabelle -> (Spalten, Schluessel, Regel je Spalte beim Zusammenfuehren; q = Quelle, t = Ziel)
TABELLEN = {
    "cells": ("cell,lat,lon,first_seen,last_seen,best_snr,max_count,has_sig", "cell",
              {"first_seen": "min(t.first_seen,excluded.first_seen)", "last_seen": "max(t.last_seen,excluded.last_seen)",
               "best_snr": _gr("t.best_snr", "excluded.best_snr"), "max_count": "max(t.max_count,excluded.max_count)",
               "has_sig": "max(t.has_sig,excluded.has_sig)"}),
    "daily": ("day,cell,count,best_snr", "day,cell",
              {"count": "max(t.count,excluded.count)", "best_snr": _gr("t.best_snr", "excluded.best_snr")}),
    "cell_nodes": ("cell,prefix,name,best_snr,max_count,last_seen", "cell,prefix",
                   {"name": "COALESCE(excluded.name,t.name)", "best_snr": _gr("t.best_snr", "excluded.best_snr"),
                    "max_count": "max(t.max_count,excluded.max_count)", "last_seen": "max(t.last_seen,excluded.last_seen)"}),
    "gaps": ("cell,lat,lon,first_seen,last_seen,samples", "cell",
             {"first_seen": "min(t.first_seen,excluded.first_seen)", "last_seen": "max(t.last_seen,excluded.last_seen)",
              "samples": "max(t.samples,excluded.samples)"}),
    "noise": ("cell,lat,lon,first_seen,last_seen,median,quietest,noisiest,count", "cell",
              {"first_seen": "min(t.first_seen,excluded.first_seen)", "last_seen": "max(t.last_seen,excluded.last_seen)",
               "median": "CASE WHEN excluded.last_seen>=t.last_seen THEN excluded.median ELSE t.median END",
               "quietest": _kl("t.quietest", "excluded.quietest"), "noisiest": _gr("t.noisiest", "excluded.noisiest"),
               "count": "max(t.count,excluded.count)"}),
    "rx": ("pubkey,name,first_seen,last_seen", "pubkey",
           {"name": "CASE WHEN excluded.last_seen>=t.last_seen THEN excluded.name ELSE t.name END",
            "first_seen": "min(t.first_seen,excluded.first_seen)", "last_seen": "max(t.last_seen,excluded.last_seen)"}),
    "cell_rx": ("cell,pubkey,best_snr,max_count,last_seen", "cell,pubkey",
                {"best_snr": _gr("t.best_snr", "excluded.best_snr"), "max_count": "max(t.max_count,excluded.max_count)",
                 "last_seen": "max(t.last_seen,excluded.last_seen)"}),
}


def aus_db(db, pfad):
    if not os.path.isfile(pfad):
        raise FileNotFoundError(pfad)
    db.execute("ATTACH DATABASE ? AS q", (pfad,))
    try:
        n = {}
        for tab, (spalten, schluessel, regeln) in TABELLEN.items():
            if not db.execute("SELECT 1 FROM q.sqlite_master WHERE type='table' AND name=?", (tab,)).fetchone():
                continue
            setze = ", ".join(f"{k}={v}" for k, v in regeln.items())
            db.execute(f"INSERT INTO main.{tab}({spalten}) SELECT {spalten} FROM q.{tab} WHERE true "
                       f"ON CONFLICT({schluessel}) DO UPDATE SET {setze}".replace("t.", f"main.{tab}."))
            n[tab] = db.execute(f"SELECT COUNT(*) FROM q.{tab}").fetchone()[0]
        db.commit()
        return n
    finally:
        db.execute("DETACH DATABASE q")


def aus_geojson(db, pfad, tag, tagesscheibe):
    d = json.load(open(pfad, encoding="utf-8"))
    n = archiv.zellen_zusammenfuehren(db, d.get("features", []), tag, daily_tag=tag if tagesscheibe else None)
    g = archiv.luecken_zusammenfuehren(db, d.get("gaps", []), tag)
    db.commit()
    return {"zellen": n, "luecken": g}


def aus_rauschen(db, pfad, tag):
    n = archiv.rauschen_zusammenfuehren(db, json.load(open(pfad, encoding="utf-8")).get("features", []), tag)
    db.commit()
    return {"rauschen": n}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db"); ap.add_argument("--geojson"); ap.add_argument("--rauschen")
    ap.add_argument("--tag", help="Datum der Daten, JJJJ-MM-TT"); ap.add_argument("--tagesscheibe", action="store_true")
    a = ap.parse_args()
    if not (a.db or a.geojson or a.rauschen):
        ap.error("nichts zu importieren: --db, --geojson oder --rauschen angeben")
    if (a.geojson or a.rauschen) and not a.tag:
        ap.error("--tag ist fuer --geojson und --rauschen noetig")
    os.makedirs(DATA, exist_ok=True)
    db = archiv.verbinden(os.path.join(DATA, "archiv.db"))
    if a.db: print("db:", aus_db(db, a.db))
    if a.geojson: print("geojson:", aus_geojson(db, a.geojson, a.tag, a.tagesscheibe))
    if a.rauschen: print("rauschen:", aus_rauschen(db, a.rauschen, a.tag))
    meta = export.exportieren(db, WEB)
    print(f"Export neu geschrieben: {meta['zellen']} Zellen, {meta['luecken']} Luecken, {meta['rauschen']} Rauschen")


if __name__ == "__main__":
    main()
