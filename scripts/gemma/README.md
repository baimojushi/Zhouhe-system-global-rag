# Gemma 启动资料

本目录包含可直接随源码移动的 Gemma 服务管理器，不依赖 `F:\scripts\Gemma` 或任何固定 Windows 路径：

- `start-q4.cmd`：重启 Q4（默认 `8000`）。
- `start-q8.cmd`：重启 Q8（默认 `8002`）。
- `stop-all.cmd`：停止本项目管理的 Q4/Q8。
- `manage-gemma.ps1`：可配置 WSL 发行版、用户、操作和模型档位。
- `llama-service.sh`：安装到目标 WSL 用户目录的实际服务管理器。

模型和 llama.cpp 默认仍按当前机器布局读取；可通过 `LLAMA_SERVER_BINARY`、`LLAMA_Q4_MODEL`、`LLAMA_Q8_MODEL`、`LLAMA_Q8_LAST_SHARD` 等 WSL 环境变量覆盖。脚本只依据经过命令行身份校验的 PID 文件停止进程，不按端口或进程名称盲目批量结束。

`reference/` 保存用户提供的 Windows/WSL 启停脚本原件，仅用于审计和参数追踪，不被正式启动流程调用。

- `start_q4_server_persistent_v4.bat` 是 `llama.cpp` Gemma Q4 服务启动器，当前监听 `8000`。
- `start_llama_chat_persistent_v3.bat` 启动交互式 Python 客户端，不是服务端依赖。

原始脚本已发现并修正以下问题：Q4/Q8 启动器会停止所有 llama-server；Q8 检查中混入硬编码发行版和用户；健康检查只确认“任意 llama-server”；停止 BAT 固定引用 `/mnt/f/scripts/Gemma`；停止 SH 只输出 PID 列却尝试匹配命令名，实际通常无法停止服务；Windows 端还可能误杀占用 8000–8002 的无关进程。

制作完全自包含的离线安装包前，请补充：

1. 如需内置交互式客户端，补充 `llama_chat_persistent_v3.py`；
2. llama.cpp build commit、模型 GGUF SHA-256、chat template 和运行时 `/props`、`/slots` 快照。
