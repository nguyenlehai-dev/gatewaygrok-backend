# Grok Gateway No-VNC Plan

## Muc tieu

Xac dinh phuong an kha thi cho `gatewaygrok-staging` trong truong hop:

- Khong muon dung VNC de van hanh hang ngay
- Tao san `3 profile` cho `3 account Grok`
- Khach chi goi `API` de tao job
- Web chi dong vai tro dashboard/admin, khong phai kenh su dung chinh

## Ket luan ngan

Phuong an kha thi nhat voi code hien tai la:

- Tao san 3 profile, moi profile gan voi 1 account Grok
- Login san cho tung profile
- Khong dung VNC trong van hanh thuong ngay
- Khach goi API kem `profile_id` de chay job tren profile tuong ung
- Moi profile nen de `concurrency_limit = 1`

Tuy nhien, voi implementation hien tai cua provider `Grok`, he thong van dang yeu cau `live browser` cho profile khi chay job. Nghia la:

- Co the bo VNC
- Nhung chua the bo hoan toan viec giu browser/profile dang song

Can noi ro hon:

- `No-VNC` o day co nghia la `khong can human remote desktop trong van hanh hang ngay`
- Runtime van nen giu 1 Chromium thuc su dang song cho moi profile
- VNC chi la `temporary bootstrap/debug path` khi can login lai bang tay
- `headless thuần` hien chua on dinh voi Grok/Cloudflare

## Trang thai da xac nhan tren testflowgrok

Cap nhat ngay `2026-04-14`:

- Moi truong test dung API port `18084`, storage rieng `storage-test`, container `gatewaygrok-api-test`
- Frontend test dung `https://testflowgrok.plxeditor.com/` va nen proxy `/api`, `/storage`, `/docs` ve API test `18084`
- Runtime no-VNC dung endpoint `POST /api/profiles/{profile_id}/launch-runtime`
- Job khach dung `POST /api/client/jobs` voi `x-api-key` va `profile_id`
- VNC khong con la runtime path bat buoc; chi dung khi can login/verify bang tay

Ket qua smoke test Profile 3 `e6980c8f-3d4b-4e0b-b70b-8f23e1872c26`:

- `image`: pass, output local `.jpg`
- `video` voi `provider_payload.video_mode = text_to_video`: pass, output local `.mp4`
- `video` voi `provider_payload.video_mode = image_to_video`: pass, output Grok public `.mp4`

Nhung loi da xu ly trong qua trinh test:

- CDP attach khong duoc dong browser live sau job, neu khong runtime bi tat va VNC/browser bi roi
- Cookie/privacy overlay co the chan click editor/submit, can dismiss/remove trong automation
- Grok co `input[type=file]` an dung truoc editor, nen helper tim field phai uu tien element visible va chi cho phep hidden voi file upload
- Neu dang o `/imagine/post/...`, job moi phai quay ve `/imagine` truoc khi nhap prompt moi
- Submit phai uu tien click nut `Submit`; khong nen bam `Enter` truoc vi co the submit thanh cong roi lam editor trong, sau do code submit lai se gap `Submit button stayed disabled`
- Fallback JS khong duoc dua selector Playwright `:has-text(...)` truc tiep vao `document.querySelector`

## Hien trang ky thuat

### 1. Backend da co queue va gioi han theo profile

`JobRunner` da ho tro:

- Queue job toan cuc
- `global_concurrency`
- `profile_semaphore` theo tung profile
- `concurrency_limit` tren model profile

Tac dong:

- Co the nhan nhieu request tu API
- Moi profile van co the chay tuan tu
- Phu hop voi mo hinh `1 profile = 1 account = 1 luong job on dinh`

File tham chieu:

- `be/app/services/job_runner.py`
- `be/app/models/profile.py`

### 2. Client da co the goi truc tiep API vao profile cu the

Client API route da ho tro:

- `POST /api/client/generate`
- `POST /api/client/jobs`

Neu truyen `profile_id`, backend se:

- Tim dung profile
- Kiem tra session san sang
- Tao job va dua vao queue

Dieu nay dung voi nhu cau: khach chi can biet `API key + profile_id`.

File tham chieu:

- `be/app/api/routes/client.py`

### 3. Frontend hien tai chi la dashboard/admin

FE hien tai phuc vu:

- Tao va sua profile
- Upload cookie
- Session check
- Launch login
- Theo doi trang thai profile/job

No khong phai runtime chinh cho khach tich hop.

File tham chieu:

- `be/docs/architecture.md`
- `fe/src/pages/ProfilesPage.tsx`

### 4. Grok provider hien tai dang yeu cau live browser

Day la diem quyet dinh lon nhat.

Trong `grok.py`, session analysis tra ve:

- `requires_live_browser = True`

Sau do `session_guard.py` se chan job neu:

- Profile can live browser
- Nhung browser hien tai khong con attached

Tac dong:

- Chi import cookie roi tat het browser la chua du
- He thong hien tai uu tien attach vao browser dang mo cua profile
- Neu khong attach duoc, job co the bi chan truoc khi chay

File tham chieu:

- `be/app/services/automation/grok.py`
- `be/app/services/session_guard.py`
- `be/app/services/automation/base.py`

### 5. VNC chi la fallback cho bai toan login tu xa

Script login hien tai:

- Neu co `DISPLAY`, mo browser binh thuong
- Neu khong co `DISPLAY`, moi dung `Xvfb + x11vnc`

Tac dong:

- VNC khong phai bat buoc cua job runtime
- VNC chi la cach de login/verify tu xa tren server khong co desktop

Trang thai test hien tai:

- Login bang `Xvfb + VNC` co the dua profile ve `authenticated`
- Nhung VNC/browser launcher hien tai co the roi session, nen khong phu hop cho van hanh lau dai
- Thu nghiem `headless + user_data_dir` van bi Cloudflare dua ve `Just a moment...`
- Do do, huong kha thi nhat hien nay la:
  - bootstrap bang tay khi can
  - sau do chuyen sang runtime `headful trong Xvfb, khong mo VNC`

File tham chieu:

- `be/scripts/profile_login_bootstrap.py`

## Dinh nghia ro 2 giai doan

### 1. Bootstrap session

Muc dich:

- Dang nhap Grok
- Vuot Cloudflare/checkpoint khi session het han
- Cap nhat `storage_state` / `user_data_dir`

Cong cu:

- Co the dung `launch-login`
- Co the dung `profile_login_bootstrap.py`
- Co the dung VNC neu can thao tac tay

Luu y:

- Day la duong `bao tri/ho tro`
- Khong phai duong runtime chinh cho khach

### 2. Runtime no-VNC

Muc dich:

- Giu browser cua profile dang song
- Khong can mo desktop/VNC cho admin
- API goi truc tiep vao profile da san sang

Cong cu:

- `be/scripts/profile_runtime_bootstrap.py`
- `be/scripts/launch-test-profile-runtime.sh`
- `be/scripts/stop-test-profile-runtime.sh`
- `be/scripts/check-test-profile-runtime.sh`

Luu y:

- Runtime nay van la `headed browser` trong `Xvfb`
- Chi bo VNC, khong bo browser song
- Day la buoc trung gian hop ly truoc khi tiep tuc R&D de bo han live browser

## Phan tich theo tung mo hinh

### Mo hinh A: 3 profile, login san, giu browser song, khach chi goi API

Trang thai: `Kha thi ngay voi code hien tai`

Mo ta:

- Tao 3 profile Grok
- Moi profile gan voi 1 account
- Login san cho tung profile
- Giu browser/profile dang song
- Khach goi API kem `profile_id`
- Moi profile xu ly job theo queue rieng

Uu diem:

- Dung voi logic code hien tai
- Khong can VNC trong van hanh thuong ngay
- De kiem soat loi session
- De scale ngang bang cach tang them profile

Nhuoc diem:

- Ton RAM/CPU vi phai giu browser song
- Van can co co che login lai khi session het han
- Van co operational overhead de quan ly 3 browser/profile

Danh gia:

- Day la phuong an nen chon cho giai doan gateway truoc

### Mo hinh B: 3 profile, import cookie, tat browser, chi goi API headless

Trang thai: `Chua phu hop voi code hien tai`

Mo ta:

- Tao 3 profile
- Import cookie/storage
- Khong giu browser nao song
- Khi co job moi mo browser headless de chay

Van de:

- `session_guard` hien tai co the chan vi `requires_live_browser = True`
- `Grok` implementation dang duoc thiet ke de uu tien browser dang attach
- Muc do on dinh voi session Grok chua duoc dam bao neu bo browser song

Danh gia:

- Khong nen cam ket theo huong nay neu chua sua code va test lai

### Mo hinh C: 1 profile nhan nhieu job cung luc

Trang thai: `Khong nen ap dung cho Grok`

Van de:

- De xung dot state tren cung account/browser
- Tang kha nang rate limit, verification, checkpoint
- Tang RAM/CPU dang ke
- Kho debug khi nhieu flow dong thoi tren cung profile

Danh gia:

- Nen queue tuan tu theo profile
- Muon tang thong luong thi tang them profile/account

## Phuong an de xuat

### Nguyen tac moi truong

De dung mo hinh moi an toan, can tach ro `test/staging` va `prod`.

Bat buoc:

- `test` khong duoc dung chung DB voi `prod`
- `test` khong duoc dung chung `storage_root` voi `prod`
- `test` khong duoc dung chung `profiles_root` voi `prod`
- Neu co 3 account Grok de test, nen tach rieng khoi account prod

Ly do:

- Profile, cookie, storage state, output media va job history deu duoc luu theo DB + filesystem
- Neu dung chung DB hoac chung storage, test co the lam ban session/profiles cua prod
- Voi Grok live browser flow, roi ro con lon hon vi browser dang bam vao `user_data_dir` cua profile

### Mo hinh moi truong de xuat

#### Muc tieu

Dung duoc mo hinh No-VNC trong `test/staging` ma khong anh huong `prod`.

#### Cach tach

Moi truong `test/staging`:

- DB rieng
- Storage rieng
- Profiles rieng
- API key rieng
- Co the dung cung codebase, nhung config env phai rieng

Moi truong `prod`:

- DB rieng
- Storage rieng
- Profiles rieng
- API key rieng
- Browser runtime rieng

#### Goi y config

Test/staging:

- `GATEWAY_DATABASE_URL=sqlite:///./storage-test/gateway_grok_test.db`
- `GATEWAY_STORAGE_ROOT=storage-test`
- `GATEWAY_PROFILES_ROOT=storage-test/profiles`
- Port API rieng neu can
- Thu muc volumes rieng neu chay Docker

Prod:

- `GATEWAY_DATABASE_URL=sqlite:///./storage/gateway_grok.db` hoac Postgres/Supabase rieng
- `GATEWAY_STORAGE_ROOT=storage`
- `GATEWAY_PROFILES_ROOT=storage/profiles`

Ghi chu:

- Hien tai code cho phep doi DB bang env `GATEWAY_DATABASE_URL`
- Hien tai test smoke da dang dung DB rieng bang env
- App dang tao schema tu SQLAlchemy models bang `create_all`, chua co migration versioning

### Mo hinh kha thi nhat cho test

Trang thai: `Nen lam ngay`

Trong moi truong test/staging:

- Tao 3 profile Grok test
- Moi profile map 1 account Grok test
- `concurrency_limit = 1`
- Login san cho tung profile
- Giu browser cua tung profile dang song
- Khach test chi goi API vao `test/staging`
- Web test chi de admin quan sat

Day la mo hinh gan nhat voi prod mong muon, nhung van tach biet hoan toan du lieu va session.

### Phuong an MVP

Muc tieu:

- Di duoc nhanh
- Bo VNC khoi van hanh hang ngay
- Dam bao khach chi goi API

Trien khai:

1. Tao 3 profile Grok trong dashboard hoac API admin
2. Gan proxy rieng neu can
3. Dat `concurrency_limit = 1` cho moi profile
4. Bootstrap login cho tung profile khi can
5. Session check va xac nhan profile o trang thai `authenticated`
6. Chuyen tung profile sang `runtime no-VNC` (browser song trong `Xvfb`, khong mo VNC)
7. Cap `API key` cho khach
8. Khach goi API voi `profile_id` cu the
9. Web chi de admin theo doi job, profile, va xu ly su co

Ky vong ket qua:

- Khach chi lam viec qua API
- He thong van on dinh theo tung profile
- Khong can mo VNC trong qua trinh chay job binh thuong
- Chi can mo VNC/bootstrap neu profile bi logout hoac Cloudflare xuat hien lai

### Phuong an trien khai test khong chung DB voi prod

Muc tieu:

- Dung mo hinh moi trong `test/staging`
- Khong lam anh huong profile, job, cookie va session cua `prod`

Trien khai:

1. Tao file env rieng cho test, vi du: `.env.test`
2. Set `GATEWAY_DATABASE_URL` sang DB test rieng
3. Set `GATEWAY_STORAGE_ROOT` sang thu muc storage test rieng
4. Set `GATEWAY_PROFILES_ROOT` sang thu muc profiles test rieng
5. Chay API test tren port rieng
6. Tao lai 3 profile test bang UI hoac API admin
7. Login 3 account test tren moi truong test
8. Xac nhan `session-check` cua test chi thao tac tren thu muc test
9. Cho khach test API chi vao domain/port test

Ky vong ket qua:

- `prod` khong bi dong vao DB
- `prod` khong bi dung chung `user_data_dir`
- `prod` khong bi dung chung output media/job history
- Co the test thuc chien mo hinh 3 profile API-first an toan

### Mau phan tach toi thieu can dam bao

Can khac nhau giua test va prod:

- `database_url`
- `storage_root`
- `profiles_root`
- API port/base URL
- Admin token secret
- Admin credentials
- API keys

Nen khac nhau neu co the:

- Account Grok
- Proxy
- Domain/subdomain deploy
- Volume mount Docker

Khong nen dung chung:

- File SQLite
- Thu muc `storage`
- Thu muc `storage/profiles`
- `user_data_dir` cua browser
- Cookie files
- Output assets/media

### Phuong an nang cap sau MVP

Neu muon bo ca yeu cau `live browser`, can lam them:

1. Ra soat va sua `Grok session analysis` de khong mac dinh `requires_live_browser = True`
2. Test lai kha nang chay headless tu `storage_state` hoac `user_data_dir`
3. Xac minh Grok co giu session on dinh khi browser chi mo luc co job
4. Danh gia lai ti le gap Cloudflare, login prompt, checkpoint
5. Sua FE/BE de phan biet ro:
   - `cookie ready`
   - `session ready`
   - `live browser required`
   - `headless-ready`

Danh gia:

- Day la bai toan R&D, khong nen cam ket gap neu khach dang can gateway truoc

## Flow van hanh de xuat

### Flow 1: Setup profile moi

1. Tao profile
2. Import cookie neu co san
3. Neu chua du session, chay bootstrap login
4. Session check den khi profile `authenticated`
5. Launch runtime no-VNC cho profile do
6. Re-check `session-check`
7. Cap `profile_id` cho khach test

### Flow 2: Van hanh thuong ngay

1. Dam bao API test/prod dang chay
2. Dam bao moi profile runtime dang `open`
3. Khach goi `POST /api/client/jobs` voi `profile_id`
4. Backend queue theo profile
5. Dashboard chi de admin theo doi

### Flow 3: Khi profile rot session

1. Job bi chan boi `ensure_profile_session_ready`
2. Admin chay `session-check`
3. Neu ra `security_verification` hoac `login_required`:
   - tam dung runtime profile do
   - chay bootstrap login
   - login/verify lai
   - xac nhan `authenticated`
   - launch runtime no-VNC lai

## Script de xuat cho test/staging

### Bootstrap

Login bang tay khi can:

```bash
bash scripts/launch-test-profile-login.sh d5a1ef00-a053-4ca4-8ed8-58429b396a1a :101
```

Stop bootstrap:

```bash
bash scripts/stop-test-profile-login.sh d5a1ef00-a053-4ca4-8ed8-58429b396a1a
```

### Runtime no-VNC

Launch runtime browser cho profile:

```bash
bash scripts/launch-test-profile-runtime.sh d5a1ef00-a053-4ca4-8ed8-58429b396a1a :101
```

Stop runtime:

```bash
bash scripts/stop-test-profile-runtime.sh d5a1ef00-a053-4ca4-8ed8-58429b396a1a :101
```

Check debug port/runtime status:

```bash
bash scripts/check-test-profile-runtime.sh
```

### API runtime endpoints

Launch runtime qua API admin:

```bash
curl -X POST "$BASE_URL/api/profiles/$PROFILE_ID/launch-runtime" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "display": ":103",
    "start_url": "https://grok.com/imagine"
  }'
```

Check runtime:

```bash
curl "$BASE_URL/api/profiles/$PROFILE_ID/runtime-status" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Check session:

```bash
curl -X POST "$BASE_URL/api/profiles/$PROFILE_ID/session-check" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### Client job payloads da test

Image:

```json
{
  "profile_id": "e6980c8f-3d4b-4e0b-b70b-8f23e1872c26",
  "target": "image",
  "prompt": "minimal product photo of a matte black perfume bottle on black obsidian stone, dramatic studio lighting",
  "count": 1
}
```

Text to video:

```json
{
  "profile_id": "e6980c8f-3d4b-4e0b-b70b-8f23e1872c26",
  "target": "video",
  "prompt": "cinematic slow motion shot of a matte black perfume bottle on black obsidian stone, subtle smoke, studio light, 5 seconds",
  "count": 1,
  "provider_payload": {
    "video_mode": "text_to_video",
    "duration": 5,
    "quality": "Speed"
  }
}
```

Image to video:

```json
{
  "profile_id": "e6980c8f-3d4b-4e0b-b70b-8f23e1872c26",
  "target": "video",
  "prompt": "slow cinematic camera push-in, subtle smoke drifting around the bottle, luxury commercial style",
  "count": 1,
  "provider_payload": {
    "video_mode": "image_to_video",
    "source_asset_path": "storage-test/profiles/PROFILE_ID/output/IMAGE_JOB_ID-image-1.jpg",
    "duration": 5,
    "quality": "Speed"
  }
}
```

## Rang buoc da duoc xac nhan trong qua trinh test

- `session-check` co the tra `authenticated` khi attach dung live browser cua profile
- `headless thuần` tu `user_data_dir` hien van co kha nang roi vao `security_verification`
- Job Grok hien van can `live browser`
- Vi vay, MVP dung nhat hien nay la:
  - `bootstrap bang tay khi can`
  - `runtime no-VNC voi browser song`
  - `1 profile = 1 concurrency`

## Cac rui ro can noi truoc voi khach

### Rui ro session

- Session Grok co the het han
- Tai khoan co the bi logout
- Cloudflare/security verification co the xuat hien lai

Tac dong:

- Se can login lai profile
- VNC hoac mot hinh thuc login thu cong van co the can cho giai doan bao tri

### Rui ro tai nguyen server

- Moi browser/profile dang song tieu ton RAM
- Chay job se lam RAM tang them do Chromium/Playwright

Tac dong:

- Can can doi RAM theo so profile dang online
- Khong nen day concurrency cao tren cung 1 profile

### Rui ro van hanh

- Neu browser cua profile bi dong, session check co the fail
- Job co the bi chan truoc khi vao queue thuc thi

Tac dong:

- Can co monitoring cho tung profile
- Nen co checklist van hanh cho admin

## De xuat cach noi voi khach

Noi gon:

`Ben em co the lam theo mo hinh 3 profile cho 3 account, khach chi goi API vao profile can dung. Web chi de hien thi va quan tri. Ben em khong can dung VNC trong van hanh binh thuong, nhung voi flow Grok hien tai thi moi profile van nen duoc giu browser song de dam bao job chay on dinh.`

Neu khach hoi them ve VNC:

`VNC khong dung cho luc chay job, ma chu yeu la phuong an ho tro login/xac minh tu xa khi can. Con khi van hanh thong thuong, he thong nhan API va tu chay automation tren profile da duoc chuan bi san.`

## Checklist trien khai de xuat

- Tao 3 profile Grok
- Dat `concurrency_limit = 1` cho moi profile
- Gan proxy neu can tach IP
- Login san 3 account
- Chay `session-check` cho tung profile
- Xac nhan profile o trang thai `authenticated`
- Xac nhan browser dang `attached` cho profile Grok
- Chuyen profile sang runtime no-VNC
- Kiem tra `debug_port` cua tung profile o trang thai `open`
- Tao `API key` cho khach
- Test `POST /api/client/jobs` voi `profile_id`
- Test 3 job dong thoi tren 3 profile khac nhau
- Test 2 job lien tiep tren cung 1 profile de xac nhan queue
- Theo doi RAM/CPU de chot cau hinh server

## Khuyen nghi cuoi cung

De dap ung nhu cau hien tai, huong dung nhat la:

- Chon `gateway/API-first`
- Giu web lam dashboard
- Bo VNC khoi van hanh thuong ngay
- Dung `3 profile song song cho 3 account`
- `1 profile = 1 concurrency`

Neu muon bo hoan toan browser song va chay headless thuần tu cookie/session, can xem do la phase sau va can co mot vong test/R&D rieng.
