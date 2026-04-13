# Gateway Grok Backend

Backend Python cho mô hình gateway:

- FE React ở repo riêng, chỉ gọi REST API của backend này.
- Backend giữ toàn bộ orchestration: profile, proxy, cookie import, API key, queue concurrency, Playwright automation.
- Mặc định dùng SQLite tối ưu cho local tool.
- Khi triển khai online có thể đổi thẳng sang PostgreSQL/Supabase qua `GATEWAY_DATABASE_URL`.
- Admin endpoints dùng bearer token riêng cho dashboard/operator.

## Tính năng đã dựng

- Quản lý profile theo category: `grok`, `flow`, `dreamina`
- Mỗi profile có `user-data`, `cache`, `cookie state` riêng
- Import cookie từ `.txt` hoặc `.json`
- Quản lý proxy
- Antidetect cơ bản theo profile: `user_agent`, `locale`, `timezone`, `viewport`, `platform`, `hardware_concurrency`
- Hệ thống API key cho client gọi gateway
- Hàng đợi job với global concurrency và per-profile concurrency
- Tự requeue job `pending/running` khi backend restart
- Metadata/overview endpoints để FE React repo dựng dashboard
- Adapter Playwright headless cho Grok, Flow; Dreamina đã được đăng ký category nhưng chưa triển khai automation
- Admin auth cho FE/operator
- Session check cho profile Grok/Flow truoc khi chay automation
- Job submission bi chan neu session check khong dat `authenticated`

## Chạy local

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
uvicorn app.main:app --reload
```

API docs: `http://localhost:8000/docs`

## Admin auth

- `POST /api/auth/login`
- `GET /api/auth/bootstrap`
- Toan bo admin endpoints (`/meta`, `/profiles`, `/proxies`, `/api-keys`, `/settings`, `/jobs`) can `Authorization: Bearer <token>`
- Client gateway endpoints `/api/client/*` van dung `x-api-key`

## Cấu trúc

- `app/api/routes`: REST endpoints cho admin và client
- `app/models`: SQLAlchemy models
- `app/services`: business logic, cookie import, job runner, automation providers
- `docs/architecture.md`: phân tách FE/BE
- `docs/frontend-contract.md`: contract để FE React bám vào
- `tests/test_gateway_smoke.py`: smoke test cho API lifecycle

## Database

- Local: `SQLite + WAL + foreign keys`
- Online: `PostgreSQL/Supabase` bằng cách đổi `GATEWAY_DATABASE_URL`
- Mongo chưa cần cho CRUD lõi; nếu sau này cần log event/raw artifacts lớn thì nên tách sang Mongo hoặc object storage

## Lưu ý bảo mật

- Không commit tài khoản Grok/Google vào source.
- Luồng chuẩn là import cookie vào profile rồi gateway dùng Playwright headless với storage riêng của profile đó.
- API key chỉ trả về `plain_key` đúng một lần lúc tạo.

## Verify nhanh

```bash
pip install -r requirements-dev.txt
python -m unittest tests.test_gateway_smoke -v
```
