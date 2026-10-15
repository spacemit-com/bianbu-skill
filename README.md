# Bianbu Skills

SpacemiT APC（Agent Power Cloud）上公开发布的 **Skill** 资源的只读镜像仓库。

本仓库不是 Skill 的开发地：`skills/` 下的内容按 APC 发布包原样解包，
目录名等于 APC 的 `name`，未做任何改写、翻译或裁剪。
若需修改某个 Skill，请在它自己的源仓库修改并重新发布。

## 内容清单

当前镜像 APC 目录快照 `catalog_sha256`：

```text
0846d739bbf9916abaddfd95a63836d387ed02ee58f463961c5f13673ae63af5
```

共 11 个 Skill，每个取 APC 上的最新版本；导出于 2026-10-15。

| Skill | 版本 | 中文名 | 用途 | 标签 |
| --- | --- | --- | --- | --- |
| [`bianbu-media-apps`](skills/bianbu-media-apps/) | `v0.0.3` | 多媒体应用使用与测试 | 使用或测试 Bianbu 桌面的 MPV、VLC、Totem 和 Snapshot（相机）应用。 | `devtools`, `media`, `official` |
| [`cpu-compress-benchmark`](skills/cpu-compress-benchmark/) | `v1.0.1` | CPU解压缩性能基准 | 当用户需要在本机对 CPU 压缩/解压缩性能（吞吐、压缩比、内存占用）做基准测试并生成结构化报告时使用。 | `devtools`, `official` |
| [`k3-media-pipeline`](skills/k3-media-pipeline/) | `v1.0.2` | K3 媒体处理流水线 | 在 K3 板卡上使用 GStreamer 或 FFmpeg 查看媒体信息，执行视频播放、硬件编解码、… | `devtools`, `media`, `official` |
| [`markdown-maker`](skills/markdown-maker/) | `v1.0.5` | 文档转 Markdown | 在 Bianbu riscv64 设备上通过本地 File2MD 运行时把 PDF、PPTX、Word… | `devtools`, `documents`, `official` |
| [`riscv-porter`](skills/riscv-porter/) | `v1.0.1` | RISC-V 移植助手 | 把有源码的 x86_64 / ARM / AArch64 项目迁移到 SpacemiT… | `devtools`, `official` |
| [`spacemit-k-stability`](skills/spacemit-k-stability/) | `v0.1.2` | K 系列稳定性测试 | 在 SpacemiT K 系列开发板上运行和监管稳定性测试。 | `devtools`, `official` |
| [`spacemit-modelzoo-benchmark`](skills/spacemit-modelzoo-benchmark/) | `v2.0.2` | ModelZoo 性能验证 | 在进迭时空 SpaceMIT K 系列设备上完整编排官方 ModelZoo 性能验证；自动识别芯片… | `devtools`, `official` |
| [`using-apm`](skills/using-apm/) | `v1.5.0` | APM 使用手册 | 在用户需要查找、安装、更新、卸载、创建、校验或上传 Bianbu/SpaceMIT（进迭时空）Power… | `devtools`, `official` |
| [`using-coremark`](skills/using-coremark/) | `v1.0.1` | CoreMark 性能测试 | 在 Bianbu 或其他 riscv64 Linux 系统上安装、运行 CoreMark 性能测试，报告或对比… | `devtools`, `official` |
| [`vibe-coder`](skills/vibe-coder/) | `v0.1.1` | 离线 HTML 应用生成 | 在当前工作目录内根据自然语言生成、修改并校验可直接运行的离线 HTML/CSS/JavaScript 应用… | `devtools`, `official` |
| [`vpu-benchmark`](skills/vpu-benchmark/) | `v0.13.14` | VPU 硬件编解码基准 | 测试 SpacemiT K3 VPU 硬件视频编解码器的基准性能、FPS、吞吐和 MVX 带宽， 支持已注册的… | `devtools`, `official` |

每个 Skill 的权威说明是它自带的 `skill-card.md`（能力、使用场景、输入输出、依赖、
限制、维护者）；`SKILL.md` 是给 Agent 读取的执行指引。本表只做索引。

## 安装使用

推荐用 APM 从 APC 安装，这样可以拿到版本管理与本地 Agent 落地的完整流程：

```sh
# 搜索可用 Skill
apm search vpu --type skill

# 查看详情（不带版本即最新版）
apm show vpu-benchmark --type skill

# 安装到指定 Agent；--agent all 表示所有已支持的 Agent
apm install vpu-benchmark --type skill --agent bibit

# 查看已安装资源
apm list --installed --agent bibit
```

也可以直接把本仓库的目录复制进目标 Agent 的 skills 目录，
Skill 是唯一在“发布目录”和“Agent 安装目录”下布局完全一致的类型：

```sh
# 用户级安装
cp -a skills/vpu-benchmark ~/.bianbu-agent/skills/vpu-benchmark

# 项目级安装
mkdir -p .bianbu-agent/skills
cp -a skills/vpu-benchmark .bianbu-agent/skills/vpu-benchmark
```

复制后可用本仓库自带的上游校验工具确认格式未被破坏：

```sh
apm validate skills/vpu-benchmark --type skill
```

## 目录结构

```text
.
├── README.md          本文件：清单与使用说明
├── SOURCES.md         溯源表：版本、发布时间、大小、MD5、下载地址
├── LICENSE            Apache-2.0
└── skills/
    ├── bianbu-media-apps/
    ├── cpu-compress-benchmark/
    ├── k3-media-pipeline/
    ├── markdown-maker/
    ├── riscv-porter/
    ├── spacemit-k-stability/
    ├── spacemit-modelzoo-benchmark/
    ├── using-apm/
    ├── using-coremark/
    ├── vibe-coder/
    ├── vpu-benchmark/
```

## 更新与维护

`skills/` 下的文件是 APC 发布产物的副本，**不要手工编辑**：

1. 重新导出：从 APC 目录取各 Skill 的最新版本，校验 `content_md5` 后解包。
2. 更新 `SOURCES.md` 的版本、发布时间、大小、MD5 与下载地址。
3. 更新本文件的内容清单表。
4. 逐目录执行 `apm validate <dir> --type skill`，全部通过后再提交。

历史版本不在本仓库内：APC 只保留每个 `name` 的最新版本条目，
需要旧版本时按 `apm install <name>=<version>` 指定版本安装，
或按 `SOURCES.md` 记录的 CDN 地址规则取对应归档。

## 范围与许可

- 本仓库只镜像 APC 的 **skill** 类别；Plugin、MCP、Agent 不在范围内。
- 版权归各 Skill 维护者所有，许可为 Apache-2.0，见 [LICENSE](LICENSE)；
  各 Skill 的维护者在 `skills/<name>/skill-card.md` 的 Maintainer 段列出。
- `riscv-porter` 与 `vibe-coder` 的发布包自带 `LICENSE`/`README.md`，已原样保留。
