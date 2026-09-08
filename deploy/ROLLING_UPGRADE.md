# Single-host rolling upgrade

This deployment remains one steady-state systemd service on port 8000. A
temporary instance on 8001 bridges the upgrade; it is not a second permanent
worker. Never overwrite a running process's source tree.

## Preconditions

- Run backend compileall, full tests and pip check, frontend tests/build, the
  opt-in PostgreSQL key-limit concurrency regression, and frontend deploy tests.
- Record the actual source-file hashes, production unit/config, frontend target
  and current schema version. Preserve unrelated local artifacts.
- Back up source, nginx config, service config and PostgreSQL before mutation.
- Check both `usage_logs` pending calls and established backend connections.
  An idle instant does not mean there are no users online.
- Stage the new source under a separate immutable release directory. Use the
  existing virtualenv only if requirements are unchanged.

## Schema 20260908_0008

Adds only a nullable `usage_logs.runtime_id` column. Existing records and costs
are not rewritten. PostgreSQL lock wait is capped at one second; abort/retry
rather than queue a migration behind active transactions. No new index is
required: recovery first narrows by the existing pending-status index.

Apply the migration explicitly from the staged version before starting it.
Keep the additive column if the application is rolled back. Do not downgrade a
live database as part of an application rollback.

## Cutover

1. Start staged backend on loopback 8001, as `tokenpool`, with the existing secret
   EnvironmentFile. Override `AUTO_MIGRATE=false`, `SEED_ON_STARTUP=false`, and
   `MODEL_SYNC_ENABLED=false`. Set `USAGE_RUNTIME_DIR` to the **same physical
   directory** used by the primary, e.g. `/opt/tokenpool/backend/data/usage-runtime`.
   Never put it under service-private `/tmp` (`PrivateTmp=true`) or a release
   directory. OS lock files must not be removed while instances may be alive.
2. Check readiness, authentication, expected routes and one small authorized
   streaming smoke; verify DONE, usage and final audit status, not only HTTP 200.
3. Save nginx config, update all backend proxy locations from 8000 to 8001,
   `nginx -t`, then graceful reload. On config validation/reload failure restore
   the saved config. Keep old workers and the old backend alive for existing SSE.
4. Wait until old-port established connections and old-instance pending audit
   records have drained. Require repeated zero samples. Do not stop a busy
   instance or impose a forced stream-kill deadline.
5. Only then stop primary, replace its verified source with the staged files and
   start it. Check readiness. While this happens, 8001 continues serving users.
6. Gracefully switch nginx back to 8000 after readiness. Drain 8001 and its owned
   pending logs before stopping the temporary unit. A failed drain means leave
   both instances available and report the unfinished cleanup.
7. Publish frontend with `deploy-frontend-atomic.sh` and
   `validate_frontend_release.py` together. This retains old hashed assets for
   already-open pages and verifies the served homepage and assets after switching.
8. Verify file hashes, service/config/schema, real audit outcomes and proxy 5xx
   during the window. Do not claim an end-to-end no-interruption guarantee from
   a health endpoint alone.

## Failure and rollback boundaries

- Before nginx cutover, failed candidate readiness does not affect old traffic.
- If primary replacement/start fails while the candidate is healthy, keep nginx
  on 8001. Restore primary from backup without interrupting candidate traffic.
- **Old 5744420 startup performs age-based pending recovery.** Before restarting
  that old binary, drain all candidate requests or explicitly disable its old
  recovery path. The old binary otherwise can misclassify active streams older
  than five minutes. Schema compatibility alone does not make that rollback safe.
- New owner-aware recovery only handles same-host/same-directory tagged calls.
  Legacy NULL owners and foreign namespaces require explicit operator review;
  do not bulk-recover them while an old instance may still be serving requests.
- Recovery preserves a terminal status committed concurrently by the old owner.
  Lifespan waits for detached audit cleanup before releasing process ownership.
- Keep backups and prior release directories; restore service availability
  before considering cleanup. Never delete or recalculate historical costs as
  part of this upgrade.

## Local checks

From backend: `python -m compileall -q app scripts tests`, `python -m pytest`, and
`python -m pip check`. Set `TOKENPOOL_TEST_POSTGRES_URL` only to a disposable
local PostgreSQL database for the opt-in concurrency test. The test creates and
removes its own random schema.

From frontend (Node 22 with type stripping): `npm test` and `npm run build`.
On Linux/WSL: `python3 deploy/test_frontend_deploy.py`; it creates isolated
temporary paths and stub service commands, never real production targets.
