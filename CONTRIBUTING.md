# Mitmachen

Beiträge sind willkommen: Fehler melden, Texte verbessern, Funktionen vorschlagen oder Code beisteuern.

## Ablauf in Kürze

1. Repo forken (Button "Fork" auf GitHub) und einen Branch anlegen, z. B. `fix/legende-mobil`.
2. Änderung machen, lokal prüfen (siehe unten), committen und pushen.
3. Pull Request gegen `main` öffnen. Kurz beschreiben, was und warum.
4. Der Maintainer prüft den PR. Passt alles, wird gemergt.
5. **Der Merge auf `main` rollt automatisch aus:** Die GitHub Action testet, baut die Images, trägt die neuen Digests in `k8s/deployment.yaml` ein, ArgoCD übernimmt sie im Cluster. Wenige Minuten später ist die Änderung auf https://meshcoredrive.kaernten-funkt.at live. Beim Wechsel gibt es eine kurze Downtime (ein Replikat, SQLite), die Daten bleiben erhalten.

Gemergt wird nur durch den Maintainer. Ein PR von einem Fork löst keinen Build mit Zugriff auf Zugangsdaten aus; gebaut und ausgerollt wird erst nach dem Merge.

## Lokal prüfen

```
python -m unittest discover -s tests     # Tests des Collectors
docker compose up --build                # Viewer und Collector lokal, siehe README
```

Reine Oberflächenänderungen (`web/`) lassen sich im Browser prüfen, indem `web/` über einen lokalen Webserver mit Beispieldaten aus `/data/` ausgeliefert wird.

## Was sich lohnt

- Kleine, in sich geschlossene PRs (eine Sache pro PR).
- Tests für Änderungen am Collector (`tests/`).
- Keine Zugangsdaten, Schlüssel oder personenbezogenen Daten im Code oder in Beispielen.
- Keine neuen externen Dienste im Browser: Karten-Kacheln laufen bewusst über den eigenen Proxy (Datenschutz, OSM-Nutzungsbedingungen).

## Was nicht passiert

- Änderungen nur unter `k8s/`, an `*.md` oder `LICENSE` lösen keinen Build aus (Doku-Fixes sind also risikolos).
- Die Dateien in `k8s/` beschreiben unseren Cluster. Wer das Archiv selbst betreibt, passt sie an oder nutzt Docker Compose.

## Lizenz

Mit einem Beitrag stimmst du zu, dass er unter der MIT-Lizenz (siehe `LICENSE`) veröffentlicht wird.
