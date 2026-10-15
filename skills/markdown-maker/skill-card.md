---
schema_version: 2
---
# Skill Card: markdown-maker

## Capability

Convert local PDF, PPTX, Word, XLSX, PNG, JPG, and other supported documents to Markdown on a Bianbu riscv64 device through the local File2MD runtime, including the surrounding service lifecycle, model readiness, file validation, job submission, failure diagnosis, and ZIP result extraction.

## Use Cases

Use when a task needs offline document conversion, File2MD service start / stop / restart / status control, local quantized-model status, file validation, progress and error reporting, ZIP result extraction, or a saved Markdown path. Triggered by requests such as "把这个 PDF 转成 Markdown" / "convert this document to Markdown" / "把这份 PPT 转成 Markdown" with no cloud upload of source or result.

## Inputs and Outputs

Input:
- SSH host, user, and password or preconfigured SSH agent (`FILE2MD_SSH_HOST` may override the host).
- A local input file with a supported suffix (PDF, PPT/PPTX, DOC/DOCX, XLS/XLSX, PNG/JPG/JPEG, ...), regular file, size ≤ server upload limit (default 100 MiB), signature matching the suffix.
- Optional output directory (`--output-dir`); default `~/File2MD/<source-stem>-<job-id>/` on the machine running the skill.

Output:
- Absolute path to the extracted Markdown file.
- An `images/` directory when present.
- Original filename, byte size, validation result, route, processing status, model-load seconds, elapsed seconds, page count, and PDF seconds per page when the API exposes them.

## Dependencies

- `file2md` Debian package for `riscv64` (installed on first use via `apt-get` or a supplied `.deb`).
- `file2md.service` managed by systemd; `systemctl` access for the SSH user (sudo or already-granted rule).
- LibreOffice for PPT/DOC and similar Office formats.
- A reachable SSH target with the chosen authentication; never hard-code device addresses inside the skill.
- Local network for first-time package/model install; conversion itself runs offline once the runtime and models are ready.

## Limitations

- Submit only local files to `POST /api/jobs`; never call the URL conversion endpoint.
- Never write passwords into the skill or any file; prefer SSH key/agent for published deployments.
- Never stop or restart `file2md.service` implicitly during a conversion; only do so when the user requests or explicitly asks to release a stuck File2MD task.
- Do not claim success on `<2s` model-load or `<5s/page` PDF targets without measurements from the API.
- OOM, OCR / table / formula failures, conversion timeouts, and missing outputs require the structured remediation in `references/error-remediation.md`; preserve partial results and ZIP for diagnosis.
- Performance numbers are measured values, not promises; report them as observed, not guaranteed.

## Maintainer

Owner: huangjingtao
Contact: jingtao.huang@spacemit.com
