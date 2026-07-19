# OpenShorts Codex Handoff

Stand: 2026-07-19

Dieses Dokument ist der technische Kontext fuer eine neue Codex-Session. Keine geheimen Werte sind hier enthalten.

## Kritische Produktregeln

1. Eine aktive Podcast-Link-Kampagne veraendert nur Instagram.
2. Instagram erhaelt die CTA plus Leerzeile plus KI-Text sowohl in der Caption als auch im ersten Kommentar.
3. Alle anderen Plattformen behalten den normalen KI-generierten Text und den normalen ersten Kommentar.
4. Das gilt fuer Einzel-Posts, regulaere Multi-Posts und Reparatur-/Reschedule-Laeufe.
5. Wenn ein Upload-Post-Job ersetzt wird, muss die neue Vendor-Job-ID im PHP-Relay registriert und die alte ersetzt werden.
6. Der automatisch vom eigenen Instagram-Konto gepostete CTA-Kommentar darf nie eine DM oder Public Reply ausloesen.

## Instagram Caption und First Comment

Upload-Post unterstuetzt plattformspezifische Felder. OpenShorts verwendet beim Video-Upload:

- `instagram_title` fuer die Instagram-Caption
- `instagram_first_comment` fuer den ersten Instagram-Kommentar
- `title` und `first_comment` bleiben die Fallbacks fuer andere Plattformen

Relevanter Code in `app.py`:

- `_build_podcast_link_cta`
- `_compose_caption_with_podcast_cta`
- `_compose_first_comment_with_podcast_cta`
- `_build_upload_post_data_payload`
- `_post_social_clip`
- `_build_podcast_caption_patch_candidates`
- `_repair_podcast_campaign_candidate`

Die Delivery-Markierung `payload_schema_version = instagram_title_v2` zeigt an, dass die plattformspezifischen Upload-Felder verwendet wurden. Generische Schedule-PATCHes fuer Multi-Plattform-Jobs sind absichtlich verboten, weil sie sonst YouTube, TikTok und weitere Plattformen ebenfalls veraendern.

Upload-Post-Referenz:

- https://docs.upload-post.com/api/upload-video/

## Podcast-DM-Relay

Datei: `scripts/uploadpost_podcast_dm_relay.php`

Der Relay laeuft separat auf einem PHP-Webspace. OpenShorts registriert Instagram-Posts per `action=register`; ein Cron ruft alle zwei Minuten `action=cron` auf.

Wichtige Eigenschaften:

- Nur Plattformen aus `supported_comment_platforms` werden kontrolliert, derzeit `instagram`.
- Kampagnen und Posts liegen in `podcast_dm_relay_data/registry.json`.
- Verarbeitete Kommentare liegen in `processed.json`.
- Die Queue wird fair nach `last_checked_at` sortiert.
- Noch nicht faellige Posts werden als `not_due_yet` uebersprungen.
- Private Replies sind auf das konfigurierte 7-Tage-Fenster begrenzt.
- Ein 429 stoppt den aktuellen Lauf, damit das Rate-Limit nicht weiter belastet wird.
- Vor einem Public Reply wird eine Reservierung in `processed.json` gespeichert. Das verhindert doppelte sichtbare Antworten nach Timeout/Prozessabbruch.
- `replaces_vendor_job_id` entfernt beim Reschedule den alten Relay-Post und registriert die neue Vendor-ID.

### Schutz gegen den eigenen CTA-Kommentar

Die offizielle Comments-API liefert den Autor als `comment.user.username`. Vor dem Keyword-Match arbeitet der Relay in dieser Reihenfolge:

1. Autor gegen Upload-Post-Profil und optionale Handle-Mappings pruefen.
2. Kommentar gegen den pro Post registrierten exakten `own_first_comment` pruefen.
3. Bei alten Registry-Eintraegen die vollstaendige Kampagnen-CTA im Kommentar erkennen.
4. Ignorierte Kommentare mit `ignored=true` und `ignore_reason` in `processed.json` speichern.

OpenShorts sendet bei jeder regulaeren oder reparierten Relay-Registrierung zusaetzlich:

- `comment_template`
- `own_first_comment`

Wenn der Upload-Post-Profilname nicht dem Instagram-Handle entspricht, kann im PHP konfiguriert werden:

```php
'own_comment_usernames_by_profile' => [
    'anna' => ['real_instagram_handle'],
],
```

Der Textschutz funktioniert auch ohne dieses Mapping.

Offizielle Comments-Antwort und Reply-Endpunkte:

- https://docs.upload-post.com/api/instagram-comments/

## Relay Deployment

Ein Git-Push aktualisiert den PHP-Webspace nicht automatisch. Nach einer Aenderung:

1. `scripts/uploadpost_podcast_dm_relay.php` auf dem Webspace ersetzen.
2. Bestehende `podcast_dm_relay_data/*.json` nicht loeschen.
3. PHP-Syntax auf dem Server pruefen: `php -l uploadpost_podcast_dm_relay.php`.
4. Health mit Relay-Passwort aufrufen.
5. Einen eigenen CTA-Kommentar und einen echten Testkommentar pruefen.

Cron-Beispiel:

```cron
*/2 * * * * /usr/bin/php /absolute/path/uploadpost_podcast_dm_relay.php cron RELAY_PASSWORD >/dev/null 2>&1
```

## Settings-Migration

Im Dashboard unter `Einstellungen -> Geraete-Sync` gibt es jetzt:

- `Einstellungen exportieren`
- `Einstellungen importieren`

Format: `openshorts-settings`, Version `1`.

Enthalten sind API-Schluessel, Provider/Modelle, Upload-Post-Profil und Profilkontexte, Social-/Podcast-Relay-Einstellungen, Overlay-/Edit-Vorgaben, Longform-AI-Vorgaben und optional der eingefuegte YouTube-Cookie-Text.

Nicht enthalten sind Projekte, Jobs, Videos, Renderdaten, Job-UI-Zustand oder globale laufende Schedule-Batches.

Die JSON-Datei enthaelt Geheimnisse im Klartext. Sie darf nicht committed, geteilt oder dauerhaft unsicher gespeichert werden.

## Windows

Siehe `docs/WINDOWS_CODEX_SETUP.md` und `scripts/setup_windows.ps1`.

Windows verwendet `docker-compose.windows.yml` im Bridge-Netz. `dashboard/vite.config.js` liest dafuer `VITE_PROXY_TARGET=http://backend:8000`. Optional aktiviert `docker-compose.windows.gpu.yml` NVIDIA-GPU-Passthrough.

## Verifikation

Relevante lokale Checks:

```bash
python -m compileall -q app.py main.py
php -l scripts/uploadpost_podcast_dm_relay.php
php tests/test_uploadpost_podcast_dm_relay.php
cd dashboard && npm run build
docker compose -f docker-compose.windows.yml config --quiet
```

Wenn PHP lokal fehlt, die beiden PHP-Checks in einem PHP-CLI-Container oder direkt auf dem Webspace ausfuehren.

## Bekannte Betriebsgrenzen

- Ein Zwei-Minuten-Cron garantiert keine Zwei-Minuten-Antwort. Upload-Post/Meta koennen neue Kommentare verzoegert sichtbar machen und API-Aufrufe koennen Rate-Limits erreichen.
- Der Relay pollt; ein echter Meta-Webhook waere fuer niedrigste Latenz die bessere spaetere Architektur.
- YouTube-Browsercookie-Import aus einem Linux-Container kann nicht direkt auf Windows-Browserprofile zugreifen. Der portable Cookie-Text oder ein frischer `cookies.txt`-Export ist verlaesslicher.
- Alte Relay-Registrierungen haben noch kein `own_first_comment`; dafuer existiert der CTA-Fallback.

## Naechste Session

Vor weiteren Aenderungen zuerst:

1. `git status` und den letzten Commit lesen.
2. Dieses Dokument lesen.
3. Die Instagram-only-Invarianten mit einem Payload-Test pruefen.
4. Keine generischen Upload-Post-Titel oder First Comments patchen, wenn ein Job mehrere Plattformen enthaelt.
5. Bei Relay-Aenderungen bestehende Registry-/Processed-Dateien kompatibel halten.
