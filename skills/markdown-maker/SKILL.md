---
schema_version: 2
name_zh: 文档转 Markdown
name_en: File2MD Local
name: markdown-maker
version: "v1.0.5"
description: Convert local PDF, PPTX, Word, XLSX, PNG, JPG, and related documents to Markdown on a Bianbu riscv64 device through the local File2MD runtime. Use when a task needs offline document conversion, File2MD service start/stop/restart/status control, local quantized-model status, file validation, progress/error reporting, ZIP result extraction, or a saved Markdown path; the runtime is installed from APT or a supplied riscv64 .deb on first use and then called over the device-local API.
description_zh: 在 Bianbu riscv64 设备上通过本地 File2MD 运行时把 PDF、PPTX、Word、XLSX、PNG、JPG 等文档转换为 Markdown，源文件与转换结果都不上传云端；覆盖服务启停与状态查询、本地量化模型就绪检查、文件校验、任务提交、失败诊断与 ZIP 结果解压。
---

# File2MD Local

Use this skill when conversion must run on the Bianbu device, without uploading documents or conversion results to a cloud service. The skill manages the `file2md` Debian runtime, checks local model readiness, validates files, submits jobs, diagnoses failures, downloads the result ZIP, and reports the extracted Markdown path.

## Runtime contract

- Target: this device only; never hard-code a deployment address in a published skill. Override the API endpoint with `FILE2MD_WEB_HOST` / `FILE2MD_WEB_PORT` / `FILE2MD_API_BASE` only when needed.
- Package: Debian package `file2md` for `riscv64`; never assume a fixed package version.
- Service API: read `/etc/file2md/file2md.env`; current releases normally use `http://127.0.0.1:8070`, not port 7860.
- Runtime service: `file2md.service`.
- The wrapper invokes local `systemctl`, `apt-get`, `dpkg`, `journalctl`, and `curl` directly through `subprocess`; no SSH layer.
- Never call the URL-conversion endpoint. Submit only local files to `POST /api/jobs`.
- First installation may need network and root/sudo. After the runtime and models are installed, conversion is local/offline.

## Standard workflow

1. Collect the local input file and optional output directory. The skill assumes `file2md.service` runs on this device and exposes its API on `http://127.0.0.1:8070`; override with `FILE2MD_WEB_HOST` / `FILE2MD_WEB_PORT` (or set `FILE2MD_API_BASE` directly) when the API listens on a different address. By default, save results under `~/File2MD/<source-stem>-<job-id>/` on this machine.
2. Run `python3 scripts/file2md.py ensure-runtime` as root or with passwordless sudo for `apt-get` / `dpkg` / `systemctl`. It checks architecture, installed version, APT candidate version, service state, API port, and model readiness. If `file2md` is missing, it runs `sudo -n apt-get update` then `sudo -n apt-get install -y file2md`; pass `--deb-source` to install a local riscv64 `.deb` when APT is unavailable. By default it refreshes APT metadata and upgrades only when a newer candidate exists; if an installed runtime is present but the refresh fails, it continues offline with the installed version. If the installed service is stopped, it starts `file2md.service`, then waits for health/model readiness. Without sudo the script returns `PRIVILEGE_REQUIRED` with the exact command to re-run manually.
3. Validate the input before upload: regular file, supported suffix, size <= the server limit (read from `FILE2MD_WEB_MAX_UPLOAD_MB`, default 100 MiB), and a matching file signature/container. Reject malformed or mismatched files locally.
4. Run `python3 scripts/file2md.py convert`. Before submission it records memory and TCM state. It never clears a block owned by a live process or a block whose owner cannot be verified. A stale allocation may be cleared once when every owner PID is confirmed dead. It then creates a job through `POST /api/jobs`, polls `/api/jobs/{id}`, and prints filename, byte size, route/status, elapsed time, model state, logs, and failure diagnostics. There is no fixed conversion deadline. File2MD detects missing MinerU/page-level progress, marks a task as suspected stalled, and observes process resources before confirming a stall. Classify a continuously unresponsive API separately after `--stall-timeout` (default 60 seconds).
5. On completion, download `/api/jobs/{id}/download` into `/tmp/file2md-result-<job-id>.zip`, copy it into `~/File2MD/<source-stem>-<job-id>/` by default, locate the Markdown file, and verify that it is non-empty and contains normal Markdown constructs. Report the absolute `.md` path and the `images/` directory when present. Treat `--output-dir` as an override for the result root.
6. Keep the downloaded ZIP and extracted files unless the user asks for cleanup. Do not delete the on-device job data automatically.

## Format routing expectations

- PDF: MinerU layout/OCR/formula/table pipeline.
- PPT/PPTX and DOC/DOCX: LibreOffice conversion followed by the PDF pipeline.
- XLS/XLSX: direct spreadsheet parsing to Markdown tables.
- PNG/JPG/JPEG and other accepted images: image-to-PDF/layout/OCR/formula/table pipeline.

The skill must display the original filename, byte size, validation result, route, processing status, and final path. Treat performance targets as measured values, not promises: report model-load seconds, elapsed seconds, page count, and PDF seconds per page when the API exposes them. Report explicit booleans for the `<2s` model-load and `<5s/page` PDF targets rather than claiming success without measurements.

For XLSX, prefer the server capability `capabilities.xlsx_formula_recalc`: upload the original file and let File2MD recalculate a temporary copy, preserving all formula-cache warnings. When connected to an older server without that capability, inspect worksheet XML before submission and retain the client-side LibreOffice fallback. In both paths leave the original untouched. If recalculation fails, continue conversion with the original file and prominently report the affected cells, failure reason, remediation, and that formula values may be empty.

## Failure handling

Use `references/error-remediation.md` to map API errors, logs, transient API disconnects, service restarts, and journal messages to a stable error code and actionable remediation. In particular:

- `MODEL_LOAD_FAILED` / `MODEL_NOT_READY`: check `/api/models`, model directory, disk space, and rerun the package runtime installer.
- `LIBREOFFICE_NOT_FOUND` / conversion errors: check `command -v libreoffice` and retry Office conversion after installing the required LibreOffice components.
- `WORKER_OOM_KILLED`: require task-scoped OOM evidence. A catchable `MemoryError` shuts down the engine in the worker `finally` path. A kernel SIGKILL cannot run cleanup, so inspect TCM afterward and clear it only when every busy block is exclusively owned by that dead worker PID. Verify all blocks are free, report cleanup success/failure separately, and never retry the OOM task automatically. Recommend waiting for memory, disabling optional stages, or splitting the file.
- `SPACEMIT_TCM_ACQUIRE_FAILED` / `TCM_STALE_ALLOCATION` / `TCM_BUSY`: distinguish an acquire failure, a dead owner, and a live or unverifiable owner. Clear TCM only for verified dead owners, then retry at most once.
- `OCR_FAILED`, `TABLE_FAILED`, or formula errors: preserve partial logs/results when available and explain that recognition may be incomplete; retry with a clearer image or adjusted DPI/language.
- `CONVERSION_STALLED`: report only after both the no-progress threshold and the diagnostic observation window pass without callbacks or worker resource activity. Do not kill the worker by default; return the job id, diagnostics, and cancel endpoint.
- `CLIENT_WAIT_LIMIT_REACHED`: an explicitly configured client wait limit ended; the server task continues and must not be reported as a conversion failure.
- `OUTPUT_MISSING`: download failure or no `.md` in the ZIP; retain the ZIP for diagnosis and inspect service logs.

If the API becomes unreachable during processing, do not claim a normal conversion failure until checking `systemctl status file2md.service` and recent `journalctl -u file2md.service` output locally.

## Service lifecycle

Use the explicit service subcommand for lifecycle operations. `status` is read-only. `start`, `stop`, and `restart` affect only `file2md.service`, invoke systemd through sudo, wait for the requested terminal state, and emit structured JSON. `start` and `restart` succeed only after the API and local models report `ready`; `stop` succeeds after systemd reports `inactive`, or reports `forced=true` when a stuck worker was killed and the unit reached `failed` with no remaining main process.

Never stop or restart the whole service implicitly during conversion. File2MD keeps one supervised model worker resident: it loads models during service startup and serves serialized jobs without reloading. An idle EP-thread change is applied inside the same worker and must not reload models. Replace the worker only after cancellation, a fatal native error, OOM/TCM failure, confirmed-stall auto-termination, or a model/provider configuration change. A suspected stall remains observable; only the explicit per-job cancel endpoint terminates its worker by default. Automatic termination after confirmed no progress is an administrator opt-in. A service stop or restart terminates every active conversion job; invoke it only when the user requests it. Report `PRIVILEGE_REQUIRED` with the exact restricted systemctl permission required when sudo is unavailable.

## Bundled scripts

Use the deterministic wrapper rather than reconstructing local `curl` / `shutil` logic in every task:

```text
sudo python3 scripts/file2md.py ensure-runtime
sudo python3 scripts/file2md.py ensure-runtime --no-update
sudo python3 scripts/file2md.py ensure-runtime --deb-source /path/to/file2md_riscv64.deb
python3 scripts/file2md.py service status
sudo python3 scripts/file2md.py service start
sudo python3 scripts/file2md.py service stop
sudo python3 scripts/file2md.py service restart
python3 scripts/file2md.py convert input.pdf
python3 scripts/file2md.py convert input.pdf --output-dir /path/to/result-root
python3 scripts/file2md.py convert input.pdf --flowchart --image-caption --output-dir /path/to/result-root
```

The wrapper uses `subprocess` to drive local `apt-get` / `dpkg` / `systemctl` / `journalctl` / `curl` directly. The input is staged under `/tmp/file2md-skill-<pid>-<name>` and the result ZIP under `/tmp/file2md-result-<job-id>.zip`; both staging files are removed after the result directory is populated. Override the API endpoint with `FILE2MD_WEB_HOST` / `FILE2MD_WEB_PORT` / `FILE2MD_API_BASE` only when the service listens on a non-default address.
