# rx-archiv

Dauerhaftes Archiv und freier Viewer für die **CoreDrive-Empfangskarte** von CarinthiaMesh
(`map.carinthiamesh.com`, Seite *Mobile RX coverage*).

Die Originalkarte zeigt höchstens **30 Tage** und hat nur wenige Filter. Dieses Projekt holt
regelmäßig, was die Karte zeigt, und führt es dauerhaft zusammen. Der Viewer zeigt alles, was je
gemessen wurde, mit mehr Filtern, und zeichnet die Zellen auch beim Herauszoomen klein.

## Bestandteile

| | |
|---|---|
| `collector/` | Sammler (Python, nur Standardbibliothek). Läuft stündlich, holt über die öffentliche Karten-Schnittstelle Zellen, Lücken, Rauschen und Teilnehmer und führt sie in `archiv.db` (SQLite) zusammen. Schreibt danach kompakte JSON-Dateien für den Viewer |
| `web/` | Viewer: eine statische Seite (Leaflet), filtert im Browser |
| `k8s/` | Betrieb im k3s-Cluster (Kustomize, ArgoCD) |
| `Dockerfile`, `Dockerfile.web`, `docker-compose.yml` | Betrieb ohne Cluster oder lokal |
| `tests/` | Tests der Zusammenführung (`python3 -m unittest discover -s tests`) |

Der Sammler braucht **keine Zugangsdaten** und **keine Datenbankkopie**. Alle Daten kommen über die öffentliche Schnittstelle der Karte, auch der Erstimport.

## Was archiviert wird

Pro Zelle (rund 150 m, die feinste Stufe der Karte): bester SNR, höchste Anzahl Empfänge, erster und letzter Tag,
gehörte Knoten mit eigenem Bestwert, Tage mit Aktivität, Teilnehmer, die dort gemessen haben. Dazu die
schraffierten Zellen (*befahren, nichts gehört*) und das Grundrauschen.

**Täglich** (alle 20 Stunden) zusätzlich das volle 30-Tage-Fenster und die Teilnehmer, **stündlich** die letzten 24 Stunden.
Beim allerersten Lauf wird das 30-Tage-Fenster als Startbestand übernommen. Was dort nicht in den letzten 24 Stunden lag,
gilt als „bis Archivstart".

## Erstimport

Beim ersten Start ist das Archiv leer. Der Sammler erkennt das und holt automatisch das ganze 30-Tage-Fenster der Karte
(Zellen, Lücken, Rauschen, Teilnehmer). Das dauert ein bis zwei Minuten und braucht nichts außer Internet. Von Hand erzwingen:

```bash
docker compose run --rm collector python -m collector.run --erstimport
```

`collector.importieren` ist ein Zusatzwerkzeug und **kein Datenweg**: Es führt ein zweites Archiv zusammen (Umzug auf einen anderen Rechner)
oder liest gespeicherte Antworten der Schnittstelle ein.

```bash
docker compose run --rm -v "$PWD":/import:ro collector python -m collector.importieren --db /import/archiv.db
```

## Filter im Viewer

Ebene (Signal, Rauschen), Lücken, Zeitraum, Signalstufe, Mindestzahl Repeater und Empfänge, gehörter Knoten, Teilnehmer.
Die Ansicht steckt im Link und lässt sich teilen.

## Grenzen (wichtig beim Lesen)

- **Kein Verlauf vor dem ersten Lauf.** Die Karte reicht höchstens 30 Tage zurück. Was vor dem Start schon herausgefallen war, ist nicht mehr zu holen.
- **Zellen, keine Einzelmessungen.** Die Schnittstelle liefert zusammengefasste Zellen. Es gibt keinen genauen Zeitpunkt je Messung. Die Zeitachse besteht aus **Tagesscheiben**: Eine Zelle zählt an dem Tag, an dem sie in den letzten 24 Stunden aktiv war.
- **Anzahlen sind Höchstwerte,** keine Summen. Die Karte zählt im Fenster, das Archiv behält das Maximum.
- **Knoten- und Teilnehmerfilter ignorieren den Zeitraum.** Die Zuordnung ist ein Bestand über die gesamte Zeit.
- **Farbe ist der beste je gehörte Wert,** nicht der typische. Schraffur heißt *befahren, nichts gehört*, nicht *kein Empfang*.
- Wird eine Zelle später doch gehört, ersetzt der Treffer die Lücke.
- Ändert CoreScope seine Schnittstelle, bricht der Sammler. Der Viewer warnt, wenn die Daten älter als drei Stunden sind oder der letzte Lauf einen Fehler meldete.

## Betrieb im k3s-Cluster (so läuft es bei uns)

Ein Pod mit zwei Containern: Der **Sammler** (`meshcore-rx-archiv-collector`) schreibt, **nginx** (`meshcore-rx-archiv-web`, auf Basis von `nginx-unprivileged`) liefert aus.
Beide Images baut `.github/workflows/build.yml` bei jedem Merge auf `main` (Tag `sha-<kurz>`) nach `ghcr.io/achildrenmile/`, trägt die Digests in `k8s/deployment.yaml` ein und committet das mit `[skip ci]` zurück; ArgoCD rollt dann aus. Ein `v*`-Tag baut nur die Images. Pull per `ghcr-pull-secret` (Pakete sind privat).
Das Archiv liegt auf einem PVC (1 Gi). Es gibt genau ein Replikat mit `Recreate`, weil SQLite nur einen Schreiber verträgt.

| Datei in `k8s/` | |
|---|---|
| `kustomization.yaml` | Einstieg: Namespace `rx-archiv`, PVC, Deployment, Service `web:80` |
| `deployment.yaml` | beide Container, Images per Tag und Digest gepinnt |
| `tunnel/` | optional: cloudflared, falls im Cluster noch keiner läuft (Token aus einem Secret, nicht im Repo) |
| `argocd/application.yaml` | ArgoCD-Application, von Hand anzuwenden |

**Neue Version:** einfach nach `main` mergen. Der Workflow baut, setzt die Digests und ArgoCD rollt aus (kurze Downtime, `Recreate`).

Den dunklen Kartenstil bedient nginx über den Key aus dem Secret `carto-key` (Umgebungsvariable `CARTO_KEY`).

**Ausrollen:**

1. Das Repo ist öffentlich, ArgoCD braucht keine Zugangsdaten.
2. `kubectl apply -f k8s/argocd/application.yaml`
3. Der erste Start holt den Erstimport selbst (ein bis zwei Minuten). Prüfen:
   `kubectl -n rx-archiv logs deploy/rx-archiv -c collector`

**Erreichbar unter `meshcoredrive.kaernten-funkt.at`:** Die Adresse zeigt über einen Cloudflare-Tunnel auf `http://web.rx-archiv.svc.cluster.local:80`.
Läuft im Cluster schon ein cloudflared, dort nur die Route ergänzen. Sonst `k8s/tunnel/` verwenden:

```bash
kubectl -n rx-archiv create secret generic tunnel-token --from-literal=token=<TOKEN>
kubectl apply -k k8s/tunnel
```

Den Tunnel samt *Public Hostname* legt man im Cloudflare-Dashboard der Zone `kaernten-funkt.at` an (*Zero Trust → Networks → Tunnels*).

**Sicherung:** `archiv.db` auf dem PVC ist das Einzige, was sich nicht neu holen lässt. Bei uns sichert Longhorn das Volume täglich um 02:30 Uhr (Label `recurring-job-group.longhorn.io/stateful-daily=enabled` am PVC, siehe `k8s/pvc.yaml`) auf NFS und behält sieben Backups. Bei Velero müsste das Pod-Template stattdessen die Annotation `backup.velero.io/backup-volumes: data` tragen. **Eine Wiederherstellung einmal probieren.**

**Überwachung:** Der Sammler hat bewusst keine Probe, damit der Viewer bei einem Ausfall der Karte mit den vorhandenen Daten erreichbar bleibt.
Der Viewer warnt, wenn die Daten älter als drei Stunden sind. Von außen prüfbar über `/data/meta.json` (`letzter_lauf`, `letzter_lauf_ok`) und `/healthz`.

## Betrieb mit Docker Compose (lokal oder ohne Cluster)

```bash
cp .env.example .env            # Port anpassen
docker compose up -d --build    # Sammler und Viewer auf http://<host>:8088
docker compose logs -f collector
```

Optional mit Tunnel: Token in `.env` als `TUNNEL_TOKEN=`, dann `docker compose --profile tunnel up -d`.

## Lokal ausprobieren

```bash
python3 -m collector.run --einmal --voll     # schreibt data/archiv.db und web/data/*.json
cd web && python3 -m http.server 8099        # http://localhost:8099
python3 -m unittest discover -s tests
```

## Lizenz und Herkunft

Die Daten stammen von `map.carinthiamesh.com` (CoreScope, GPL-3.0). **Der Viewer ist eigener Code** und kopiert nichts aus dem
Frontend von CoreScope. Genutzt wird nur die Form der öffentlichen Schnittstellen.
