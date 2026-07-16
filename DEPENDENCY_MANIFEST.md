# 依赖版本清单

## Web GUI

| 依赖 | 版本 |
| --- | --- |
| Node.js | `>= 22.13.0` |
| Next.js | `16.2.6` |
| React | `19.2.6` |
| React DOM | `19.2.6` |
| TypeScript | `5.9.3` |
| ESLint | `9.39.4` |
| eslint-config-next | `16.2.6` |

完整 npm 传递依赖及完整性哈希以 `package-lock.json` 为准。生产 Docker 基础镜像为 `node:22-bookworm-slim`。

## ESO ALPACA 更新器

| 依赖 | 版本 |
| --- | --- |
| Python 基础镜像 | `python:3.12-slim-bookworm` |
| astropy | `7.1.0` |
| numpy | `2.3.1` |
| Pillow | `11.3.0` |
| ncompress | Debian Bookworm 仓库版本 |

Python 依赖以 `sky-worker/requirements.txt` 为安装依据。`ncompress` 用于解压 ESO 发布的 Unix `.Z` FITS 文件。

## 外部运行依赖

- Docker Compose 插件：用于同时运行 GUI 和每小时夜空更新器。
- 能访问 `archive.eso.org` 和 `dataportal.eso.org` 的网络：仅实时更新需要；离线时使用包内真实观测帧。
- RAG Gateway、Weaviate、Embedding 与 vLLM：只有关闭演示模式并连接真实知识库时需要。
