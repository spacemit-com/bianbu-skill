# Error classification and remediation

Normalize the raw job error, logs, journal output, and service exit state into these codes:

| Code | Detection | Remediation |
|---|---|---|
| `RUNTIME_NOT_INSTALLED` | package/service/API absent | install the pinned `.deb`; check sudo and architecture |
| `PRIVILEGE_REQUIRED` | dpkg/installer, or a lifecycle command, needs root | run with sudo or ask an administrator to install; grant narrowly scoped systemctl permission for lifecycle operations |
| `APT_UPDATE_FAILED` | `apt-get update` fails during `ensure-runtime` | check network and APT sources; confirm the device is riscv64; pass `--deb-source` for an offline install |
| `APT_INSTALL_FAILED` | `apt-get install file2md` fails and sudo was not the cause | confirm sudo permission; confirm the APT source carries a riscv64 `file2md`; check dependencies and disk space |
| `PACKAGE_NOT_FOUND` | the `--deb-source` path does not exist | provide a path to a riscv64 `.deb` on the local filesystem |
| `PACKAGE_INSTALL_FAILED` | `dpkg -i` of a supplied `.deb` fails | confirm sudo permission, that the `.deb` is riscv64, and that dependencies and disk space are sufficient |
| `LOCAL_COMMAND_NOT_FOUND` | a required binary (`curl`/`systemctl`/`dpkg`/`apt-get`/`journalctl`) is missing | install the missing binary; check `PATH` |
| `LOCAL_COMMAND_TIMEOUT` | a local wrapper command exceeds its timeout | retry after the device is responsive; inspect stuck jobs or an unattended sudo prompt |
| `MODEL_LOAD_FAILED` | model/session/ONNX load error | verify model files, disk space, checksum; rerun runtime installer |
| `MODEL_NOT_READY` | `/api/models` is loading/degraded | wait, inspect service logs, then restart/preload |
| `MODEL_PREPARE_FAILED` | idle resident worker cannot apply the requested EP thread count | ensure no conversion is active; inspect the worker/TCM diagnostics; normal changes are hot-applied and only an unhealthy worker enters cold recovery |
| `LIBREOFFICE_NOT_FOUND` | executable absent | install LibreOffice Writer/Impress/Calc |
| `LIBREOFFICE_CONVERSION_FAILED` | Office conversion error | retry with a private temp profile; inspect fonts/permissions |
| `INVALID_DOCUMENT` | the container cannot be read at all (PDFium `Data format error`, a renamed or truncated file) | the input is damaged or its contents do not match the extension; confirm extension vs content, re-export from the original application, and re-download if it came from a network drive or chat tool |
| `INVALID_XLSX` | a valid ZIP that lacks required parts (`[Content_Types].xml`, `xl/workbook.xml`, or the worksheet parts) | confirm extension vs content; re-export from Excel or LibreOffice and retry |
| `INVALID_FILE_SIGNATURE` | local preflight rejects the container before upload (damaged OOXML, missing XLSX parts, structural parse failure) | confirm extension vs content; re-export from the original application and retry |
| `CONVERSION_FAILED` | conversion raised and no more specific code matched | inspect the job's full exception in the service log; keep the job id; confirm the input opens in its original application and retry |
| `OCR_FAILED` | OCR/det/rec error | check image quality/language; retry with suitable DPI |
| `TABLE_FAILED` | table model/recognition error | report partial output; retry with clearer input or lower load |
| `FORMULA_FAILED` | formula model/recognition error | report partial output; retry with clearer input or suitable DPI |
| `RECOGNITION_PARTIAL_FAILED` | recognition produced partial or low-confidence output without a stage-specific failure | keep any partial output; retry with a clearer input and lower load |
| `WORKER_OOM_KILLED` | worker raises `MemoryError`, or exits by SIGKILL/137 while the task-scoped kernel OOM counter increases | catchable failures run engine shutdown; after SIGKILL inspect TCM, clear only blocks exclusively owned by the dead worker, verify recovery, report the cleanup result, and never auto-retry the conversion |
| `SPACEMIT_TCM_ACQUIRE_FAILED` | SpaceMIT EP reports `tcm buffer acquire failed` | inspect TCM owners; retry only after the resource is available |
| `TCM_STALE_ALLOCATION` | every busy block owner PID is recorded and no longer exists | ensure no valid EP task remains, clear TCM once, verify all blocks free, retry once |
| `TCM_BUSY` | a busy block has a live owner or its owner cannot be verified | wait; never force-clear an active or unknown owner |
| `TCM_RECOVERY_FAILED` | TCM was cleared but blocks remain busy, the owner still exists, or the clear command itself failed | stop the File2MD inference task, then re-inspect TCM; if blocks stay busy an administrator must clear TCM or restart the device |
| `CONVERSION_STALLED` | no MinerU/page-level callback for the configured threshold, followed by an observation window with no worker CPU/I/O/RSS activity | return stage, silence duration, memory, TCM, worker PID and cancel endpoint; do not terminate by default |
| `CLIENT_WAIT_LIMIT_REACHED` | an optional nonzero skill `--wait` limit expires | report that the server task is still running; continue querying by job id or cancel explicitly |
| `UPSTREAM_OPERATION_TIMEOUT` | MinerU, LibreOffice, ONNX Runtime, or another dependency explicitly reports its own timeout | preserve the dependency error and stage; do not describe it as File2MD's document deadline |
| `FILE2MD_API_STALLED` | API is continuously unresponsive and no more specific cause exists | preserve job id and diagnostics; inspect the supervised worker |
| `FILE2MD_SERVICE_RESTARTED` | service PID/restart count changes after job submission | inspect task-scoped journal for OOM/native crash, then resubmit after ready |
| `API_INVALID_RESPONSE` | a File2MD API response is not valid JSON, or is JSON that is not an object | inspect `file2md.service` logs; compare the installed package version with the API contract |
| `FORMULA_RESULT_NOT_CACHED` | completed XLSX job has formula `<f>` without cached `<v>` because recalculation was disabled | result was generated from the original; warn that affected formula values may be empty, enable recalculation or save in Calc/Excel and retry |
| `FORMULA_CACHE_RECALC_FAILED` | completed XLSX job could not run/finish/verify LibreOffice recalculation | result was generated from the original; report affected cells and raw cause, inspect LibreOffice/profile permissions, or save manually and retry |
| `LIBREOFFICE_RECALC_FAILED` | older skill fallback could not recalculate the temporary XLSX | continue with the original and emit `FORMULA_CACHE_RECALC_FAILED`; never modify the original |
| `UNSUPPORTED_FORMAT` | suffix/signature/container rejected | convert to PDF or use a supported format |
| `INPUT_NOT_FOUND` | the local input path does not exist | provide an existing local file |
| `FILE_TOO_LARGE` | exceeds configured upload limit | reduce/compress/split input |
| `UPLOAD_FAILED` | submitting the document to File2MD failed | check that the service is available, and the disk space and upload size limit |
| `OUTPUT_MISSING` | completed job has no Markdown in ZIP | keep ZIP, inspect service logs and output storage |
| `MARKDOWN_EMPTY` | the job completed but the Markdown body is empty | confirm the source has recognizable content; inspect the recognition log and retry |
| `OUTPUT_ARCHIVE_INVALID` | a result ZIP member path escapes the output directory | keep the ZIP for diagnosis and do not extract it |
| `OUTPUT_DOWNLOAD_FAILED` | the result ZIP could not be downloaded | keep the job id; re-download after the service is ready |
| `SERVICE_UNREACHABLE` | API disappears during job | check systemd status/journal; distinguish restart/OOM from network failure |
| `SERVICE_START_FAILED` / `SERVICE_STOP_FAILED` / `SERVICE_RESTART_FAILED` | systemctl lifecycle command fails | inspect systemd/journal and the command's stderr |
| `SERVICE_STOP_TIMEOUT` | service does not become inactive before the wait limit | inspect workers and systemd stop timeout |

Always return the stable code, Chinese summary, stage, root cause, raw error, retryable flag, and recommended next action. Scan logs only from the job submission timestamp so historical OOM events do not contaminate classification.

## Keeping this table complete

The runtime never reads this file: `SkillError.payload()` resolves the message from `ERROR_MESSAGES` and
the remediation from `ERROR_REMEDIATION`, falling back to `GENERIC_REMEDIATION` for any code that has no
entry. This table exists so an agent can explain a failure without reading the source, so every code the
client can emit must appear here — otherwise the reader finds no entry for the code in the payload and
falls back to generic advice.

When adding a code to `scripts/file2md.py`, add its row here in the same change. To list the gap:

```python
import re
client = open("scripts/file2md.py", encoding="utf-8").read()
doc = open("references/error-remediation.md", encoding="utf-8").read()
raised = set(re.findall(r'SkillError\(\s*"([A-Z_]+)"', client))
tabled = set(re.findall(r'^    "([A-Z_]+)":', client, re.M))
documented = set(re.findall(r'`([A-Z_]+)`', doc))
print(sorted((raised | tabled) - documented))
```
