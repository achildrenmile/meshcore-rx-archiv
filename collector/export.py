"""Schreibt das Archiv als kompakte JSON-Dateien fuer den Viewer (web/data/)."""
import datetime, gzip, json, os


def _schreiben(pfad, obj):
    tmp = pfad + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, pfad)


def exportieren(db, ziel):
    os.makedirs(ziel, exist_ok=True)
    tage = [r[0] for r in db.execute("SELECT DISTINCT day FROM daily ORDER BY day")]
    tidx = {d: i for i, d in enumerate(tage)}
    knoten, kidx = [], {}

    def knoten_id(n):
        if n not in kidx:
            kidx[n] = len(knoten); knoten.append(n)
        return kidx[n]
    teiln = [(r[0], r[1]) for r in db.execute("SELECT pubkey, COALESCE(name, substr(pubkey,1,8)) FROM rx ORDER BY name")]
    pidx = {pk: i for i, (pk, _) in enumerate(teiln)}

    nodes_je, tage_je, rx_je = {}, {}, {}
    for c, pre, name, snr, cnt in db.execute("SELECT cell, prefix, name, best_snr, max_count FROM cell_nodes"):
        nodes_je.setdefault(c, []).append([knoten_id(name or pre), snr, cnt])
    for d, c, cnt, snr in db.execute("SELECT day, cell, count, best_snr FROM daily"):
        tage_je.setdefault(c, []).append([tidx[d], cnt, snr])
    for c, pk in db.execute("SELECT cell, pubkey FROM cell_rx"):
        if pk in pidx: rx_je.setdefault(c, []).append(pidx[pk])

    zellen, ids = [], set()
    for c, lat, lon, ersterT, letzterT, best, mx, sig in db.execute(
            "SELECT cell, lat, lon, first_seen, last_seen, best_snr, max_count, has_sig FROM cells"):
        ids.add(c)
        zellen.append([round(lat, 5), round(lon, 5), best, mx, ersterT, letzterT,
                       nodes_je.get(c, []), tage_je.get(c, []), rx_je.get(c, []), sig])
    luecken = [[round(a, 5), round(b, 5), s, e, l] for c, a, b, e, l, s in db.execute(
        "SELECT cell, lat, lon, first_seen, last_seen, samples FROM gaps") if c not in ids]
    rauschen = [[round(a, 5), round(b, 5), m, q, n, cnt, l] for a, b, m, q, n, cnt, l in db.execute(
        "SELECT lat, lon, median, quietest, noisiest, count, last_seen FROM noise")]
    letzter = db.execute("SELECT ts, ok, note FROM runs ORDER BY rowid DESC LIMIT 1").fetchone()
    backfill = db.execute("SELECT v FROM meta WHERE k='backfill_day'").fetchone()
    meta = {"erzeugt": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "letzter_lauf": letzter[0] if letzter else None, "letzter_lauf_ok": bool(letzter and letzter[1]),
            "laeufe": db.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
            "zellen": len(zellen), "luecken": len(luecken), "rauschen": len(rauschen),
            "vor_start_tag": backfill[0] if backfill else None,
            "archiv_seit": tage[0] if tage else None}
    _schreiben(os.path.join(ziel, "cells.json"), {"tage": tage, "knoten": knoten, "teilnehmer": [n for _, n in teiln], "zellen": zellen})
    _schreiben(os.path.join(ziel, "gaps.json"), luecken)
    _schreiben(os.path.join(ziel, "noise.json"), rauschen)
    _schreiben(os.path.join(ziel, "meta.json"), meta)
    return meta
