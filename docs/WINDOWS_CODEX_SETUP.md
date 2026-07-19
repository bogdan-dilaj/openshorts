# Windows Setup fuer eine neue Codex-Session

Ziel: OpenShorts auf Windows funktional identisch starten und nur Einstellungen importieren. Bestehende Projekte, Jobs, Videos und Renderdaten werden nicht migriert.

## Auftrag an Codex auf Windows

Codex soll diese Schritte selbst ausfuehren, Ausgaben pruefen und erst aufhoeren, wenn Backend und Frontend erreichbar sind. API-Schluessel oder den Inhalt der Exportdatei niemals in Terminalausgaben, Logs, Commits oder Chat-Antworten schreiben.

## Voraussetzungen

- Windows 11 oder aktuelles Windows 10
- Git
- Docker Desktop mit WSL-2-Backend und Linux-Containern
- Optional fuer GPU: aktueller NVIDIA-Treiber mit WSL-/Docker-Unterstuetzung
- Die exportierte Datei `openshorts-settings-YYYY-MM-DD.json`

Wenn Git oder Docker Desktop fehlt, soll Codex die Installation per `winget` vorbereiten. Docker Desktop benoetigt gegebenenfalls einen Neustart und eine interaktive Bestaetigung fuer WSL 2.

Beispiel in PowerShell als Administrator:

```powershell
winget install --id Git.Git -e
winget install --id Docker.DockerDesktop -e
```

Danach Docker Desktop starten und warten, bis `docker info` erfolgreich ist.

## Repository installieren

```powershell
Set-Location $HOME
git clone https://github.com/bogdan-dilaj/openshorts.git
Set-Location openshorts
```

Bei einem bestehenden Clone:

```powershell
Set-Location "$HOME\openshorts"
git pull --ff-only
```

Keine alten `output`, Projekt- oder Mediendateien kopieren.

## Automatischer Start

CPU, funktioniert auf jedem Docker-Desktop-System:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup_windows.ps1
```

NVIDIA-GPU, nur wenn `nvidia-smi` auf Windows funktioniert und Docker Desktop GPU-Zugriff hat:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup_windows.ps1 -Gpu
```

Das Skript:

1. prueft Docker und Docker Compose,
2. erstellt bei Bedarf `.env` aus `.env.example`,
3. erstellt nur frische Runtime-Verzeichnisse,
4. validiert die Compose-Konfiguration,
5. baut und startet Backend und Frontend,
6. wartet auf `http://localhost:8000/openapi.json` und `http://localhost:5175`,
7. oeffnet das Dashboard.

Das Windows-Compose verwendet Bridge-Networking und explizite Ports. Das vermeidet die Linux-Abhaengigkeit von `network_mode: host`.

## Einstellungen auf dem alten Rechner exportieren

1. OpenShorts oeffnen.
2. `Einstellungen -> Geraete-Sync` oeffnen.
3. Optional `YouTube Session mit synchronisieren` aktivieren.
4. `Einstellungen exportieren` klicken.
5. Sicherheitswarnung bestaetigen.
6. Die JSON-Datei sicher auf den Windows-Rechner uebertragen.

Die Datei enthaelt API-Schluessel und das Relay-Passwort im Klartext. Nicht per Git, unverschluesselter Cloud-Freigabe oder oeffentlichem Messenger uebertragen.

## Einstellungen auf Windows importieren

1. `http://localhost:5175` oeffnen.
2. `Einstellungen -> Geraete-Sync` oeffnen.
3. `Einstellungen importieren` klicken.
4. Die exportierte JSON-Datei auswaehlen.
5. Upload-Post-Profil und AI-Provider kurz kontrollieren.
6. Nach erfolgreichem Test die Transferdatei sicher loeschen.

Der Import uebernimmt keine Projekte. Das neue Windows-System bleibt bezueglich Jobs und Medien leer.

## Funktionstest

Codex soll mindestens pruefen:

```powershell
docker compose -f docker-compose.windows.yml ps
Invoke-WebRequest -UseBasicParsing http://localhost:8000/openapi.json
Invoke-WebRequest -UseBasicParsing http://localhost:5175
```

Im Dashboard:

1. API-Schluessel-Felder sind befuellt.
2. Upload-Post-Profil kann geladen werden.
3. Podcast-DM-Relay-URL und Passwort sind vorhanden.
4. Ein kleiner Testjob kann angelegt werden.
5. Bei Podcast-Kampagne erhaelt nur Instagram CTA-Caption und CTA-Erstkommentar.
6. Beim Upload-Post Direkt-Upload kann der Instagram Kommentar-Trigger mit eigenem Ziel-Link aktiviert werden; TikTok/YouTube behalten dabei ihre normalen Texte.

## PHP-Relay

Der PHP-Relay bleibt auf dem bestehenden Webspace. Windows muss ihn nicht lokal hosten. Die importierten Relay-URL-/Passwort-Einstellungen verbinden die neue OpenShorts-Installation wieder mit diesem Dienst.

Wichtig: Nach Code-Aenderungen muss `scripts/uploadpost_podcast_dm_relay.php` separat auf den Webspace hochgeladen werden. Der Git-Push allein aktualisiert ihn nicht.

## Ollama auf Windows

Der Backend-Container laeuft im Bridge-Netz. OpenShorts wandelt `http://127.0.0.1:11434` im Container automatisch zu `host.docker.internal:11434` um, wenn `NETWORK_MODE=bridge` gesetzt ist.

Wenn Ollama nicht erreichbar ist:

```powershell
ollama serve
ollama list
```

Dann Backend-Status/Logs pruefen:

```powershell
docker compose -f docker-compose.windows.yml logs --tail 100 backend
```

## YouTube-Cookies auf Windows

Ein Container kann das native Windows-Browserprofil nicht verlaesslich direkt lesen. Bevorzugt:

1. Cookie-Text ueber die Einstellungsdatei importieren, oder
2. frische Netscape-`cookies.txt` im Dashboard einfuegen und im Backend speichern.

## Stoppen und Aktualisieren

Stoppen ohne Datenvolumes zu loeschen:

```powershell
docker compose -f docker-compose.windows.yml stop
```

Aktualisieren:

```powershell
git pull --ff-only
.\scripts\setup_windows.ps1
```

Keine Befehle wie `docker compose down -v`, `git reset --hard` oder das Loeschen von `output` verwenden, ausser der Benutzer verlangt es ausdruecklich.

## Fehlerdiagnose

```powershell
docker compose -f docker-compose.windows.yml ps
docker compose -f docker-compose.windows.yml logs --tail 150 backend
docker compose -f docker-compose.windows.yml logs --tail 150 frontend
```

Bei GPU-Problemen zuerst CPU starten:

```powershell
docker compose -f docker-compose.windows.yml down
.\scripts\setup_windows.ps1
```
