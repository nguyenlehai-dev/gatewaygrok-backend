# FE/BE Split

## Frontend React repo

FE chỉ làm 3 việc:

1. Trang quản trị profile, proxy, API key, settings, job queue
2. Form import cookie file cho profile
3. Dashboard gọi API backend, polling trạng thái job và render result

FE không giữ:

- cookie thật
- logic Playwright
- logic rate limit
- logic queue/concurrency
- logic proxy/antidetect

## Backend Python repo

BE là gateway thật, không phải auto tool độc lập:

1. Cấp REST API cho FE và client ngoài
2. Lưu profile, proxy, API key, setting, job
3. Quản lý storage riêng cho từng profile
4. Nhận cookie import và ghi storage state
5. Điều phối Playwright headless theo queue/concurrency
6. Tách provider logic cho Grok, Flow, Dreamina

## Data strategy

- SQLite cho local tool hoặc single node
- PostgreSQL/Supabase cho production online
- Mongo chỉ nên dùng nếu phát sinh nhu cầu lưu event log lớn, raw prompt history, audit stream hoặc metadata phi cấu trúc
