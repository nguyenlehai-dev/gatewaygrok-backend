# GatewayGrok Client API Docs

Base URL: `/api`

## Auth

Client endpoints dung header:

```http
x-api-key: <plain_key>
```

Admin endpoints dung:

```http
Authorization: Bearer <admin_token>
```

## End-to-end flow

1. Admin tao profile Grok.
2. Admin login/import cookie cho profile.
3. Admin goi `POST /api/profiles/{profile_id}/session-check` de xac nhan profile san sang.
4. Neu can image-to-video, admin upload anh qua `POST /api/profiles/{profile_id}/assets`.
5. Admin tao client key qua `POST /api/api-keys`.
6. Client goi `POST /api/client/generate` (profile_id la optional).
7. Client poll `GET /api/client/tasks/{task_id}` cho toi khi `succeeded` hoac `failed`.

## Generate task

```http
POST /api/client/generate
Content-Type: application/json
x-api-key: <plain_key>
```

```json
{
  "target": "video",
  "prompt": "A cinematic shot of clouds moving fast over mountains",
  "reference_images": [
    "storage/profiles/PROFILE_ID/assets/ref-mountains.png"
  ],
  "ratio": "16:9",
  "quality": "high",
  "duration": 5,
  "negative_prompt": null,
  "count": 1
}
```

Response:

```json
{
  "task_id": "42d72140-8613-4a53-a1df-1af4db95f4df",
  "status": "pending",
  "poll_url": "/api/client/tasks/42d72140-8613-4a53-a1df-1af4db95f4df"
}
```

## Poll task

```http
GET /api/client/tasks/{task_id}
x-api-key: <plain_key>
```

```json
{
  "task_id": "42d72140-8613-4a53-a1df-1af4db95f4df",
  "status": "running",
  "poll_url": "/api/client/tasks/42d72140-8613-4a53-a1df-1af4db95f4df",
  "profile_id": "PROFILE_ID",
  "target": "video",
  "prompt": "A cinematic shot of clouds moving fast over mountains",
  "negative_prompt": null,
  "count": 1,
  "provider_payload": {
    "reference_images": [
      "storage/profiles/PROFILE_ID/assets/ref-mountains.png"
    ],
    "source_asset_path": "storage/profiles/PROFILE_ID/assets/ref-mountains.png",
    "video_mode": "image_to_video",
    "ratio": "16:9",
    "quality": "high",
    "duration": 5
  },
  "result": null,
  "error": null
}
```

Success example:

```json
{
  "task_id": "42d72140-8613-4a53-a1df-1af4db95f4df",
  "status": "succeeded",
  "poll_url": "/api/client/tasks/42d72140-8613-4a53-a1df-1af4db95f4df",
  "profile_id": "PROFILE_ID",
  "target": "image",
  "prompt": "A cinematic portrait",
  "negative_prompt": null,
  "count": 1,
  "provider_payload": {
    "ratio": "1:1",
    "quality": "high"
  },
  "result": {
    "target": "image",
    "media_urls": [
      "storage/profiles/PROFILE_ID/output/42d72140-8613-4a53-a1df-1af4db95f4df-image-1.jpg"
    ],
    "provider": "grok",
    "page_url": "https://grok.com/imagine"
  },
  "error": null
}
```

## Legacy aliases

Create alias:

```http
POST /api/client/jobs
```

Poll alias:

```http
GET /api/client/jobs/{task_id}
```

## Upload reference image

```http
POST /api/profiles/{profile_id}/assets
Authorization: Bearer <admin_token>
Content-Type: multipart/form-data
```

Field:

- `file`: image file

Response:

```json
{
  "profile_id": "PROFILE_ID",
  "original_filename": "ref.png",
  "stored_path": "storage/profiles/PROFILE_ID/assets/ref.png",
  "content_type": "image/png",
  "size": 248199
}
```

Use `stored_path` in `reference_images`.

## Create API key

```http
POST /api/api-keys
Authorization: Bearer <admin_token>
Content-Type: application/json
```

```json
{
  "name": "Customer Integration Key",
  "rate_limit_per_minute": 60,
  "allowed_categories": ["grok"],
  "notes": "Client integration"
}
```

## Session management

Check session:

```http
POST /api/profiles/{profile_id}/session-check
```

Launch live browser for login:

```http
POST /api/profiles/{profile_id}/launch-login
```

## Mapping rules

- `target=image` and no `reference_images`: image generation.
- `target=image` and `reference_images` present: image flow with `source_asset_path` mapped from the first reference.
- `target=video` and no `reference_images`: `video_mode=text_to_video`.
- `target=video` and `reference_images` present: `video_mode=image_to_video`.
- `ratio`, `quality`, and `duration` are accepted at top level and forwarded into `provider_payload`.
- If `profile_id` is omitted, backend will auto-pick an active profile in pool that is authenticated and allowed by the API key.

## Status values

- `pending`
- `running`
- `succeeded`
- `failed`

## Common errors

- `401`: missing or invalid API key
- `403`: API key cannot use selected profile category
- `404`: profile or task not found
- `409`: profile session is not ready for automation, or no available profile in pool

## Notes

- `media_urls` are returned as relative storage paths.
- Video jobs can remain in `running` longer than image jobs.
- Provider-specific behavior for `ratio`, `quality`, and `duration` depends on the live Grok automation flow.
