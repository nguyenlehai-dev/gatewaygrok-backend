# Test Staging Setup

## Muc tieu

Dung mot moi truong `test/staging` rieng cho `gatewaygrok-staging` ma:

- Khong dung chung DB voi prod
- Khong dung chung storage/profiles voi prod
- Khong can sua `.env` hien tai dang duoc khach su dung

## File moi da duoc tao

- `.env.test.example`
- `docker-compose.test.yml`
- `scripts/start_api_env.sh`
- `scripts/deploy-compose-test.sh`
- `scripts/launch-test-profile-login.sh`
- `scripts/stop-test-profile-login.sh`
- `scripts/import-test-profile-cookie.sh`
- `scripts/check-test-profiles.sh`
- `scripts/verify-test-client-key.sh`
- `scripts/create-test-client-job.sh`
- `docs/TEST_PROFILE_MAP.md`

## Cach dung

1. Tao file env test:

```bash
cp .env.test.example .env.test
```

2. Chinh lai gia tri trong `.env.test` neu can:

- `GATEWAY_DATABASE_URL`
- `GATEWAY_STORAGE_ROOT`
- `GATEWAY_PROFILES_ROOT`
- `APP_PORT`
- `APP_CONTAINER_NAME`
- `COMPOSE_PROJECT_NAME`
- `GATEWAY_ADMIN_USERNAME`
- `GATEWAY_ADMIN_PASSWORD`
- `GATEWAY_ADMIN_TOKEN_SECRET`

3. Dung moi truong test:

```bash
bash scripts/deploy-compose-test.sh
```

## Mac dinh test environment

- DB: `sqlite:///./storage-test/gatewaygrok_test.db`
- Storage root: `storage-test`
- Profiles root: `storage-test/profiles`
- API port: `18084`
- Container name: `gatewaygrok-api-test`
- Compose project: `gatewaygrok-test-be`

## Kiem tra nhanh

Sau khi dung:

```bash
curl http://127.0.0.1:18084/api/health
```

Neu can login admin:

```bash
curl -X POST http://127.0.0.1:18084/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin_test","password":"change-me-test"}'
```

## Chay browser test khong dung VNC

Moi profile Grok test nen duoc chay tren `DISPLAY` rieng de tranh tranh chap `:99`.

Vi du:

```bash
bash scripts/launch-test-profile-login.sh d5a1ef00-a053-4ca4-8ed8-58429b396a1a :101
bash scripts/launch-test-profile-login.sh dda2bb75-52ad-4a30-bda0-2f3082ef49c1 :102
bash scripts/launch-test-profile-login.sh e6980c8f-3d4b-4e0b-b70b-8f23e1872c26 :103
```

Script nay:

- tu tao `Xvfb` rieng cho tung `DISPLAY`
- set bien `DISPLAY` truoc khi goi `profile_login_bootstrap.py`
- khong di qua `x11vnc`
- khong dung chung `:99` nhu flow default

Neu can dung mot profile:

```bash
bash scripts/stop-test-profile-login.sh d5a1ef00-a053-4ca4-8ed8-58429b396a1a
```

## Luu y

- Moi truong nay doc `.env.test`, khong doc `.env` cua prod.
- Volume test chi mount `./storage-test`, nen profile/cookie/job/output se tach khoi prod.
- Neu ban muon dung 3 profile Grok test, hay tao va login lai trong moi truong test nay.
