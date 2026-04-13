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

`POST /jobs` va `POST /client/jobs` se tra `409` neu profile session chua san sang cho automation.

## Client Jobs with API key

Header: `x-api-key: <plain_key>`

- `POST /client/jobs`

```json
{
  "profile_id": "uuid",
  "target": "image",
  "prompt": "a cinematic robot in Bangkok",
  "negative_prompt": "",
  "count": 1,
  "provider_payload": {}
}
```

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
