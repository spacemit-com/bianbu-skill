# 溯源表

本表由 APC 目录快照生成，用于核对 `skills/` 内容与 APC 发布产物是否一致。

- 数据来源：APC 公开查询接口（`GET /resources/version` → `GET /resources`）
- 目录快照 `catalog_sha256`：`0846d739bbf9916abaddfd95a63836d387ed02ee58f463961c5f13673ae63af5`
- 目录快照大小：60091 字节
- 选取口径：每个 skill 的最新版本
- 导出日期：2026-10-15

| Skill | 版本 | 发布时间 | 字节 | 归档 MD5 | 下载地址 |
| --- | --- | --- | --- | --- | --- |
| `bianbu-media-apps` | `v0.0.3` | 2026-09-29T15:03:17 | 47700 | `72d81721272bea355d838aa14f2b8161` | [CDN](https://cdn-resource.spacemit.com/file/apc/resource/skill/bianbu-media-apps-2-v0.0.3.tar.gz) |
| `cpu-compress-benchmark` | `v1.0.1` | 2026-09-30T14:10:07 | 24924 | `c271a9fa93d3f4283d348e484e4c973a` | [CDN](https://cdn-resource.spacemit.com/file/apc/resource/skill/cpu-compress-benchmark-2-v1.0.1.tar.gz) |
| `k3-media-pipeline` | `v1.0.2` | 2026-09-29T15:05:34 | 19626 | `4a04a91f67853274302e3631e50da423` | [CDN](https://cdn-resource.spacemit.com/file/apc/resource/skill/k3-media-pipeline-2-v1.0.2.tar.gz) |
| `markdown-maker` | `v1.0.5` | 2026-10-08T15:30:25 | 28582 | `a65b7e31c1c9f217a27424676f5de7c6` | [CDN](https://cdn-resource.spacemit.com/file/apc/resource/skill/markdown-maker-2-v1.0.5.tar.gz) |
| `riscv-porter` | `v1.0.1` | 2026-09-29T14:46:04 | 16047 | `fbc4615110846739779f916a58831c80` | [CDN](https://cdn-resource.spacemit.com/file/apc/resource/skill/riscv-porter-2-v1.0.1.tar.gz) |
| `spacemit-k-stability` | `v0.1.2` | 2026-09-29T15:02:58 | 21982 | `d03c96671f18208ce3ba834b4bf7dd77` | [CDN](https://cdn-resource.spacemit.com/file/apc/resource/skill/spacemit-k-stability-2-v0.1.2.tar.gz) |
| `spacemit-modelzoo-benchmark` | `v2.0.2` | 2026-09-29T15:03:53 | 28967 | `0fb7b530cb0984276d1bcaa7ed2d6083` | [CDN](https://cdn-resource.spacemit.com/file/apc/resource/skill/spacemit-modelzoo-benchmark-2-v2.0.2.tar.gz) |
| `using-apm` | `v1.5.0` | 2026-09-30T11:27:49 | 19494 | `ef914b820ade4c646d6140d20e54d395` | [CDN](https://cdn-resource.spacemit.com/file/apc/resource/skill/using-apm-2-v1.5.0.tar.gz) |
| `using-coremark` | `v1.0.1` | 2026-10-12T14:18:20 | 8592 | `1a4fe4f5b2ab0f04aa06c90c35d0e02f` | [CDN](https://cdn-resource.spacemit.com/file/apc/resource/skill/using-coremark-2-v1.0.1.tar.gz) |
| `vibe-coder` | `v0.1.1` | 2026-09-29T14:47:22 | 8431 | `ed6a7b058408fec038573a452646b61f` | [CDN](https://cdn-resource.spacemit.com/file/apc/resource/skill/vibe-coder-2-v0.1.1.tar.gz) |
| `vpu-benchmark` | `v0.13.14` | 2026-09-29T15:04:12 | 39225 | `84d628622e60e2ea4837ee7c3efce157` | [CDN](https://cdn-resource.spacemit.com/file/apc/resource/skill/vpu-benchmark-2-v0.13.14.tar.gz) |

## 校验方法

按上表地址下载归档后：

```sh
# 归档自身与 APC 声明的 MD5 一致
md5sum <name>-<version>.tar.gz

# 解包结果与仓库内容一致
mkdir -p /tmp/apc-check && tar xzf <name>-<version>.tar.gz -C /tmp/apc-check
diff -r /tmp/apc-check skills/<name>
```

## 各 Skill 维护者

内容取自各 `skills/<name>/skill-card.md` 的 Maintainer 段，仅作索引。

| Skill | 维护者 |
| --- | --- |
| `bianbu-media-apps` | wumingjie <mingjie.wu@spacemit.com> |
| `cpu-compress-benchmark` | liangjunzhao <junzhao.liang@spacemit.com> |
| `k3-media-pipeline` | wumingjie <mingjie.wu@spacemit.com> |
| `markdown-maker` | huangjingtao <jingtao.huang@spacemit.com> |
| `riscv-porter` | dec <decheng.liu@spacemit.com> |
| `spacemit-k-stability` | fuqiang <qiang.fu@spacemit.com> |
| `spacemit-modelzoo-benchmark` | fuqiang <qiang.fu@spacemit.com> |
| `using-apm` | liangjunzhao <junzhao.liang@spacemit.com> |
| `using-coremark` | liangjunzhao <junzhao.liang@spacemit.com> |
| `vibe-coder` | dec <decheng.liu@spacemit.com> |
| `vpu-benchmark` | wumingjie <mingjie.wu@spacemit.com> |
