"""Sammler: python -m collector.run [--einmal] [--voll] [--erstimport] [--intervall 3600]

Alle Daten kommen ueber die oeffentliche Schnittstelle der Karte, es wird keine Datenbankkopie gebraucht.
Der ERSTIMPORT geschieht automatisch beim ersten Start (leeres Archiv): dann wird das ganze 30-Tage-Fenster
geholt. --erstimport erzwingt dasselbe von Hand (Voll-Lauf, einmal), z.B. nach einem Ausfall von mehr als 30 Tagen.

Umgebung: MAP_BASE (https://map.carinthiamesh.com/api/), BBOX, DATA_DIR (./data), WEB_DATA_DIR (./web/data)
"""
import argparse, datetime, os, sys, time

from . import archiv, export

BASIS = os.environ.get("MAP_BASE", "https://map.carinthiamesh.com/api/")
BBOX = os.environ.get("BBOX", "45.6,12.0,47.7,15.6")
DATA = os.environ.get("DATA_DIR", "./data")
WEB = os.environ.get("WEB_DATA_DIR", "./web/data")


def log(*a):
    print(datetime.datetime.now().isoformat(timespec="seconds"), *a, flush=True)


def noetig_voll(db):
    r = db.execute("SELECT v FROM meta WHERE k='letzter_voller_lauf'").fetchone()
    if not r:
        return True
    letzter = datetime.datetime.fromisoformat(r[0])
    return (datetime.datetime.now(datetime.timezone.utc) - letzter) > datetime.timedelta(hours=20)


def durchgang(db, voll):
    ok, fehler = archiv.lauf(db, BASIS, BBOX, voll or noetig_voll(db))
    meta = export.exportieren(db, WEB)
    log("ok" if ok else "FEHLER", f"{meta['zellen']} Zellen, {meta['luecken']} Luecken, {meta['rauschen']} Rauschen", *fehler)
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--einmal", action="store_true"); ap.add_argument("--voll", action="store_true")
    ap.add_argument("--erstimport", action="store_true", help="Voll-Lauf, einmal, dann beenden")
    ap.add_argument("--intervall", type=int, default=3600)
    a = ap.parse_args()
    if a.erstimport:
        a.einmal = a.voll = True
    os.makedirs(DATA, exist_ok=True)
    db = archiv.verbinden(os.path.join(DATA, "archiv.db"))
    if db.execute("SELECT COUNT(*) FROM cells").fetchone()[0] == 0:
        log("Archiv ist leer: Erstimport aus dem 30-Tage-Fenster der Karte")
    while True:
        try:
            ok = durchgang(db, a.voll)
        except Exception as e:
            ok = False; log("ABBRUCH im Durchgang:", e)
        if a.einmal:
            sys.exit(0 if ok else 1)
        time.sleep(a.intervall)


if __name__ == "__main__":
    main()
