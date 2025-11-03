# 高德地图瓦片代理服务

支持多架构（x86/ARM）的高德地图瓦片代理服务，解决地图偏移问题，支持智能坐标转换和瓦片缓存。

## 功能特点

- 🌐 **智能坐标转换**：自动识别WGS84来源，进行坐标转换
- 🗺️ **瓦片缓存**：支持本地缓存瓦片，提高访问速度
- 🔄 **多架构支持**：同时支持x86/64和ARM架构
- 🔌 **简单配置**：通过环境变量和配置文件轻松定制

## 快速开始

### 在Linux系统直接运行

```bash
# 安装依赖
pip install -r requirements.txt

# 运行应用
python app.py
```

### 在Linux系统构建Docker镜像

```bash
# 克隆仓库
git clone https://github.com/lxg20082008/amap-tile-proxy.git
cd amap-tile-proxy

# 构建Docker镜像
docker build -t amap-tile-proxy:latest .

# 运行自己构建的镜像
docker run -d -p 8280:8280 \
  -v ./amap-cache:/tmp/cache \
  -v ./config:/app/config \
  -e CACHE_ENABLED=true \
  amap-tile-proxy:latest
```

### 使用Docker运行

```bash
# 使用Docker运行
docker run -d -p 8280:8280 \
  -v ./amap-cache:/tmp/cache \
  -v ./config:/app/config \
  -e CACHE_ENABLED=true \
  imno9999/amap-tile-proxy:latest
```

或者使用docker-compose:

```yaml
services:
  amap-proxy:
    image: imno9999/amap-tile-proxy:latest
    container_name: amap-proxy
    restart: unless-stopped
    environment:
      - LOG_LEVEL=INFO
      - CACHE_ENABLED=true
      - CACHE_DIR=/tmp/cache
    ports:
      - "8280:8280"
    volumes:
      - ./amap-cache:/tmp/cache
      - ./config:/app/config
      - ./geoip/GeoLite2-City.mmdb:/app/GeoLite2-City.mmdb:ro
```

## API 使用

```bash
# 健康检查
curl http://localhost:8280/health

# 获取瓦片
curl http://localhost:8280/amap/10/500/300.jpg

# 测试坐标转换
curl http://localhost:8280/api/test-coord?lng=116.391265&lat=39.907339
```

## 配置说明

### 环境变量

- `CACHE_ENABLED`: 是否启用缓存 (true/false)
- `CACHE_DIR`: 缓存目录路径 (默认: /tmp/cache)
- `LOG_LEVEL`: 日志级别 (INFO/DEBUG/ERROR)

### 例外规则配置

在`config/exception_rules`文件中配置需要进行WGS84到GCJ02转换的来源：

```
# 格式: 名称: 关键词1, 关键词2, 关键词3
openstreetmap: openstreetmap.org, osm.org
```

### GeoIP数据库

如需使用GeoIP功能，请将GeoLite2-City.mmdb文件放置在geoip目录下，容器会自动挂载使用。