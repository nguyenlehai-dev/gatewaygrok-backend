# Test Profile Map

## Test Environment

- API base: `http://127.0.0.1:18084`
- Admin username: `admin_test`
- Admin password: `change-me-test`
- Client API key name: `test-grok-client`
- Client API key prefix: `gg_k1sB2HLzC`

## Grok Test Profiles

- `grok-test-01`
  - profile_id: `d5a1ef00-a053-4ca4-8ed8-58429b396a1a`
  - display: `:101`
  - debug_port: `41082`

- `grok-test-02`
  - profile_id: `dda2bb75-52ad-4a30-bda0-2f3082ef49c1`
  - display: `:102`
  - debug_port: `47873`

- `grok-test-03`
  - profile_id: `e6980c8f-3d4b-4e0b-b70b-8f23e1872c26`
  - display: `:103`
  - debug_port: `50086`

## Useful Scripts

- Check all profile sessions:

```bash
bash scripts/check-test-profiles.sh
```

- Import cookies into a profile:

```bash
bash scripts/import-test-profile-cookie.sh d5a1ef00-a053-4ca4-8ed8-58429b396a1a /path/to/cookies.json
```

- Launch profile browser without VNC:

```bash
bash scripts/launch-test-profile-login.sh d5a1ef00-a053-4ca4-8ed8-58429b396a1a :101
```

- Launch profile runtime without VNC (daily operation path):

```bash
bash scripts/launch-test-profile-runtime.sh d5a1ef00-a053-4ca4-8ed8-58429b396a1a :101
```

- Stop profile runtime:

```bash
bash scripts/stop-test-profile-runtime.sh d5a1ef00-a053-4ca4-8ed8-58429b396a1a :101
```

- Check profile runtime debug ports:

```bash
bash scripts/check-test-profile-runtime.sh
```

- Verify client API key:

```bash
CLIENT_API_KEY_TEST='replace-me' bash scripts/verify-test-client-key.sh
```

- Submit a test job:

```bash
CLIENT_API_KEY_TEST='replace-me' bash scripts/create-test-client-job.sh d5a1ef00-a053-4ca4-8ed8-58429b396a1a image 'simple test prompt'
```

## Recommended Operational Flow

1. Bootstrap/login only when the profile loses session.
2. Confirm `session-check` returns `authenticated`.
3. Switch the profile to `launch-test-profile-runtime.sh`.
4. Keep runtime browser alive without VNC.
5. Submit jobs by API with the target `profile_id`.
