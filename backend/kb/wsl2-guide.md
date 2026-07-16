# WSL2 配置手册

## 系统资源分配

WSL2 的内存分配可以通过 `.wslconfig` 文件配置。推荐使用 `gradual` 自动回收模式，这样 Windows 可以在需要时释放 WSL2 占用的内存。

### .wslconfig 配置示例

```ini
[wsl2]
memory=43GB
swap=12GB
localhostForwarding=true
sparseVhd=true
```

### 内存管理要点

1. **gradual 模式**：默认启用，WSL2 会在 Windows 内存紧张时自动释放页面
2. **最大内存限制**：通过 `memory` 参数设置，建议不超过物理内存的 70%
3. **Swap 配置**：通过 `swap` 参数设置虚拟内存大小
4. **稀疏 VHD**：`sparseVhd=true` 可以让 VHDX 文件按需增长，节省磁盘空间

## 网络配置

WSL2 使用 NAT 网络模式，Windows 主机可以访问 WSL2 服务，但反向需要端口转发。

### 端口转发

在 Windows PowerShell 中执行：

```powershell
netsh interface portproxy add v4tov4 listenport=8080 listenaddress=127.0.0.1 connectport=8080 connectaddress=<WSL2_IP>
```

### 代理配置

如果需要使用 HTTP 代理，在 WSL2 中设置环境变量：

```bash
export http_proxy=http://127.0.0.1:7897
export https_proxy=http://127.0.0.1:7897
export HF_ENDPOINT=https://hf-mirror.com
```

## 文件系统访问

### Windows 访问 WSL2 文件

```
\\wsl$\Ubuntu-22.04\home\username
```

### WSL2 访问 Windows 文件

```bash
# E 盘
/mnt/e/

# D 盘
/mnt/d/
```

> **注意**：大文件（>1GB）通过 `/mnt/` 路径访问可能导致 WSL2 崩溃或 C 盘膨胀。重要文件应存放在 WSL2 原生 ext4 文件系统中。

## Docker 集成

WSL2 可以运行 Docker Desktop，配置步骤：

1. 安装 Docker Desktop for Windows
2. 在设置中启用 "Use WSL 2 based engine"
3. 选择要集成的 WSL2 发行版

## 性能优化

1. 启用 Hyper-V 快速启动
2. 关闭 Windows Defender 实时扫描（针对开发目录）
3. 使用 SSD 存储 VHDX 文件
4. 合理配置内存和 CPU 限制