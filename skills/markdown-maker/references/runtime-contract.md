# File2MD runtime contract

The `file2md` Debian package for `riscv64` installs `/opt/file2md`, `file2md.service`, the runtime dependencies, PDFium, and model-install logic. The installed environment file is `/etc/file2md/file2md.env`; read `FILE2MD_WEB_HOST`, `FILE2MD_WEB_PORT`, `FILE2MD_DATA_DIR`, and `FILE2MD_WEB_MAX_UPLOAD_MB` instead of hard-coding them. Compare `${Version}` from `dpkg-query` with the APT `Candidate` using `dpkg --compare-versions`; never hard-code a release number.

Important endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | service and engine health |
| `GET /api/models` | model loading state, progress, message, nodes |
| `POST /api/models/prepare` | hot-update the idle resident worker's EP thread count |
| `POST /api/jobs` | local multipart file conversion |
| `GET /api/jobs/{id}` | status, progress, logs, error, metadata |
| `POST /api/jobs/{id}/cancel` | terminate only the isolated conversion worker |
| `GET /api/jobs/{id}/download` | ZIP containing Markdown and images |
| `GET /api/jobs/{id}/assets/{path}` | individual result asset |

The service also exposes `/api/jobs/url`; the skill must not use it because conversion is required to remain local and offline after installation.

`GET /api/models.capabilities.xlsx_formula_recalc=true` means File2MD owns XLSX formula-cache validation and LibreOffice recalculation for every caller, including the web UI. Upload the original XLSX and pass `xlsx_recalc=true`; preserve returned job warnings. `FORMULA_CACHE_REBUILT` means recalculation succeeded. `FORMULA_CACHE_RECALC_FAILED` or `FORMULA_RESULT_NOT_CACHED` on a completed job means File2MD continued with the original file and formula values may be empty. If the capability is absent, use the skill's client-side recalculation fallback for compatibility with older services and follow the same warning-and-continue contract.

Failed jobs may include `code`, `stage`, `root_cause`, `raw_message`, `retryable`, `remediation`, and `worker_pid`. Prefer these structured fields over reclassifying display logs. The API process owns persistent job state and must remain responsive while inference runs in a child process. The child is a supervised resident model worker: models load once during service startup and normal jobs reuse the same PID/session. A fatal worker exit causes the API to rebuild it before accepting more work. An idle EP-thread change is applied inside that same worker and does not reload models; a cold rebuild is reserved for worker exit, OOM, unreleased worker-owned TCM, cancellation, or model/provider configuration changes.

Service startup is model-ready startup. The systemd unit uses `Type=notify`; FastAPI waits for the resident worker to report `ready`, then sends `READY=1`. Therefore a successful `systemctl start file2md.service` means both the web UI/API and local models are ready for immediate conversion. `/api/models.startup` exposes cold-start timing such as MinerU import, engine construction, model preload, and total worker-ready seconds.

Processing jobs may additionally expose `health`, `last_activity_at`, `no_progress_seconds`, and `diagnostics`. `suspected_stall` starts a diagnostic observation window. `slow_but_active` means callbacks are quiet but worker CPU/I/O/RSS changed, so conversion continues. `confirmed_stall` means neither callbacks nor process resources changed; the worker still runs unless the administrator explicitly enables automatic termination or the caller invokes the cancel endpoint.

OOM failures include task-scoped worker exit and memory/TCM diagnostics. The skill performs a post-failure TCM check. Automatic cleanup is permitted only when all busy blocks name the failed worker PID, that PID is dead, and there are no live, unknown, or foreign owners. Cleanup outcome is diagnostic metadata and must not replace the primary `WORKER_OOM_KILLED` code or trigger an automatic retry.
