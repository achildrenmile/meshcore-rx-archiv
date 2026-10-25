"""Archiv der Empfangskarte: holt die Zellen der CoreScope-Karte und fuehrt sie dauerhaft zusammen.

Die Karte zeigt hoechstens 30 Tage. Dieses Modul haelt fest, was sie je gezeigt hat:
pro Zelle bester SNR, hoechste Anzahl, erster und letzter Tag, gehoerte Knoten, Tage mit
Aktivitaet und welche Teilnehmer sie gemessen haben. Reine Standardbibliothek.
"""
import datetime, json, sqlite3, time, urllib.parse, urllib.request

SCHEMA = """
CREATE TABLE IF NOT EXISTS cells(cell TEXT PRIMARY KEY, lat REAL, lon REAL, first_seen TEXT, last_seen TEXT,
  best_snr REAL, max_count INTEGER, has_sig INTEGER);
CREATE TABLE IF NOT EXISTS daily(day TEXT, cell TEXT, count INTEGER, best_snr REAL, PRIMARY KEY(day, cell));
CREATE TABLE IF NOT EXISTS cell_nodes(cell TEXT, prefix TEXT, name TEXT, best_snr REAL, max_count INTEGER,
  last_seen TEXT, PRIMARY KEY(cell, prefix));
CREATE TABLE IF NOT EXISTS gaps(cell TEXT PRIMARY KEY, lat REAL, lon REAL, first_seen TEXT, last_seen TEXT, samples INTEGER);
CREATE TABLE IF NOT EXISTS noise(cell TEXT PRIMARY KEY, lat REAL, lon REAL, first_seen TEXT, last_seen TEXT,
  median REAL, quietest REAL, noisiest REAL, count INTEGER);
CREATE TABLE IF NOT EXISTS rx(pubkey TEXT PRIMARY KEY, name TEXT, first_seen TEXT, last_seen TEXT);
CREATE TABLE IF NOT EXISTS cell_rx(cell TEXT, pubkey TEXT, best_snr REAL, max_count INTEGER, last_seen TEXT,
  PRIMARY KEY(cell, pubkey));
CREATE TABLE IF NOT EXISTS runs(ts TEXT, kind TEXT, cells INTEGER, gaps INTEGER, noise INTEGER, ok INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
"""


def verbinden(pfad):
    db = sqlite3.connect(pfad)
    db.executescript(SCHEMA)
    return db


def heute():
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def holen(basis, pfad, params, versuche=3):
    url = basis.rstrip("/") + "/" + pfad + "?" + urllib.parse.urlencode(params)
    for i in range(versuche):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "rx-archiv/1"}), timeout=120) as r:
                return json.load(r)
        except Exception:
            if i == versuche - 1:
                raise
            time.sleep(5 * (i + 1))


def mitte(ring):
    pts = ring[:-1] if ring[0] == ring[-1] else ring
    return sum(p[1] for p in pts) / len(pts), sum(p[0] for p in pts) / len(pts)


def _max(a, b):
    return b if a is None else a if b is None else max(a, b)


def _min(a, b):
    return b if a is None else a if b is None else min(a, b)


def zellen_zusammenfuehren(db, features, tag, daily_tag=None):
    """features: Zellen aus rx-coverage. daily_tag: Datum, wenn die Antwort ein 24-h-Fenster ist."""
    bestand = {r[0]: r for r in db.execute("SELECT cell, first_seen, best_snr, max_count, has_sig FROM cells")}
    for f in features:
        p = f["properties"]; cid = p["cell"]
        lat, lon = mitte(f["geometry"]["coordinates"][0])
        alt = bestand.get(cid)
        snr = p.get("best_snr") if p.get("has_sig") else None
        if alt:
            db.execute("UPDATE cells SET last_seen=?, best_snr=?, max_count=?, has_sig=? WHERE cell=?",
                       (tag, _max(alt[2], snr), max(alt[3] or 0, p["count"]), int(bool(alt[4] or p.get("has_sig"))), cid))
        else:
            db.execute("INSERT INTO cells VALUES(?,?,?,?,?,?,?,?)", (cid, lat, lon, tag, tag, snr, p["count"], int(bool(p.get("has_sig")))))
        for n in p.get("nodes", []):
            key = n.get("prefix") or n.get("name")
            r = db.execute("SELECT best_snr, max_count FROM cell_nodes WHERE cell=? AND prefix=?", (cid, key)).fetchone()
            if r:
                db.execute("UPDATE cell_nodes SET name=COALESCE(?,name), best_snr=?, max_count=?, last_seen=? WHERE cell=? AND prefix=?",
                           (n.get("name"), _max(r[0], n.get("snr")), max(r[1] or 0, n.get("count") or 0), tag, cid, key))
            else:
                db.execute("INSERT INTO cell_nodes VALUES(?,?,?,?,?,?)", (cid, key, n.get("name"), n.get("snr"), n.get("count") or 0, tag))
        if daily_tag:
            r = db.execute("SELECT count, best_snr FROM daily WHERE day=? AND cell=?", (daily_tag, cid)).fetchone()
            if r:
                db.execute("UPDATE daily SET count=?, best_snr=? WHERE day=? AND cell=?",
                           (max(r[0], p["count"]), _max(r[1], snr), daily_tag, cid))
            else:
                db.execute("INSERT INTO daily VALUES(?,?,?,?)", (daily_tag, cid, p["count"], snr))
    return len(features)


def luecken_zusammenfuehren(db, gaps, tag):
    for g in gaps:
        cid = g["properties"]["cell"]; lat, lon = mitte(g["geometry"]["coordinates"][0])
        n = g["properties"].get("samples") or 1
        r = db.execute("SELECT samples FROM gaps WHERE cell=?", (cid,)).fetchone()
        if r:
            db.execute("UPDATE gaps SET last_seen=?, samples=? WHERE cell=?", (tag, max(r[0] or 0, n), cid))
        else:
            db.execute("INSERT INTO gaps VALUES(?,?,?,?,?,?)", (cid, lat, lon, tag, tag, n))
    return len(gaps)


def rauschen_zusammenfuehren(db, features, tag):
    for f in features:
        p = f["properties"]; cid = p["cell"]; lat, lon = mitte(f["geometry"]["coordinates"][0])
        r = db.execute("SELECT quietest, noisiest, count FROM noise WHERE cell=?", (cid,)).fetchone()
        if r:
            db.execute("UPDATE noise SET last_seen=?, median=?, quietest=?, noisiest=?, count=? WHERE cell=?",
                       (tag, p["median_noise_floor"], _min(r[0], p.get("quietest_noise_floor")),
                        _max(r[1], p.get("noisiest_noise_floor")), max(r[2] or 0, p["count"]), cid))
        else:
            db.execute("INSERT INTO noise VALUES(?,?,?,?,?,?,?,?,?)", (cid, lat, lon, tag, tag, p["median_noise_floor"],
                       p.get("quietest_noise_floor"), p.get("noisiest_noise_floor"), p["count"]))
    return len(features)


def teilnehmer_zusammenfuehren(db, basis, bbox, tag):
    n = 0
    for o in holen(basis, "rx-leaderboard", {"days": 30}).get("observers", []):
        pk = o["pubkey"].lower()
        r = db.execute("SELECT 1 FROM rx WHERE pubkey=?", (pk,)).fetchone()
        if r:
            db.execute("UPDATE rx SET name=?, last_seen=? WHERE pubkey=?", (o.get("name"), tag, pk))
        else:
            db.execute("INSERT INTO rx VALUES(?,?,?,?)", (pk, o.get("name"), tag, tag))
        feats = holen(basis, "rx-coverage", {"bbox": bbox, "z": 14, "days": 30, "rx": pk})["features"]
        for f in feats:
            p = f["properties"]; snr = p.get("best_snr") if p.get("has_sig") else None
            old = db.execute("SELECT best_snr, max_count FROM cell_rx WHERE cell=? AND pubkey=?", (p["cell"], pk)).fetchone()
            if old:
                db.execute("UPDATE cell_rx SET best_snr=?, max_count=?, last_seen=? WHERE cell=? AND pubkey=?",
                           (_max(old[0], snr), max(old[1] or 0, p["count"]), tag, p["cell"], pk))
            else:
                db.execute("INSERT INTO cell_rx VALUES(?,?,?,?,?)", (p["cell"], pk, snr, p["count"], tag))
        n += 1
    return n


def lauf(db, basis, bbox, voll):
    """Ein Durchgang. Jeder Schritt faengt seinen Fehler selbst ab; der Lauf gilt als ok, wenn mindestens die
    Tagesabfrage durchkam."""
    tag = heute(); ergebnis = {"cells": 0, "gaps": 0, "noise": 0}; fehler = []
    erster = db.execute("SELECT v FROM meta WHERE k='backfill_day'").fetchone() is None and \
        db.execute("SELECT COUNT(*) FROM cells").fetchone()[0] == 0

    def schritt(name, f):
        try:
            f(); db.commit()
        except Exception as e:
            db.rollback(); fehler.append(f"{name}: {e}")

    def tag_abfrage():
        a = holen(basis, "rx-coverage", {"bbox": bbox, "z": 14, "days": 1, "gaps": 1})
        ergebnis["cells"] = zellen_zusammenfuehren(db, a["features"], tag, daily_tag=tag)
        ergebnis["gaps"] = luecken_zusammenfuehren(db, a.get("gaps", []), tag)
    schritt("tag", tag_abfrage)

    def rauschen_tag():
        ergebnis["noise"] = rauschen_zusammenfuehren(db, holen(basis, "rf-noise", {"bbox": bbox, "z": 14, "days": 1})["features"], tag)
    schritt("rauschen-tag", rauschen_tag)

    if voll:
        def monat():
            a = holen(basis, "rx-coverage", {"bbox": bbox, "z": 14, "days": 30, "gaps": 1})
            # Beim ersten Lauf: alles aus dem 30-Tage-Fenster, das nicht in den letzten 24 h lag, gehoert zu "vor Archivstart"
            vorher = (datetime.date.fromisoformat(tag) - datetime.timedelta(days=1)).isoformat()
            zellen_zusammenfuehren(db, a["features"], tag, daily_tag=vorher if erster else None)
            if erster:
                db.execute("INSERT OR REPLACE INTO meta VALUES('backfill_day', ?)", (vorher,))
                # Zellen, die auch in den letzten 24 h aktiv waren, gehoeren nicht zu "vorher"
                db.execute("DELETE FROM daily WHERE day=? AND cell IN (SELECT cell FROM daily WHERE day=?)", (vorher, tag))
            luecken_zusammenfuehren(db, a.get("gaps", []), tag)
        schritt("monat", monat)
        schritt("rauschen-monat", lambda: rauschen_zusammenfuehren(
            db, holen(basis, "rf-noise", {"bbox": bbox, "z": 14, "days": 30})["features"], tag))
        schritt("teilnehmer", lambda: teilnehmer_zusammenfuehren(db, basis, bbox, tag))
        db.execute("INSERT OR REPLACE INTO meta VALUES('letzter_voller_lauf', ?)", (datetime.datetime.now(datetime.timezone.utc).isoformat(),))
    ok = int(not any(s.startswith("tag:") for s in fehler))
    db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
               "voll" if voll else "tag", ergebnis["cells"], ergebnis["gaps"], ergebnis["noise"], ok, "; ".join(fehler)[:500]))
    db.commit()
    return ok, fehler
