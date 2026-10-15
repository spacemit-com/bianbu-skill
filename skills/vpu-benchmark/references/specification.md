# Benchmark specification

The runner accepts JSON only and rejects unknown fields.

```json
{
  "version": 1,
  "name": "h264-1080p-encode",
  "operation": "encode",
  "codec": "h264",
  "device": "auto",
  "input": "/tmp/vpu-1080p.yuv",
  "output": "/tmp/vpu-1080p.264",
  "width": 1920,
  "height": 1080,
  "frames": 60,
  "fps": null,
  "sessions": 1,
  "warmup_iterations": 1,
  "profiling": false,
  "measure_ddr": true,
  "ddr_baseline_seconds": 2.0,
  "ddr_capacity_mbps": null,
  "min_fps": null,
  "baseline_fps": null,
  "baseline_result": null,
  "overwrite": true,
  "timeout_seconds": 600,
  "result_path": "./h264-1080p-encode-result.json",
  "report_path": "./h264-1080p-encode-result.md"
}
```

## Fields

- `name`: lowercase letters, digits, `_`, and `-`; maximum 64 characters.
- `operation`: `encode` or `decode`.
- `codec`: `h264`, `h265`, `vp8`, `vp9`, or `mjpeg`. VP8/VP9/MJPEG currently permit single-session only.
- `device`: `auto` or an existing `/dev/videoN` whose driver is `mvx`. Node numbers are not stable identifiers. `auto` remains stored as `auto` in the Spec and rescans V4L2 nodes during every validate, compile, and run operation; reports record the actual `resolved_device` used for that run.
- `input`: existing local file. Encode expects raw I420; decode expects an elementary H.264/H.265 stream.
- `output`: required for single-session encode; optional for single-session decode; forbidden for multi-session runs.
- `width` and `height`: required positive even integers for encode. Decoder obtains dimensions from the stream.
- `frames`: optional positive frame limit. Zero or null processes the complete input.
- `fps`: optional paced rate. Omit for maximum throughput. Required when `profiling` is true.
- `sessions`: 1 through 32. Values greater than one select the multi-session tool.
- `warmup_iterations`: 0 through 20, default 1 in the advanced interface. The default regression suite sets this to 1 for single-session cases and 0 for multi-session cases. Warmup runs are retained under `details.warmup_runs` and excluded from formal metrics.
- `warmup_frames`: optional positive frame limit for FPS warmup, capped at the formal frame limit when specified. The default regression suite uses 30 frames for single-session warmup. Omitting this field in the advanced interface retains the formal frame limit for warmup.
- `profiling`: enables MVX bus profiling for a single-session paced run.
- `measure_ddr`: opens `/dev/ddr_perf` as the invoking user, samples all reported AXI ports every 50 ms, and subtracts an adjacent idle baseline. It works for single- and multi-session VPU runs and does not require `fps`. Samples containing the `0xFFFFFFFF` saturation sentinel are excluded and reported as `invalid_samples`.
- `ddr_baseline_seconds`: adjacent idle baseline duration from 0.2 through 60 seconds; default 2 seconds.
- `ddr_capacity_mbps`: optional platform DDR capacity used only to calculate incremental utilization percentage.
- `min_fps`: optional acceptance threshold applied after MVX completes.
- `baseline_fps`: optional comparison baseline. It produces FPS delta, percentage delta, ratio, and comparison status but does not change pass/fail by itself.
- `baseline_result`: baseline JSON for the same component. Both result and scalar baselines are compared numerically; environment and input consistency are not checked.
- `overwrite`: permits replacement of output and result files.
- `timeout_seconds`: process timeout from 1 through 3600 seconds.
- `result_path`: JSON report path; defaults to `<name>-result.json` in the current directory.
- `report_path`: Markdown report path; defaults to the result path with `.md` suffix. It is generated from the JSON result.

## Tool mapping

| Operation | Sessions | Binary |
|---|---:|---|
| Encode | 1 | `mvx_encoder` |
| Encode | 2–32 | `mvx_encoder_multi` |
| Decode | 1 | `mvx_decoder` |
| Decode | 2–32 | `mvx_decoder_multi` |

The Skill does not contain executable binaries. All four commands must be supplied through `PATH` by the Debian package `k3x-vpu-test`. Before creating a benchmark result directory, the portable entrypoint checks the complete command set. If commands are missing, it makes one non-interactive installation attempt with `sudo -n apt-get install -y k3x-vpu-test` (or direct `apt-get` when already root). If installation is unavailable, fails, or times out, it stops before the workload and tells the user to install `k3x-vpu-test` or a local `k3x-vpu-test_*.deb` manually. It never prompts for a sudo password or downloads a DEB from an unspecified source. The board still requires the MVX kernel driver and V4L2 device nodes.

H.264 is the MVX default. H.265 maps to `-o hevc` for encode and `-i hevc` for decode. VP8/VP9 use `-f ivf` and `-o vp8/vp9` or `-i vp8/vp9`. MJPEG uses `-f raw` with the MVX format name `jpeg`. H.264/H.265 use raw elementary streams. VP8/VP9 outputs use .ivf; MJPEG uses .mjpg/.mjpeg. The common single-session profiling helper uses the same mapping.

## Metrics

- `mvx_status`: parsed from `[Test Result] MVX Encode/Decode PASS`.
- `average_fps`: parsed from `Average Framerate`.
- `throughput_equivalent_ms_per_frame`: `1000 / average_fps`; not end-to-end latency.
- `cpu_percent`: child user+system CPU time divided by wall time. Values may exceed 100% for multi-threaded work.
- `peak_rss_kib`: maximum resident set reported for the benchmark child process.
- `resources.ddr_bandwidth`: when `measure_ddr=true`, includes `/dev/ddr_perf` baseline, formal system-wide traffic, baseline-subtracted incremental bandwidth, sampling ports, p95/peak observations, and optional utilization. The counters are not tagged by VPU master and another reader must not run concurrently.
- `details.mvx_profiling_bandwidth`: when profiling is enabled, parses `avg_write_bw` and `avg_read_bw` from the MVX kernel record and multiplies by requested `fps`. When both methods are active, `/dev/ddr_perf` is the canonical resource value and MVX profiling is retained as supporting evidence.
- `baseline_comparison`: comparison against `baseline_fps`, with `delta_fps`, `delta_percent`, `ratio`, and `status` (`above`, `equal`, or `below`).
- `threshold_status`: `not_configured`, `pass`, or `fail`, independent from `mvx_status`.

## Standard output

Every result uses the common Benchmark Result interface. `summary` is the compact view; full MVX evidence remains under `details`:

```json
{
  "schema": "k3-benchmark-result",
  "schema_version": 3,
  "component": "vpu",
  "provider": "vpu-benchmark",
  "ok": true,
  "benchmark": {"name": "vpu-benchmark", "version": "0.13.12", "run_id": "..."},
  "status": {"execution": "passed", "acceptance": "passed", "evidence": "complete"},
  "environment": {"board_model": "..."},
  "sampling": {"warmup": {"iterations": 1, "excluded_from_formal": true}, "formal": {}},
  "workload": {"operation": "decode", "codec": "h265", "sessions": 8},
  "measurement": {"scope": "mvx-native-report", "rate_unit": "frames_per_second", "measured_rate_per_second": 112.84},
  "capacity": {"measured_rate_per_second": 112.84, "planning_rate_per_second": 112.84, "rate_unit": "frames_per_second"},
  "resources": {"cpu_percent": 23.5, "peak_rss_bytes": 12641280, "ddr_bandwidth": null},
  "thresholds": {"status": "not_configured", "minimum_rate_per_second": null, "passed": true},
  "summary": {
    "status": "pass",
    "measured_rate_per_second": 112.84,
    "planning_rate_per_second": 112.84,
    "rate_unit": "frames_per_second",
    "latency_ms_per_operation": 8.8621
  },
  "artifacts": {"report": "..."}, "limitations": [], "details": {}
}
```

## Reference results

The default suite uses the K3 product specification at 4 cores @ 1 GHz as its FPS reference for the existing registered cases. No new codec or session-count case is inferred from that specification. Existing MVX bandwidth baselines remain measured values.

| Scenario | Reference result |
|---|---:|
| H.264 4K encode | 124.53 fps |
| H.265 4K encode | 104.44 fps |
| H.264 1080p 12-session encode | 30 fps product target per session |
| H.265 1080p 12-session encode | 30 fps product target per session |
| H.264 4K decode | 196.28 fps |
| H.265 4K decode | 219.55 fps |
| H.264 1080p 22-session decode | 38.60 fps; reserved-memory limited |
| H.265 1080p 24-session decode | 35.94 fps |

Reference bandwidth totals use `(avg_write_bw + avg_read_bw) × fps`: H.264 4K60 encode 2170 MB/s, H.264 4K60 decode 2019 MB/s, H.264 1080p30 encode 205 MB/s, H.265 1080p30 encode 186 MB/s, H.264 1080p30 decode 230 MB/s, and H.265 1080p30 decode 163 MB/s.

Power measurements require external current/voltage instrumentation. This version does not automate or infer them.

## Portable execution contract

Invoke `[python3, <installed-skill-root>/scripts/run.py, --request-json, <JSON>]`, using an absolute path resolved by the host. Optional filters are codec (h264/h265/vp8/vp9/mjpeg), operation (encode/decode), sessions (integer 1..32), resolution (4k/1080p). Empty input or {} selects all 13 registered cases. Omitted fields impose no constraint. Unknown fields, invalid values and zero matches fail before any workload starts; no fallback to all cases and no creation of new cases. `--describe` returns JSON Schema without running a workload. A no-argument invocation starts defaults immediately and never waits for stdin EOF. For compatibility, already-available stdin JSON is accepted, but new hosts should use `--request-json`.

Example: `{"codec":"h264","operation":"decode","sessions":1}` selects only the registered H.264 4K decoder case. `{"codec":"h264","operation":"decode","resolution":"1080p","sessions":1}` fails because that case is not registered. request.json records filters and selected IDs; results contain only selected cases. The entrypoint resolves siblings relative to its own file and does not depend on the working directory or any specific agent framework. Hardware execution still requires the supported Linux board, `k3x-vpu-test`, MVX driver/device nodes, and FFmpeg hardware codecs.

Capture UTF-8 stdout and stderr separately and drain stderr while waiting. Stdout contains exactly one final Markdown report; stderr carries progress JSONL and diagnostics. The host must render stdout verbatim as the final answer, including on nonzero exit, and skip model summarization. Prompt instructions alone cannot enforce this host behavior.

Successful/benchmark-FAIL output is the regression JSON `display_markdown`: fixed performance table, explanations, version snapshot and report path. Startup errors and timeout use fixed headings: VPU Benchmark, status, test versions, performance results, exception and log directory; unavailable metrics are never fabricated. Raw child stdout is retained under the per-invocation `entry-*` state directory, and the host should retain stderr. Detailed suite JSON and Markdown remain under that directory.

Exit codes: 0 = completed (PASS/WARN/MEASURED); 1 = benchmark execution or performance FAIL with report; 2 = invalid invocation/preparation/protocol error; 124 = 1500-second timeout; 130 = keyboard interruption. The wrapper terminates its workload process group on timeout/interruption. Hosts should allow at least 1510 seconds, must not blindly retry nonzero exits, and should send SIGINT to the entrypoint for graceful cancellation. SIGKILL, machine power loss, or a host's earlier timeout cannot guarantee a final report; in that case the host must stop the process tree and display a fixed execution-interrupted message, never infer success or ask the model to invent results.

No new host adapter or runtime-specific manifest is required. Direct calls to advanced `regression.py`/`benchmark.py` retain their existing CLI contracts; this contract is for `scripts/run.py`.

## Default asset and regression suite

The default suite is for requests that do not specify a workload. Media binaries are not stored in the Skill. `scripts/assets.py ensure` downloads the source declared in `asset-manifest.json` and prepares the cached 1920×1080, 25 fps, 200-frame I420, H.264, and H.265 files with the K3 FFmpeg stcodec hardware decoder/encoders. The default cache is `~/.local/share/benchmarks/vpu/<asset-set-id>/`.

Cache readiness checks only file existence and nonzero size, including raw input. Cached files are reused without scanning media contents. Missing or empty assets trigger preparation; generation commands must succeed and outputs must be nonempty. Codec, dimensions and frame counts are not verified. `generated.json` records the source URL, transform, and FFmpeg version. This policy does not guarantee content integrity.

`scripts/run.py` runs 13 default cases through `scripts/regression.py`:

- Single-session 3840x2160 H.264/H.265 encode and decode (4 cases).
- Single-session 3840x2160 VP8/VP9/MJPEG encode and decode (6 cases), with the same 200-frame formal input, one excluded 30-frame warmup for each of FPS and bandwidth, and the 4K60 profiling method. Baseline values retain their original three-run calibration; they have not been recalibrated for the shorter warmup.
- 1920x1080 H.264 and H.265 encoding at 12 sessions (2 cases), matching the product specification.
- 1920x1080 H.265 decoding at 24 sessions (1 case).

These are the highest existing validated multi-stream test points, not an automatic maximum-capacity search.
Since v0.13.3, single-session cases run one excluded 30-frame warmup separately for FPS and bandwidth. Multi-session cases skip warmup in both stages. All cases retain their unpaced formal FPS workload and request 200 frames per session for formal testing. Existing baseline values are unchanged; the new warmup policy does not constitute a new calibration. Default FPS workloads do not read /dev/ddr_perf.

Bandwidth is measured separately by `scripts/vpu_mvx_bandwidth.py`, using the document's MVX `--profiling 1` method at 60 FPS per 4K session or 30 FPS per 1080p session. Multi-stream bandwidth launches the actual number of independent single-session tools concurrently. It requires successful channels, at least 95% of target FPS on every channel, at least 90% process-window overlap, and exactly the expected number of distinct MVX profiling session records in the kernel journal. Missing or ambiguous records fail; no single-session extrapolation or ddr_perf fallback is used.

Sum `(avg_write_bytes_per_frame + avg_read_bytes_per_frame) * target_fps / 1000000` across all measured sessions. This is MVX bus demand normalized to the target frame rate, not system-wide DDR traffic or adjacent-idle-subtracted bandwidth. Encode outputs are temporary elementary streams; decoded YUV is not saved. This preserves hardware profiling without introducing large multi-stream YUV files; it does not reproduce the document's CPU/file-output overhead measurement.

Baseline field `mvx_bandwidth_mbps` and per-case `mvx_bandwidth_method`/`mvx_bandwidth_target_fps` keep this method distinct from the optional system DDR diagnostics. Bandwidth baselines are three-run medians under the same method; FPS references are the product-spec values for the existing cases. Each measurement retains independent channel commands/logs, the journal excerpt, counters, FPS and concurrency evidence in `bandwidth.json`. Regression schema version 3 uses `mvx_bandwidth_method`; table labels say MVX bandwidth. The advanced benchmark.py interface documented above still supports optional ddr_perf diagnostics independently of the default suite.
The `4k` variant uses the 3840×2160 H.265 Roast Duck MP4 at `nexus.bianbu.xyz`. On a cache miss it requires HTTP Range support, downloads the first 16 MiB, and FFmpeg stream-copies the first 10 seconds into a temporary MP4. No full-download fallback is used. `source-clip.log` retains FFmpeg read statistics. This is stream copy, not software encoding. The K3 `hevc_stcodec` hardware decoder then prepares 200 I420 frames at 25 FPS, followed by the existing hardware codec generation paths. Only command success and nonempty outputs are checked; no media scan is performed.
The generated raw I420 file is approximately 2.32 GiB; media remains outside the Skill.
The 1080p cache remains unchanged. Each regression run uses its own result directory.

The default suite records board model, OS release, kernel, VPU driver name/version, FFmpeg, Python and Skill versions, and asset-set IDs in JSON and Markdown. MPP is not part of the VPU test-version summary. Environment and asset consistency are not checked and do not gate comparison. Cases with a baseline are compared directly. This also applies to the advanced benchmark.py baseline_result interface. Input metadata records only path, availability, size and modification time; collecting it does not read the file contents.
FPS decline over 5%/10% produces WARN/FAIL; MVX bandwidth increase over 15%/25% produces WARN/FAIL.
A performance warning/failure is repeated twice and classified from the median.
Execution failures are retained as FAIL without automatically repeating them.
An unset baseline produces MEASURED (measurement only), not a passing regression. Default-suite statuses are PASS, MEASURED, WARN and FAIL; WARN/FAIL take priority over MEASURED in the overall result. Missing version metadata is displayed as unavailable, not a failure.
