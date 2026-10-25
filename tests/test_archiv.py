import json, os, sqlite3, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from collector import archiv, export


def zelle(cid, lat, lon, count, snr, nodes=(("aaaa", "AT-X-Berg", 5.0, 1),), sig=True):
    r = [[lon + dx, lat + dy] for dx, dy in ((0.001, -0.0004), (0.001, 0.0004), (0, 0.0008), (-0.001, 0.0004), (-0.001, -0.0004), (0, -0.0008))]
    return {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [r + [r[0]]]},
            "properties": {"cell": cid, "count": count, "best_snr": snr, "has_sig": sig,
                           "nodes": [{"prefix": p, "name": n, "snr": s, "count": c} for p, n, s, c in nodes]}}


class Zusammenfuehren(unittest.TestCase):
    def setUp(self):
        self.db = archiv.verbinden(":memory:")

    def test_bester_wert_und_hoechste_anzahl_bleiben(self):
        archiv.zellen_zusammenfuehren(self.db, [zelle("14:1:1", 46.6, 14.3, 5, 8.0)], "2026-10-24", "2026-10-24")
        archiv.zellen_zusammenfuehren(self.db, [zelle("14:1:1", 46.6, 14.3, 2, -4.0)], "2026-10-25", "2026-10-25")
        r = self.db.execute("SELECT first_seen, last_seen, best_snr, max_count FROM cells").fetchone()
        self.assertEqual(r, ("2026-10-24", "2026-10-25", 8.0, 5))   # schlechterer Wert und kleinere Anzahl ueberschreiben nicht
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM daily").fetchone()[0], 2)

    def test_zelle_bleibt_nach_dem_fenster(self):
        archiv.zellen_zusammenfuehren(self.db, [zelle("14:1:1", 46.6, 14.3, 5, 8.0)], "2026-10-24")
        archiv.zellen_zusammenfuehren(self.db, [], "2026-12-01")      # Karte zeigt sie nicht mehr
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM cells").fetchone()[0], 1)

    def test_zelle_ohne_snr_bekommt_keinen_wert(self):
        archiv.zellen_zusammenfuehren(self.db, [zelle("14:2:2", 46.6, 14.3, 1, 0.0, sig=False)], "2026-10-24")
        self.assertIsNone(self.db.execute("SELECT best_snr FROM cells").fetchone()[0])

    def test_tagesabfrage_zweimal_am_selben_tag_zaehlt_nicht_doppelt(self):
        for _ in range(2):
            archiv.zellen_zusammenfuehren(self.db, [zelle("14:1:1", 46.6, 14.3, 3, 1.0)], "2026-10-24", "2026-10-24")
        self.assertEqual(self.db.execute("SELECT count FROM daily").fetchone()[0], 3)

    def test_mitte(self):
        lat, lon = archiv.mitte(zelle("x", 46.6, 14.3, 1, 1)["geometry"]["coordinates"][0])
        self.assertAlmostEqual(lat, 46.6, 4); self.assertAlmostEqual(lon, 14.3, 4)


class Ausgabe(unittest.TestCase):
    def test_export_nimmt_luecken_aus_wenn_zelle_existiert(self):
        db = archiv.verbinden(":memory:")
        archiv.zellen_zusammenfuehren(db, [zelle("14:1:1", 46.6, 14.3, 1, 5.0)], "2026-10-24", "2026-10-24")
        g = zelle("14:1:1", 46.6, 14.3, 0, 0); g["properties"] = {"cell": "14:1:1", "samples": 2}
        h = zelle("14:9:9", 46.7, 14.4, 0, 0); h["properties"] = {"cell": "14:9:9", "samples": 1}
        archiv.luecken_zusammenfuehren(db, [g, h], "2026-10-24")
        with tempfile.TemporaryDirectory() as d:
            meta = export.exportieren(db, d)
            luecken = json.load(open(os.path.join(d, "gaps.json")))
            zellen = json.load(open(os.path.join(d, "cells.json")))
        self.assertEqual(len(luecken), 1)                      # nur die ohne Treffer
        self.assertEqual(meta["zellen"], 1)
        self.assertEqual(zellen["knoten"], ["AT-X-Berg"])

    def test_lauf_meldet_fehler_wenn_tagesabfrage_scheitert(self):
        db = archiv.verbinden(":memory:")
        orig = archiv.holen
        archiv.holen = lambda *a, **k: (_ for _ in ()).throw(OSError("keine Verbindung"))
        try:
            ok, fehler = archiv.lauf(db, "http://x", "0,0,1,1", voll=False)
        finally:
            archiv.holen = orig
        self.assertEqual(ok, 0); self.assertTrue(any(f.startswith("tag:") for f in fehler))


class Import(unittest.TestCase):
    def test_db_zusammenfuehren(self):
        from collector import importieren
        with tempfile.TemporaryDirectory() as d:
            quelle = archiv.verbinden(os.path.join(d, "alt.db"))
            archiv.zellen_zusammenfuehren(quelle, [zelle("14:1:1", 46.6, 14.3, 9, -3.0), zelle("14:5:5", 46.7, 14.4, 1, 2.0)], "2026-10-10", "2026-10-10")
            quelle.commit(); quelle.close()
            ziel = archiv.verbinden(":memory:")
            archiv.zellen_zusammenfuehren(ziel, [zelle("14:1:1", 46.6, 14.3, 2, 7.0)], "2026-10-24", "2026-10-24")
            n = importieren.aus_db(ziel, os.path.join(d, "alt.db"))
            self.assertEqual(n["cells"], 2)
            r = ziel.execute("SELECT first_seen,last_seen,best_snr,max_count FROM cells WHERE cell='14:1:1'").fetchone()
            self.assertEqual(r, ("2026-10-10", "2026-10-24", 7.0, 9))     # frueher, spaeter, besser, hoeher
            self.assertEqual(ziel.execute("SELECT COUNT(*) FROM cells").fetchone()[0], 2)
            self.assertEqual(ziel.execute("SELECT COUNT(*) FROM daily").fetchone()[0], 3)
            importieren.aus_db(ziel, os.path.join(d, "alt.db"))            # zweiter Import aendert nichts
            self.assertEqual(ziel.execute("SELECT COUNT(*) FROM cells").fetchone()[0], 2)

    def test_db_null_snr_ueberschreibt_nicht(self):
        from collector import importieren
        with tempfile.TemporaryDirectory() as d:
            q = archiv.verbinden(os.path.join(d, "a.db"))
            archiv.zellen_zusammenfuehren(q, [zelle("14:3:3", 46.6, 14.3, 1, 0.0, sig=False)], "2026-10-10"); q.commit(); q.close()
            z = archiv.verbinden(":memory:")
            archiv.zellen_zusammenfuehren(z, [zelle("14:3:3", 46.6, 14.3, 1, 4.5)], "2026-10-24")
            importieren.aus_db(z, os.path.join(d, "a.db"))
            self.assertEqual(z.execute("SELECT best_snr FROM cells").fetchone()[0], 4.5)

    def test_geojson_tagesscheibe(self):
        from collector import importieren
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "r.json")
            json.dump({"features": [zelle("14:1:1", 46.6, 14.3, 4, 3.0)], "gaps": []}, open(p, "w"))
            db = archiv.verbinden(":memory:")
            importieren.aus_geojson(db, p, "2026-10-20", True)
            self.assertEqual(db.execute("SELECT day FROM daily").fetchone()[0], "2026-10-20")
            importieren.aus_geojson(db, p, "2026-10-21", False)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM daily").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
