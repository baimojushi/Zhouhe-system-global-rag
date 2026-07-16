# Docker 部署指南

## 镜像加速配置

Docker Hub 镜像在大陆网络环境下下载缓慢。推荐使用 DaoCloud 加速服务。

### 配置 DaoCloud 镜像

编辑或创建 `/etc/docker/daemon.json`：

```json
{
    "registry-mirrors": [
        "https://m.daocloud.io"
    ]
}
```

然后重启 Docker：

```bash
sudo systemctl daemon-reload
sudo systemctl restart docker
```

### DaoCloud 加速前缀

使用 `m.daocloud.io` 前缀拉取镜像：

```bash
docker pull m.daocloud.io/docker.io/library/nginx:latest
```

## Docker Compose 部署

### 基础 compose 文件

```yaml
version: '3.8'
services:
  weaviate:
    image: semitechnologies/weaviate:1.38.3
    ports:
      - "127.0.0.1:8080:8080"
      - "127.0.0.1:50051:50051"
    environment:
      - QUERY_DEFAULTS_LIMIT=25
      - AUTHENTICATION_APIKEY_ENABLED=true
      - AUTHENTICATION_APIKEY_ALLOWED_KEYS=your-api-key
      - AUTHORIZATION_ADMINLIST_ENABLED=true
      - AUTHORIZATION_ADMINLIST_USERS=admin
      - PERSISTENCE_DATA_PATH=/var/lib/weaviate
    volumes:
      - weaviate_data:/var/lib/weaviate
    deploy:
      resources:
        limits:
          memory: 14G

volumes:
  weaviate_data:
```

### 生产环境建议

1. **离线镜像导入**：在可联网机器导出镜像，通过 `docker load` 导入
2. **持久化存储**：挂载外部 Volume 或绑定挂载
3. **健康检查**：配置 `healthcheck` 确保服务可用性
4. **资源限制**：设置合理的内存和 CPU 限制

## 常用命令

```bash
# 查看容器状态
docker ps -a

# 查看容器日志
docker logs -f <container_name>

# 进入容器
docker exec -it <container_name> bash

# 导出镜像
docker save -o image.tar <image_name>

# 导入镜像
docker load -i image.tar
```

## 网络配置

### 自定义网络

```bash
docker network create rag-network
```

### 容器间通信

```yaml
services:
  service_a:
    networks:
      - rag-network
  service_b:
    networks:
      - rag-network

networks:
  rag-network:
    driver: bridge
```