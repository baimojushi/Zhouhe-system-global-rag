# 第三方视觉资产

## ESO ALPACA 科学夜空帧

- 项目文件：`public/sky/alpaca-snapshot.webp`
- 元数据：`public/sky/alpaca-snapshot.json`
- 记录：`ALPACA.2026-07-16T06:56:52.000`
- 来源：ESO Science Archive Facility，帕拉纳尔天文台 ALPACA 全天空相机
- 官方说明：https://archive.eso.org/cms/eso-archive-news/alpaca-all-sky-images-from-paranal-available-in-the-archive.html
- 署名：ESO / ALPACA

项目内文件是公开 8750 × 8750 FITS 观测的 3840 × 3840 WebP 转换，作为诚实标注的“最近可用夜空”。运行时更新器会获取新的合格公开观测。UI 保留观测 ID、拍摄时间、曝光、原始分辨率和天顶天空亮度。合成 Canvas 星场默认关闭，开启时也明确标记为视觉层而非观测数据。

## M81 旋涡星系背景

- 项目文件：`public/galaxy-m81.webp`
- 原始文件：`hs-2007-19-a-scaled_tif.tif`（4822 × 3240）
- 来源：NASA Scientific Visualization Studio，ID 30110
- 页面：https://svs.gsfc.nasa.gov/30110/
- 原始下载：https://svs.gsfc.nasa.gov/vis/a030000/a030100/a030110/hs-2007-19-a-scaled_tif.tif
- 署名：NASA, ESA, and The Hubble Heritage Team (STScI/AURA)

项目内版本仅进行了 WebP 压缩和等比例缩放，没有生成或伪造天体结构。界面中的额外星点、亮度与缓慢闪烁由浏览器 Canvas 程序生成，不属于原始摄影图像。

NASA 媒体使用指南：https://www.nasa.gov/nasa-brand-center/images-and-media/
