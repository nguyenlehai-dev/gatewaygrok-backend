# Git Basics And Gitflow

## 1. Git basic commands

### `git init`

Tạo Git repository mới trong thư mục hiện tại.

```bash
git init
```

### `git clone`

Clone repo từ remote về máy local.

```bash
git clone <repo-url>
```

### `git add`

Đưa file vào staging area trước khi commit.

```bash
git add .
git add app/main.py
```

### `git commit`

Tạo snapshot code đã staged.

```bash
git commit -m "feat: add profile asset upload"
```

### `git pull`

Lấy code mới từ remote về và merge vào branch hiện tại.

```bash
git pull origin dev
```

### `git push`

Đẩy branch local lên remote.

```bash
git push origin feat/grok-image-upload
```

## 2. Git branch concepts

- `prod`: branch production, chỉ merge khi sẵn sàng deploy
- `staging`: branch kiểm thử QA / demo
- `dev`: branch tích hợp cho team development
- `feat/<name>`: branch tính năng, tách từ `dev`
- `hotfix/<name>`: branch sửa lỗi gấp, tách từ `prod`

## 3. Commit message

Commit message phải ngắn, rõ, nói đúng mục đích thay đổi.

Ví dụ tốt:

- `feat: add grok image source upload flow`
- `fix: stabilize grok image extraction polling`
- `docs: add branch workflow for fe and be repos`

Ví dụ kém:

- `update`
- `fix bug`
- `done`

## 4. Gitflow for this project

Project này có 2 repo tách riêng:

- `gatewaygrok-backend`
- `gatewaygrok-frontend`

Cả 2 repo dùng cùng workflow dưới đây.

## 5. Main branch structure

Ba nhánh chính:

- `prod`
  - code production
  - chỉ merge sau khi kiểm tra kỹ
- `staging`
  - QA, demo, UAT
- `dev`
  - branch tích hợp cho team dev

Branch tính năng:

- `feat/<feature_name>`
  - ví dụ: `feat/login_page`
  - ví dụ: `feat/grok_image_upload`

Branch sửa lỗi gấp:

- `hotfix/<hotfix_name>`
  - ví dụ: `hotfix/fix_login_error`

## 6. Feature workflow

### Tạo feature branch

Luôn cắt từ `dev`.

```bash
git checkout dev
git pull origin dev
git checkout -b feat/grok_image_upload
```

### Làm việc trên feature

```bash
git add .
git commit -m "feat: add grok image upload support"
git push origin feat/grok_image_upload
```

### Merge flow

1. tạo PR từ `feat/xxx` vào `dev`
2. review
3. approve
4. merge vào `dev`

## 7. Promote flow

Khi đủ ổn định:

1. merge `dev` vào `staging`
2. QA / demo trên `staging`
3. khi pass, merge `staging` vào `prod`

Không merge thẳng feature vào `prod`.

## 8. Hotfix workflow

Hotfix luôn tách từ `prod`.

### Tạo hotfix

```bash
git checkout prod
git pull origin prod
git checkout -b hotfix/fix_login_error
```

### Sửa lỗi và push

```bash
git add .
git commit -m "fix: resolve login error on production"
git push origin hotfix/fix_login_error
```

### Merge hotfix

1. PR từ `hotfix/xxx` vào `prod`
2. approve
3. merge vào `prod`
4. merge tiếp `prod` vào `staging`
5. merge tiếp `prod` vào `dev`

Điểm này bắt buộc để tránh lệch code giữa các môi trường.

## 9. Rule for FE and BE

Nếu một task đi qua cả FE và BE:

- FE: `feat/grok_image_upload`
- BE: `feat/grok_image_upload`

Tên branch nên cùng intent để dễ trace PR giữa 2 repo.

## 10. Recommended merge policy

- `feat/*` -> `dev`: squash merge
- `dev` -> `staging`: merge commit
- `staging` -> `prod`: merge commit
- `hotfix/*` -> `prod`: squash hoặc merge commit đều được, nhưng phải sync ngược về `staging` và `dev`

## 11. Minimum PR checklist

Trước khi merge:

- backend test hoặc smoke check pass
- frontend build pass
- API contract đổi thì phải note rõ
- automation flow đổi thì phải note job id hoặc screenshot
- không commit secret

## 12. Apply now for this project

Với trạng thái hiện tại, quy trình nên là:

1. giữ `prod` làm branch release
2. dùng `staging` cho demo / QA
3. toàn bộ feature mới đi từ `dev`
4. mọi fix gấp production đi từ `hotfix/*` tách từ `prod`
