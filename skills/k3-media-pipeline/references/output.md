# 输出结构

## 统一信封

所有场景（SUCCESS / FAILED / DRY_RUN / 参数错误）返回同一组 17 字段的 JSON，
不适用的字段为 `null`：

| 字段 | 说明 |
|---|---|
| `status` | SUCCESS / FAILED / DRY_RUN |
| `scenario` | 场景名；无法识别时为 null |
| `backend` | gstreamer / ffmpeg / ffprobe / null |
| `pipeline` | 数据流描述（如 "文件 → qtdemux → h264parse → spacemitdec(硬件解码) → glsinkbin(gtkglsink) → 显示"） |
| `pipeline_stages` | 实际使用的组件顺序列表（语义见下） |
| `commands` | 实际执行的完整命令 |
| `input` / `output` / `target_url` | 输入路径 / 产物路径 / 推流目标 |
| `streams` | 并发路数 |
| `duration_seconds` | 本次执行时长 |
| `processes` | 进程详情：pid、returncode、ok、elapsed_seconds、stderr_tail（仅失败时保留） |
| `output_bytes` | 产物大小 |
| `output_media_info` | 产物 ffprobe 复检结果（编码/分辨率/时长） |
| `media_info` | `media-info` 场景的探测结果 |
| `error_code` | 失败原因代码；成功为 null |
| `summary` | 面向用户的中文总结（Agent 优先展示此字段） |

## pipeline_stages 语义

从实际命令机械提取，保证与真实执行一致：

- **GStreamer**：按 `!` 分组的元件链，含属性：`filesrc(location=/a.mp4)`、
  `capsfilter(video/x-raw,framerate=30/1)`、`glsinkbin(sink=gtkglsink)`；
  tee 分支引用（如 `t.`）单独成段
- **FFmpeg**：语义段 `input(...) → decode(...) → filter(...) → encode(...) →
  mux(...) → output(...)`；`-c:v copy` 标为 `stream-copy`，`-f null -` 标为
  `output(null)`
- **ffprobe**：`["ffprobe"]`

## 错误码

| 错误码 | 含义 |
|---|---|
| `INVALID_REQUEST` | 参数缺失/非法/未知 |
| `INPUT_NOT_FOUND` | 文件/目录/摄像头设备不存在 |
| `INPUT_MISMATCH` | 输入实际编码或分辨率与请求不符 |
| `INPUT_PROBE_FAILED` | 文件或 RTSP 流无法识别 |
| `CODEC_UNSUPPORTED` | 非 H.264/H.265 |
| `CONTAINER_UNSUPPORTED` | GStreamer 播放不支持的容器 |
| `OUTPUT_EXISTS` | 输出文件已存在（不覆盖） |
| `OUTPUT_INVALID` | 执行结束但产物缺失/为空/无法识别 |
| `DURATION_MISMATCH` | 录像实际时长与请求不符 |
| `PROGRAM_UNAVAILABLE` | ffmpeg/ffprobe/gst-launch 缺失 |
| `HARDWARE_CODEC_UNAVAILABLE` | FFmpeg 未提供所需硬件编解码器 |
| `GSTREAMER_ELEMENT_UNAVAILABLE` | 所需 GStreamer 元件不可用 |
| `PROCESS_FAILED` | 进程执行失败（详见 processes[].stderr_tail） |

## 退出码

- `0`：SUCCESS 或 DRY_RUN
- `1`：执行失败（status=FAILED）
- `2`：请求/校验错误（status=FAILED 且 error_code 为请求类错误）
