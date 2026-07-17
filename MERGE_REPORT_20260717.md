# 2026-07-17 合并说明

本目录以用户提供的 `Zhouhe-system-global-rag-master` 为业务基线，合并 runtime-fix 与自包含服务管理更新。

## 保留自 master

- 全部 65 个原有文件，无文件丢失；
- `app/globals.css` 的知识库字号和可读性调整；
- Q4/Q8 自包含管理器、一键停止脚本与全部参考启停脚本；
- master 中 PowerShell 5.1 兼容处理（正式启停入口仍使用参数化窄匹配版本）。

## 恢复和修正

- 前端从 Ollama/vLLM/Qwen 恢复为 Gateway 内置 BGE-M3 + llama.cpp Gemma；
- Gateway 默认端口恢复为 `9100`，并迁移浏览器保存的旧 `8090` 默认值；
- 恢复 `turbopack.root`、standalone 静态资源复制和全 JS chunk 自检；
- 恢复 `dev:webpack`，并增加显式 `dev:lan`，默认开发服务器只监听本机；
- 移除 `backend/test_import.py` 中硬编码的 Weaviate 密钥，改读环境变量并正确返回失败退出码；
- 补回 `.env.example`、Gemma 下一版本目标、运行修复报告及完整实施方案；
- 一键启停保留 `LinuxRoot`、端口和 WSL 参数，不使用全局 `pkill rag_gateway.py`；
- Weaviate 健康检查将 API Key 留给 WSL shell 展开，不由 PowerShell提前展开为空。

## 验证结果

- Bash 语法检查通过；
- ESLint 通过；
- Next.js 16.2.6 Turbopack 生产构建通过；
- TypeScript 通过；
- UI 自检通过：主页、1 个 CSS、7 个客户端 JS、知识库工作台和 ESO ALPACA 夜空接口正常；
- 页面运行输出只包含 BGE-M3/Gemma，不包含旧 vLLM/Ollama 服务文案；
- 压缩包不包含 `node_modules`、`.next`、`.runtime` 或真实密钥。

Windows + WSL + GPU 的服务级启停仍需在目标机器执行最终验收。
