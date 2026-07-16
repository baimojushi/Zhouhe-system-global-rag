# ESO ALPACA 真实夜空背景

## 数据源

夜间主题采用 ESO 帕拉纳尔天文台 ALPACA 全天空相机的实际科学观测帧，不是生成式图片或循环视频。

- 官方说明：[ALPACA all-sky images from Paranal](https://archive.eso.org/cms/eso-archive-news/alpaca-all-sky-images-from-paranal-available-in-the-archive.html)
- 程序化访问：[ESO Programmatic Access](https://archive.eso.org/programmatic/)
- 查询表：`ist.alpaca`
- 当前公开帧：FITS，原始分辨率约 `8750 × 8750`
- 元数据：`dp_id`、`exp_start`、`date_end`、`sqm_zen`、分辨率和公开下载地址

ALPACA 只在天文夜间运行，因此“实时”采用诚实的两态定义：

1. `latest-qualified`：每小时查询到新的合格观测帧；
2. `bundled-fallback` / 最近可用：当地白天、天气不佳、网络失败或没有更合格帧时继续展示最近一张合格夜空，并在 UI 中明确标识。

## 每小时更新流程

`sky-updater` sidecar 每 3600 秒执行一次：

1. 使用 ESO TAP / ADQL 查询最新 `sqm_zen >= 21.8` 的 ALPACA 记录；
2. 若 `dp_id` 与当前帧相同，不下载；
3. 下载公开 `.fits.Z`；
4. 保留原始相对亮度，用百分位裁剪和固定 gamma 转为灰度 4K WebP；
5. 原子替换 `/data/sky/current.webp` 和 `/data/sky/current.json`；
6. 更新失败时不覆盖上一帧。

`sqm_zen` 是天顶天空表面亮度，单位为 `mag/arcsec²`；在同一仪器条件下数值越高通常表示天空越暗。默认阈值 21.8 可通过环境变量调整。

## 启动

```bash
docker compose -f docker-compose.local.yml up -d --build
```

| 环境变量 | 默认值 | 作用 |
| --- | ---: | --- |
| `SKY_UPDATE_SECONDS` | `3600` | 查询周期，脚本下限 900 秒 |
| `SKY_MIN_SQM_ZEN` | `21.8` | 合格夜空阈值 |
| `SKY_DISPLAY_SIZE` | `3840` | 输出 WebP 最大边 |
| `SKY_WEBP_QUALITY` | `88` | WebP 质量 |

GUI 端点：

- `GET /api/sky/latest`：观测元数据、状态和版本化图片地址；
- `GET /api/sky/image`：当前 WebP；共享卷没有内容时返回包内科学帧。

## 科研原图与氛围增强

默认是“科研原图模式”，不在观测帧上添加合成星。用户可手动开启“氛围增强”；此时 Canvas 星场、视星等和轻微闪烁只属于界面视觉层，UI 会明确说明它不是观测数据。

## 包内回退帧

项目包含一张从 ESO ALPACA 公开 FITS 转换的 4K WebP，以便第一次启动、离线或当地白天时仍有真实夜空背景：

- `dp_id`：`ALPACA.2026-07-16T06:56:52.000`
- 曝光：120 秒
- `sqm_zen`：22.00 mag/arcsec²
- 原始尺寸：8750 × 8750
- Credit：ESO / ALPACA

包内文件不是“持续实时”内容，因此界面显示“最近可用夜空”，不会冒充当前观测。

## 带宽与存储

原始压缩帧通常约 75–130 MB。只在 `dp_id` 变化且满足质量阈值时每小时下载一次，夜间预计约 0.8–1.5 GB，白天不重复下载。临时 FITS 转换后自动清理，共享卷只保留当前 WebP 和 JSON。
