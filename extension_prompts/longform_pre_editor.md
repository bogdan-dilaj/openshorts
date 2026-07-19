Du bist ein Senior Video Automation Engineer, Python-Architekt, Audio-Processing-Spezialist und NLE-Workflow-Entwickler.

Deine Aufgabe ist es, ein lokal laufendes, skriptbasiertes Automatisierungssystem für den Rohschnitt eines Video-Podcasts zu entwerfen und den vollständigen produktionsreifen Code dafür zu erzeugen.

WICHTIG:
- Arbeite nicht wie ein Ideengeber, sondern wie ein umsetzender Lead Engineer.
- Liefere keine vagen Konzepte, sondern ein reales, ausführbares Projekt.
- Schreibe deterministischen, konservativen, wartbaren Code.
- Bevorzuge robuste Heuristiken + Review-Marker statt aggressiver Blackbox-Automation.
- Das System muss non-destruktiv arbeiten.
- Das Ergebnis muss in DaVinci Resolve FREE importierbar und editierbar sein. Resolve Studio darf NICHT vorausgesetzt werden.
- Ziel ist ein editierbarer Rough Cut, kein finales Renderfile.
- Ich will hinterher in Resolve alle automatischen Entscheidungen manuell korrigieren können.

========================
PROJEKTZIEL
========================

Baue ein lokales Podcast-Editing-System mit diesen optionen:

1) eine iPhone-Kameraaufnahme

2) zwei iPhone-Kameraaufnahmen (interview):
- Kamera 1: Host
- Kamera 2: Gast

Rahmenbedingungen:
- Bei Interviews: Eine Kamera hat deutlich besseres Audio, z. B. Wireless-Mikrofon. das will ich per toggle flag markieren können welche kamera es ist. das ist das Hauptaudio. Die andere Kamera hat nur normales iPhone-Mikro und dient primär als Backup / Sync / sekundäres Analyse-Signal.
- Es kann pro Kamera mehrere Dateien geben, weil die Aufnahme wegen Speicherplatz unterbrochen wurde.
- Das System soll aus diesen Rohdateien eine editierbare Timeline erzeugen, die in DaVinci Resolve FREE importiert werden kann.
- Der finale Export soll primär FCPXML sein.
- Optional darf zusätzlich ein neutrales decisions.json, markers.csv und Debug-Artefakte erzeugt werden.
- Optional darf später auch CapCut-kompatibler Export vorbereitet werden, aber Resolve ist Priorität.

Hardware / Ausführungsumgebung:
- Laptop mit NVIDIA RTX 4090 16 GB VRAM
- 32 GB RAM
- i9 CPU
- Lokale KI erlaubt, inklusive Ollama
- Bevorzugt Python + Bash + FFmpeg
- GUI erwünscht
- Alles möglichst lokal und skriptbasiert, optional soll für KI spachmodelle ein Deepseek, Minimax.io, openai, gemini, cloude api token angegeben werden können. default:ollama lokal mit auswählbarem model

========================
FUNKTIONSANFORDERUNGEN
========================

Das System soll folgende Aufgaben automatisieren:

1. Ingest / Vorbereitung
- Mehrere Dateien pro Kamera erkennen (manuell sortierbar per drag and drop)
- Logisch in einen kontinuierlichen Zeitstrahl pro Kamera überführen
- Optional physisches Concatenation/Transcoding
- iPhone-Material vor Analyse in CFR überführen, um VFR-/Drift-Probleme zu minimieren
- Audio extrahieren
- Optional Proxies erzeugen
- Projektstruktur automatisch anlegen

2. Synchronisation
- Clips pro Kamera robust per Audio synchronisieren
- Auch dann, wenn nur eine Spur gutes Audio hat
- Offsets pro Datei bestimmen
- Globalen Timeline-Raum aufbauen
- Sync-Ergebnisse als JSON speichern

3. Transkription
- Lokale Speech-to-Text-Analyse mit Wort-Timestamps
- Nutze das bereits implementierte bzw installierte Whisper (die video sprache ist default deutsch)
- Architektur so bauen, dass Modell austauschbar bleibt und erweiterbar
- NVIDIA/CUDA-Beschleunigung nutzen wo es sinn macht
- Getrennte Analyse pro relevanter Audiospur

4. Sprachaktivität / Sprecherlogik
- VAD-basierte Erkennung von Sprachsegmenten
- Pegel/RMS nur als Hilfssignal, NICHT als alleinige Entscheidungsbasis
- Aktiven Sprecher bestimmen
- Backchannels erkennen und NICHT unnötig auf diese schneiden:
  Beispiele: „mhm“, „ja“, „genau“, kurzes Lachen, kurze Einwürfe
- Mindest-Shotlänge und Hysterese verwenden, damit der Schnitt nicht nervös wird
- Typische Regel:
  - min_shot_length konfigurierbar
  - switch_hold_ms konfigurierbar
  - Backchannel-Minimaldauer / Wortanzahl konfigurierbar

5. Automatische Schnittvorbereitung
- Pausen erkennen
- Sprachpausen, Denkpausen und Füllwörter erkennen
- Konfigurierbar schneiden:
  - wie aggressiv Stille gekürzt wird
  - wie aggressiv „äh“, „ähm“, „hm“ etc. entfernt werden
  - wie Retakes behandelt werden
- Niemals blind alles hart löschen
- Unsichere Fälle als Review-Marker markieren statt irreversibel zu schneiden

6. Retake- / Falschstart-Erkennung
- Retakes, Wiederholungen, abgebrochene Sätze, Neustarts erkennen
- Ollama darf genutzt werden, aber nur als Klassifikator / Hilfsschicht
- Das LLM darf NICHT die Timeline frei erfinden
- LLM soll nur Kandidaten bewerten wie:
  - is_retake
  - is_false_start
  - keep_a / keep_b / review
  - confidence
  - short_reason
- Die finale Schnittentscheidung bleibt regelbasiert und deterministisch

7. Kamera-Entscheidungslogik
- Standardregel: Zeige den Sprecher, der gerade spricht
- Aber das System muss editierbar und konservativ sein
- Es soll zusätzlich „reaction opportunities“ markieren, bei denen man bewusst auf den Zuhörer/Reaktionsshot gehen könnte
- WICHTIG: Ich will später in Resolve manuell auch dann die andere Person zeigen können, wenn sie gerade nicht spricht
- Darum:
  - keine destruktive Verarbeitung
  - lieber saubere, editierbare Timeline
  - optional beide Kameraspuren logisch mitführen
  - Markierungen für interessante Reaktionsmomente erzeugen

8. Export
- Primärer Export: Resolve-kompatible FCPXML
- Zusätzlich:
  - decisions.json
  - markers.csv oder ähnliches
  - Debug-Ordner mit Analyseartefakten
- Export muss in DaVinci Resolve FREE importierbar sein
- Kein Resolve-Studio-Zwang
- Timeline muss in Resolve vollständig manuell nachbearbeitbar sein:
  - Clips verlängern
  - Clips kürzen
  - Kamera wechseln
  - automatische Entscheidungen überschreiben

9. GUI
- GUI soll Folgendes ermöglichen:
  - Projektordner wählen
  - Videodateien laden und sortieren können. Bei Interview toggle: Host- und Gast Video-Dateien laden
  - mehrere Dateien pro Kamera verwalten
  - Audioquelle priorisieren
  - Presets wählen: konservativ / normal / aggressiv
  - Feineinstellungen konfigurieren:
    - Pause-Cut-Aggressivität
    - Füllwort-Cut-Aggressivität
    - Backchannel-Unterdrückung
    - min_shot_length
    - switch_hold_ms
    - reaction markers an/aus
    - Retake-Erkennung an/aus
    - Ollama-Modell wählen
    - Export-FPS
    - CFR-Transcode an/aus
  - Pipeline starten
  - Fortschritt sehen
  - Logs sehen
  - Analyse-Ergebnisse prüfen
  - Export-Dateien öffnen
  - Fehler ausgabe, ggf mit der möglichkeit an dem punkt zu resumen oder retry ohne komplett neu zu beginnen
- GUI darf schlicht sein, aber funktional und stabil

========================
NICHT-FUNKTIONALE ANFORDERUNGEN
========================

- Saubere Typannotationen
- Logging statt unkontrollierter print-Ausgaben
- Konfigurationsdatei, z. B. YAML oder JSON
- Saubere Fehlerbehandlung
- Reproduzierbare Ergebnisse
- Keine unnötige Cloud-Abhängigkeit
- Lokal-first
- Code muss wartbar und erweiterbar sein
- Erweitere README mit Setup und Nutzung
- Erweitere REST API
- Nutze FFmpeg/ffprobe systematisch
- Nutze CUDA wo sinnvoll, aber baue Fallbacks
- Architektur so aufbauen, dass man später weitere Regeln ergänzen kann


========================
ENTSCHEIDUNGSLOGIK
========================

Die decision_engine ist das Herz des Systems.

Sie soll konservativ arbeiten.

Pflichtregeln:
- Kein nervöser Schnitt
- Mindest-Shotlänge erzwingen
- Switch-Hold/Hysterese verwenden
- Backchannels nicht als vollwertigen Sprecherwechsel behandeln
- Pausen nur oberhalb konfigurierbarer Schwelle kürzen
- Unsichere Retakes markieren statt blind löschen
- Bei Overlap / Übersprechen lieber stabil bleiben als hektisch wechseln
- Reaktionsmomente markieren
- Optional selektive J-Cuts / L-Cuts, aber NICHT global erzwungen
- Standardmäßig harte Schnitte, J/L-Cut nur als optionale, selektive Regel
- Audiocuts smooth, nicht abgewürgt im satzende

Baue Einstellungsprofile:
- conservative
- balanced
- aggressive

Beispielparameter:
- min_shot_length_sec
- speaker_switch_hold_ms
- long_pause_threshold_ms
- pause_trim_target_ms
- filler_word_cut_level
- remove_umms
- backchannel_max_duration_ms
- reaction_marker_enabled
- retake_mode = off / mark / conservative_cut
- jcut_enabled
- lcut_enabled
- review_threshold

========================
TOOL-AUSWAHL
========================

Bevorzugte Tools:
- Python
- FFmpeg / ffprobe
- whisper
- Silero VAD oder ähnlich robuste lokale VAD
- Ollama (optional apikeys für andere lmm wie minimax.io) für semantische Klassifikation
- lxml oder saubere XML-Erzeugung für FCPXML

Nutze nur zusätzliche Libraries, wenn sie einen klaren Vorteil bringen.
Keine unnötige Tool-Inflation.
Kein unkritisches Vertrauen in Drittbibliotheken für Resolve-XML-Kompatibilität.
Wenn nötig, implementiere den FCPXML-Exporter selbst.

========================
WICHTIGE TECHNISCHE PRINZIPIEN
========================

- Die Free-Version von Resolve muss als Zielsystem genügen
- Resolve Studio Features dürfen optional erwähnt werden, aber nicht vorausgesetzt werden
- Exportiere editierbare Timelines, keine final gerenderten Auto-Cuts
- Kein Hardcoding auf nur genau zwei Dateien; mehrere Dateien pro Kamera müssen unterstützt werden
- Schlechte Audiospur primär für Sync verwenden, bessere Spur als Hauptsignal priorisieren
- FCPXML muss sauber genug sein, dass man hinterher in Resolve manuell alles anpassen kann
- Baue konservativ
- Lieber 70 % brauchbarer Rohschnitt mit Review-Markern als 95 % aggressive, fehlerhafte Automatik
- Ziel ist reale Zeitersparnis, nicht Demo-Magie
- kostenlose AI Tools immer erlaubt


========================
CODEQUALITÄT
========================

- Schreibe vollständigen, ausführbaren Code
- Kein Pseudocode
- Kein „TODO“ an kritischen Stellen
- Keine Platzhalter-Architektur ohne Implementierung
- Kommentare nur dort, wo sie technisch helfen
- Nutze klare Funktions- und Klassennamen
- Typannotationen überall, wo sinnvoll
- Solides Logging
- Prüfe Randfälle:
  - fehlende Dateien
  - asynchrone Clip-Längen
  - leere Transkriptsegmente
  - unzureichender Ollama-Output
  - nicht verfügbare CUDA
  - fehlgeschlagener FFmpeg-Call
  - problematische XML-Zeichen
- Schreibe den Code so, dass ich ihn direkt lokal weiterentwickeln kann

========================
AUSGABESTIL
========================

- Antworte strukturiert
- Liefere zuerst den Architekturüberblick
- Dann die Dateistruktur
- Dann den vollständigen Code Datei für Datei
- Dann Setup- und Nutzungsanleitung
- Dann Verbesserungsvorschläge für Version 2
- Erkläre keine Grundlagen langatmig
- Fokussiere auf Umsetzung
- Wenn du Annahmen treffen musst, triff konservative technische Annahmen und benenne sie knapp

========================
ZUSÄTZLICHE FACHLICHE LEITPLANKEN
========================

- Backchanneling darf den Schnitt nicht ruinieren
- Reaktionsshots sind wichtig und müssen im Workflow mitgedacht werden
- Retake-Erkennung ist unsicher; deshalb konservative Klassifikation + Marker
- Pausen- und Füllwort-Schnitt müssen einstellbar sein
- Die GUI ist kein Spielzeug, sondern ein praktisches Bedienwerkzeug für reale Projekte
- Das Projekt soll eher wie ein internes Produktionstool als wie ein Demo-Skript gebaut werden
- Falls du zwischen clever und robust wählen musst: wähle robust
- Falls du zwischen maximaler Automation und Editierbarkeit wählen musst: wähle Editierbarkeit


Erzeuge jetzt das vollständige Projekt. WICHTIG: Bitte liefere nicht nur einen Entwurf, sondern ein echtes MVP mit realem Code. Wenn etwas unsicher ist, implementiere eine konservative funktionierende Basis statt Platzhalter. Erfinde keine nicht existierenden APIs. Bevorzuge lokale Tools, klare Dateiformate und nachvollziehbare Heuristiken. Ich will ein Projekt, das ich direkt lokal starten und iterativ verbessern kann.