# Frontend Contract

Base URL: `/api`

## Auth

- `GET /auth/bootstrap`
- `POST /auth/login`

```json
{
  "username": "admin",
  "password": "change-me"
}
```

## Health

- `GET /health`
- `GET /meta`
- `GET /overview`

Tat ca endpoints ben duoi, tru `/health`, `/auth/*`, `/client/*`, deu can:

`Authorization: Bearer <admin_token>`

## Profiles

- `GET /profiles`
- `POST /profiles`
- `GET /profiles/{profile_id}`
- `PUT /profiles/{profile_id}`
- `DELETE /profiles/{profile_id}`
- `POST /profiles/{profile_id}/cookies` with multipart `file`
- `POST /profiles/{profile_id}/session-check`

### Profile payload

```json
{
  "name": "grok-main",
  "category": "grok",
  "description": "Primary Grok profile",
  "proxy_id": null,
  "tags": ["image", "vip"],
  "concurrency_limit": 1,
  "antidetect": {
    "user_agent": "Mozilla/5.0 ...",
    "locale": "en-US",
    "timezone_id": "America/New_York",
    "viewport_width": 1440,
    "viewport_height": 900,
    "platform": "Win32",
    "hardware_concurrency": 8
  }
}
```

## Proxies

- `GET /proxies`
- `POST /proxies`
- `PUT /proxies/{proxy_id}`
- `DELETE /proxies/{proxy_id}`

## API Keys

- `GET /api-keys`
- `POST /api-keys`
- `PUT /api-keys/{api_key_id}`

## Settings

- `GET /settings`
- `PUT /settings`

```json
{
  "automation": {
    "headless": true,
    "concurrency": 2,
    "timeout_ms": 120000
  }
}
```

## Admin Jobs

- `GET /jobs`
- `GET /jobs/{job_id}`
- `POST /jobs`
- `POST /jobs/{job_id}/retry`

`POST /jobs` va `POST /client/jobs` se tra `409` neu profile session chua san sang cho automation (hoac khong co profile nao san sang trong pool).

## Client Jobs with API key

Header: `x-api-key: <plain_key>`

- `POST /client/generate`
- `GET /client/tasks/{task_id}`
- `GET /client/tasks/{task_id}/status` (lite)
- `GET /client/jobs/{task_id}` (legacy poll alias)
- `GET /client/jobs/{task_id}/status` (legacy lite alias)
- `POST /client/jobs` (legacy create alias)

```json
{
  "profile_id": "uuid (optional)",
  "target": "video",
  "prompt": "a cinematic robot in Bangkok",
  "reference_images": [
    "https://images.example.com/ref.png"
  ],
  "ratio": "16:9",
  "quality": "high",
  "duration": 5,
  "negative_prompt": "",
  "count": 1,
  "provider_payload": {}
}
```

### Mapping rules

- `target=image` and no `reference_images`: image generation flow.
- `target=image` and `reference_images` present: image flow with `source_asset_path` mapped from the first reference.
- `target=video` and no `reference_images`: `video_mode=text_to_video`.
- `target=video` and `reference_images` present: `video_mode=image_to_video`.
- `ratio`, `quality`, and `duration` are accepted at top level and forwarded into `provider_payload`.
- `profile_id` is optional. If omitted, backend auto-selects an active profile that is authenticated and allowed by the API key.
- `reference_images` can be storage paths or `http/https` URLs (backend will download URLs into profile assets).

### Generate response (compact)

```json
{
  "task_id": "42d72140-8613-4a53-a1df-1af4db95f4df",
  "status": "pending",
  "success": false,
  "message": "pending",
  "url": null
}
```

### Poll response (full)

```json
{
  "id": "42d72140-8613-4a53-a1df-1af4db95f4df",
  "status": "running",
  "profile_id": "uuid",
  "target": "video",
  "result_payload": {
    "media_urls": [
      "https://testflowgrok.plxeditor.com/storage/profiles/uuid/output/42d72140-8613-4a53-a1df-1af4db95f4df-video-1.mp4"
    ]
  },
  "error_message": null
}
```

### Lite status response (recommended)

```json
{
  "task_id": "42d72140-8613-4a53-a1df-1af4db95f4df",
  "status": "running",
  "success": false,
  "message": "running",
  "url": null
}
```

### Status and errors

- `pending`: task has been accepted and queued.
- `running`: worker is currently automating the live Grok session.
- `succeeded`: `result_payload.media_urls` is available.
- `failed`: task stopped and `error_message` contains the reason.

Common error cases:

- `401`: missing or invalid `x-api-key`
- `403`: API key is not allowed to use the selected profile category
- `404`: profile or task not found
- `409`: profile session is not ready for automation, or no available profile in pool

## FE pages cần có

1. Profile management
2. Proxy management
3. API key management
4. Gateway settings
5. Job queue monitor
6. Overview dashboard từ `/overview`

## Meta response

FE nên gọi `GET /meta` lúc boot để lấy:

- category list
- job target list
- job status list
- capability của từng provider

Dreamina sẽ hiện trong category list nhưng `notes` sẽ báo chưa triển khai automation.
