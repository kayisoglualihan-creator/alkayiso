# API-Referenz

Live-Dokumentation mit allen Schemas: `http://127.0.0.1:8765/docs` (OpenAPI unter `/openapi.json`).

Authentifizierung: `Authorization: Bearer <token>` – lokales Admin-Token (nur 127.0.0.1) oder Geräte-Zugangstoken. 
WebSocket: `GET /ws?token=<token>` liefert Live-Ereignisse (`job.updated`, `approval.created`, `notification`, `task.changed`, `voice.*` …).

## Fehlerformat

```json
{"error": {"code": "token_expired", "message": "Token abgelaufen – bitte erneuern"}}
```

| Code | HTTP | Bedeutung |
|---|---|---|
| auth_required | 401 | kein Token |
| token_invalid / token_expired / token_revoked | 401 | Token ungültig, abgelaufen (→ `/api/auth/refresh`) oder widerrufen |
| device_revoked | 401 | Gerät wurde am PC entfernt → neu koppeln |
| remote_disabled | 401 | Fernzugriff am PC ausgeschaltet |
| refresh_invalid / refresh_expired | 401 | Refresh-Token ungültig (Wiederverwendung erkannt) oder abgelaufen |
| admin_required / admin_local_only | 403 | nur lokal am PC erlaubt |
| tailscale_required | 403 | Kopplung nur über Tailscale Serve |
| pairing_* | 400/404 | Kopplung nicht gefunden, abgelaufen, Code falsch, gesperrt |
| approval_forbidden / approval_closed | 403/409 | fremde Genehmigung, fehlende Bestätigung, bereits entschieden/abgelaufen |
| invalid_input / invalid_setting | 400 | ungültige Eingabe |
| rate_limited | 429 | zu viele Kopplungsversuche |
| stt_unavailable / tts_unavailable / wakeword_unavailable | 501 | optionale Sprachdienste nicht installiert |

## Auftragsstatus

`pending` (Wartend) → `running` (In Bearbeitung) ⇄ `approval_required` (Genehmigung erforderlich) → `succeeded` (Erfolgreich) | `failed` (Fehlgeschlagen) | `cancelled`. 
„PC offline“ ermittelt der Client, wenn `/api/health` nicht erreichbar ist.

## Endpunkte

| Bereich | Methode | Pfad |
|---|---|---|
| approvals | GET | `/api/approvals` |
| approvals | POST | `/api/approvals/{approval_id}` |
| auth | GET | `/api/auth/me` |
| auth | POST | `/api/auth/refresh` |
| automation | DELETE | `/api/automations/{aid}` |
| automation | GET | `/api/automations` |
| automation | PATCH | `/api/automations/{aid}` |
| automation | POST | `/api/automations` |
| automation | POST | `/api/automations/{aid}/run` |
| chat | DELETE | `/api/conversations/{cid}` |
| chat | GET | `/api/conversations` |
| chat | GET | `/api/conversations/{cid}/messages` |
| chat | POST | `/api/chat` |
| chat | POST | `/api/chat/stream` |
| devices | DELETE | `/api/devices/{device_id}` |
| devices | GET | `/api/devices` |
| devices | GET | `/api/network/tailscale` |
| devices | GET | `/api/remote-access` |
| devices | POST | `/api/remote-access` |
| memory | DELETE | `/api/memory` |
| memory | DELETE | `/api/memory/{mid}` |
| memory | GET | `/api/memory` |
| memory | PATCH | `/api/memory/{mid}` |
| memory | POST | `/api/memory` |
| notifications | GET | `/api/notifications` |
| notifications | POST | `/api/notifications/read` |
| pairing | GET | `/api/pairing/pending` |
| pairing | POST | `/api/pairing/claim` |
| pairing | POST | `/api/pairing/poll` |
| pairing | POST | `/api/pairing/start` |
| pairing | POST | `/api/pairing/{pairing_id}/decision` |
| personal | DELETE | `/api/lists/{iid}` |
| personal | GET | `/api/budget` |
| personal | GET | `/api/habits` |
| personal | GET | `/api/lists` |
| personal | PATCH | `/api/lists/{iid}` |
| personal | POST | `/api/budget` |
| personal | POST | `/api/habits/{name}/log` |
| personal | POST | `/api/lists` |
| remote | GET | `/api/jobs` |
| remote | GET | `/api/jobs/{job_id}` |
| remote | POST | `/api/jobs` |
| remote | POST | `/api/jobs/{job_id}/cancel` |
| settings | DELETE | `/api/secrets/{name}` |
| settings | GET | `/api/audit` |
| settings | GET | `/api/settings` |
| settings | GET | `/api/tools` |
| settings | GET | `/api/undo` |
| settings | GET | `/api/usage` |
| settings | PATCH | `/api/settings` |
| settings | POST | `/api/ai/test` |
| settings | POST | `/api/undo/{uid}` |
| settings | PUT | `/api/secrets/{name}` |
| settings | PUT | `/api/tools/{name}/grant` |
| status | GET | `/api/health` |
| status | GET | `/api/status` |
| tasks | DELETE | `/api/reminders/{rid}` |
| tasks | DELETE | `/api/tasks/{tid}` |
| tasks | GET | `/api/briefing` |
| tasks | GET | `/api/reminders` |
| tasks | GET | `/api/tasks` |
| tasks | PATCH | `/api/tasks/{tid}` |
| tasks | POST | `/api/reminders` |
| tasks | POST | `/api/tasks` |
| voice | GET | `/api/voice/status` |
| voice | POST | `/api/voice/speak` |
| voice | POST | `/api/voice/transcribe` |
| voice | POST | `/api/voice/wakeword` |
