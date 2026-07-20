# OpenShorts auf einem neuen Windows-PC

Diese Anleitung richtet einen neuen Windows-PC fuer OpenShorts ein. Nach der einmaligen Installation startet OpenShorts ueber eine Desktop- oder Startmenue-Verknuepfung, ohne sichtbares PowerShell-Fenster.

## Auftrag fuer Codex auf dem neuen PC

Der folgende Text kann in einer neuen Codex-Session verwendet werden:

```text
Bitte richte https://github.com/bogdan-dilaj/openshorts auf diesem Windows-PC vollstaendig ein. Lies zuerst README.md und docs/NEW_PC_SETUP.md. Installiere oder starte bei Bedarf Git, WSL 2 und Docker Desktop, clone das Repository frisch und fuehre scripts/setup_windows.ps1 im NVIDIA-GPU-Modus aus, sofern eine kompatible NVIDIA-GPU vorhanden ist. Pruefe Backend, Frontend, Dashboard-Proxy, nvidia-smi und h264_nvenc. Erzeuge bzw. pruefe Desktop- und Startmenue-Verknuepfung. Uebertrage keine alten Projekte, Jobs, Verlaeufe, Videos oder output-Daten und lege keine Secrets in Git ab. Stoppe erst, wenn http://localhost:5175/#app einsatzbereit ist; die Settings importiere ich danach selbst im Browser.
```

## Was uebertragen wird

Der Git-Clone enthaelt Programmcode, Docker-Konfiguration, Installer und Launcher. Die exportierte OpenShorts-Settings-Datei uebertraegt unter anderem AI-Provider, API-Schluessel, Modelle, Upload-Post-Profile und Darstellungsoptionen.

Nicht in Git enthalten sind:

- `.env` und exportierte `openshorts-settings-*.json`
- Quellvideos, fertige Shorts und Job-Historie unter `output/`
- lokale Modell- und Render-Caches
- YouTube-Cookies, sofern sie nicht ueber den Settings-Export uebertragen werden

Die Settings-Datei enthaelt Geheimnisse im Klartext. Sie darf nicht committed oder unverschluesselt oeffentlich geteilt werden.

## 1. Settings am alten PC exportieren

1. OpenShorts oeffnen.
2. `Einstellungen -> Geraete-Sync` waehlen.
3. Optional `YouTube Session mit synchronisieren` aktivieren.
4. `Einstellungen exportieren` auswaehlen.
5. Die erzeugte `openshorts-settings-YYYY-MM-DD.json` sicher auf den neuen PC uebertragen.

## 2. Voraussetzungen installieren

Empfohlen:

- Windows 11
- mindestens 30 GB freier Speicher fuer Docker-Images und Modelle, zuzueglich Platz fuer Videos
- Git
- Docker Desktop mit WSL-2-Backend und Linux-Containern
- fuer GPU-Betrieb: aktueller NVIDIA-Treiber und eine von Docker Desktop unterstuetzte NVIDIA-GPU

PowerShell als Administrator oeffnen und bei Bedarf installieren:

```powershell
wsl --install
winget install --id Git.Git -e
winget install --id Docker.DockerDesktop -e
```

Windows danach neu starten, Docker Desktop einmal oeffnen und die Einrichtung abschliessen. In Docker Desktop sollte `Start Docker Desktop when you sign in` aktiviert sein. Der OpenShorts-Launcher versucht Docker Desktop bei Bedarf ebenfalls zu starten.

Fuer NVIDIA pruefen:

```powershell
nvidia-smi
```

Es ist kein separates CUDA Toolkit im Windows-System erforderlich. Treiber, WSL 2 und Docker-GPU-Passthrough muessen funktionieren.

## 3. Repository klonen

```powershell
Set-Location $HOME
git clone https://github.com/bogdan-dilaj/openshorts.git
Set-Location openshorts
```

Ein abweichender Zielordner ist erlaubt. Der Installer speichert den tatsaechlichen Repository-Pfad in den erzeugten Verknuepfungen.

## 4. OpenShorts installieren

NVIDIA-GPU, empfohlen fuer Transkription und Rendering:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1 -Gpu
```

CPU-Modus fuer Rechner ohne kompatible NVIDIA-GPU:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
```

Der Installer:

1. erkennt Docker Desktop oder eine vorhandene native Docker-Installation in WSL,
2. startet die Docker-Runtime bei Bedarf,
3. erzeugt eine lokale `.env` aus `.env.example`,
4. validiert, baut und startet Backend und Frontend,
5. wartet auf die Healthchecks,
6. prueft im GPU-Modus `nvidia-smi` und den gewaehlten H.264-Encoder,
7. erstellt `OpenShorts` auf dem Desktop und im Startmenue,
8. oeffnet `http://localhost:5175/#app`.

Der erste Build und der erste Transkriptionsjob koennen laenger dauern, weil Docker-Images, Whisper-Modelle und weitere Caches heruntergeladen werden.

## 5. Settings importieren

1. `http://localhost:5175/#app` oeffnen.
2. `Einstellungen -> Geraete-Sync` waehlen.
3. `Einstellungen importieren` auswaehlen.
4. Die exportierte JSON-Datei laden.
5. AI-Provider und Modell kontrollieren. Fuer MiniMax muss MiniMax als Provider aktiv sein; ein Gemini-Key ist dann nicht erforderlich.
6. Upload-Post-Profil, Relay-Einstellungen und optionale YouTube-Session pruefen.
7. Nach erfolgreichem Test die Transferdatei sicher archivieren oder loeschen.

## 6. GPU-Funktion pruefen

Bei erfolgreichem `-Gpu`-Setup zeigt der Installer die erkannte GPU und den Video-Encoder. Erwartet werden eine NVIDIA-GPU und:

```text
Video encoder: h264_nvenc
```

Manuelle Pruefung bei Docker Desktop:

```powershell
docker exec openshorts-backend nvidia-smi
docker exec openshorts-backend python -c "import video_encoding; print(video_encoding.selected_h264_encoder())"
```

Ein Render nutzt trotzdem nicht permanent 100 Prozent GPU. Szenenanalyse, Gesichtserkennung und Teile des Frame-Compositings laufen auf der CPU; H.264-Encoding und Whisper-CUDA laufen auf der NVIDIA-GPU.

## 7. Taeglicher Start ohne PowerShell

Nach der Installation genuegt:

1. `OpenShorts` auf dem Desktop oder im Startmenue anklicken.
2. Der unsichtbare Launcher startet Docker bei Bedarf und danach die Container.
3. Sobald das Dashboard bereit ist, oeffnet sich der Browser automatisch.

Das Launcher-Protokoll liegt unter:

```text
%LOCALAPPDATA%\OpenShorts\launcher.log
```

Die Container verwenden `restart: unless-stopped`. Nach einem Neustart kann Docker sie selbst wiederherstellen; die Verknuepfung ist der verlaessliche manuelle Startweg.

## 8. Aktualisieren

Im Repository-Ordner:

```powershell
git pull --ff-only
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1 -Gpu
```

Auf einem CPU-Rechner `-Gpu` weglassen. Das erneute Setup baut geaenderte Images und aktualisiert beide Verknuepfungen. Settings, Jobs und Videos unter `output/` bleiben erhalten.

## 9. Bewusst keine Projekte oder Jobs uebertragen

Fuer diesen Umzug wird ausschliesslich ein frischer Git-Clone installiert und danach die Settings-Datei im Browser importiert. Den Ordner `output/` vom alten PC nicht kopieren. Dadurch startet der neue PC ohne Projekte, Jobs, Verlauf, Videos oder Renderdateien.

Neue Quellvideos werden spaeter normal ueber OpenShorts ausgewaehlt oder hochgeladen.

## 10. Fehlerdiagnose

Status und Logs mit Docker Desktop:

```powershell
docker compose -f docker-compose.windows.yml -f docker-compose.windows.gpu.yml ps
docker compose -f docker-compose.windows.yml -f docker-compose.windows.gpu.yml logs --tail 150 backend
docker compose -f docker-compose.windows.yml -f docker-compose.windows.gpu.yml logs --tail 150 frontend
```

Healthchecks:

```powershell
Invoke-WebRequest -UseBasicParsing http://localhost:8000/openapi.json
Invoke-WebRequest -UseBasicParsing http://localhost:5175/
Invoke-WebRequest -UseBasicParsing http://localhost:5175/api/jobs/history?limit=1
```

Wenn GPU-Passthrough nicht funktioniert, OpenShorts voruebergehend im CPU-Modus neu einrichten:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
```

Keine Befehle wie `docker compose down -v`, `git reset --hard` oder das Loeschen von `output/` verwenden, wenn vorhandene Daten erhalten bleiben sollen.
