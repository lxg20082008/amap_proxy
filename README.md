# 高德地图瓦片代理服务

支持多架构（x86/ARM）的高德地图瓦片代理服务，解决地图偏移问题，支持智能坐标转换和瓦片缓存。

## 功能特点

- 🌐 **智能坐标转换**：自动识别WGS84来源，进行坐标转换
- 🗺️ **瓦片缓存**：支持本地缓存瓦片，提高访问速度
- 🎨 **多图层支持**：支持卫星影像、标准矢量、矢量大字版等多种地图样式
- 🖥️ **交互式界面**：主页集成实时地图预览和图层切换功能
- 🔄 **多架构支持**：同时支持x86/64和ARM架构
- 🔌 **简单配置**：通过环境变量和配置文件轻松定制
- 📊 **实时信息**：显示瓦片坐标、URL等详细信息

## 快速开始

### 在Linux系统直接运行

推荐使用配置文件来管理环境变量，这样更安全且灵活。

```bash
# 配置文件已包含在 config/settings.conf
# 可根据需要修改配置参数

# 安装依赖
pip install -r requirements.txt

# 运行应用 (会自动加载配置文件)
python app.py
```

### 访问服务

启动后访问 `http://localhost:8280/` 可以：

- 🗺️ **交互式地图预览**：实时查看不同图层效果
- 🎨 **图层切换**：选择卫星影像、标准矢量、矢量大字版等样式
- 📊 **瓦片信息**：显示当前地图的瓦片坐标和URL
- 🩺 **服务状态**：实时监控服务运行状态
- 🔄 **坐标转换测试**：测试WGS84到GCJ02的坐标转换

### 在Linux系统构建Docker镜像

```bash
# 克隆仓库
git clone https://github.com/lxg20082008/amap_proxy.git
cd amap_proxy

# 构建Docker镜像
# Dockerfile会自动复制以下文件：
# - app.py (主应用)
# - test_tile.html (高级测试页面)
# - config/settings.conf (环境变量配置)
# - config/ (例外规则配置)
docker build -t amap_proxy:latest .

# 运行自己构建的镜像
docker run -d -p 8280:8280 \
  -v ./amap-cache:/app/cache \
  -v ./config:/app/config \
  -e CACHE_ENABLED=true \
  -e GEOIP_ENABLED=false \
  amap_proxy:latest
```

### 使用Docker运行

```bash
# 使用Docker运行
docker run -d -p 8280:8280 \
  -v ./amap-cache:/app/cache \
  -v ./config:/app/config \
  -e CACHE_ENABLED=true \
  -e GEOIP_ENABLED=false \
  lxg20082008/amap_proxy:latest
```

或者使用docker-compose:

```yaml
services:
  amap-proxy:
    image: lxg20082008/amap_proxy:latest
    container_name: amap-proxy
    restart: unless-stopped
    environment:
      - LOG_LEVEL=INFO
      - CACHE_ENABLED=true
      - CACHE_DIR=/app/cache
      - GEOIP_ENABLED=false # 在这里禁用GeoIP
    ports:
      - "8280:8280"
    volumes:
      - ./amap-cache:/app/cache
      - ./config:/app/config
      - ./GeoLite2-City.mmdb:/app/GeoLite2-City.mmdb:ro
```

## API 使用

### 基础API

```bash
# 健康检查
curl http://localhost:8280/health

# 获取瓦片（默认标准矢量图层）
curl http://localhost:8280/amap/10/500/300.jpg

# 获取指定图层瓦片
curl http://localhost:8280/amap/10/500/300.jpg?style=6  # 卫星影像
curl http://localhost:8280/amap/10/500/300.jpg?style=7  # 矢量大字版
curl http://localhost:8280/amap/10/500/300.jpg?style=8  # 标准矢量（默认）
curl http://localhost:8280/amap/10/500/300.jpg?style=9  # 矢量注记版

# 测试坐标转换
curl http://localhost:8280/api/test-coord?lng=116.391265&lat=39.907339
```

### 查询参数API

```bash
# 使用查询参数格式获取瓦片
curl "http://localhost:8280/tile?z=10&x=500&y=300&style=6"

# 根据经纬度获取瓦片
curl "http://localhost:8280/coordinate-tile?lng=116.3974&lat=39.9093&z=12&style=8"
```

## 配置说明

### 环境变量

- `CACHE_ENABLED`: 是否启用缓存 (true/false)
- `CACHE_DIR`: 缓存目录路径 (默认: /app/cache)
- `LOG_LEVEL`: 日志级别 (INFO/DEBUG/ERROR)
- `GEOIP_ENABLED`: 是否启用GeoIP地理位置判断 (true/false, 默认: true)
- `PORT`: 服务端口 (默认: 8280)
- `DEBUG`: 是否启用调试模式 (true/false, 默认: false)

### 缓存结构说明

启用缓存后，瓦片按以下分层结构存储，避免不同图层间的缓存冲突：

```
./amap-cache/
├── {z}/                    # 缩放级别
│   └── {x//100}/          # X坐标分片（每100个瓦片一个目录）
│       └── style_{style}/ # 图层样式目录（style_6, style_7, style_8, style_9）
│           └── {x}_{y}_{ltype}.jpg  # 瓦片文件（包含ltype参数）
```

**特点：**
- 🎯 **图层隔离**：不同style参数的瓦片存储在独立目录
- 📁 **分片存储**：避免单个目录文件过多，提高性能
- 🔧 **灵活扩展**：支持ltype参数区分同图层不同类型瓦片

### 图层参数说明

支持以下地图样式（通过`style`参数指定）：

- **`style=6`**: 卫星影像图层 - 使用 `webst` 域名，适用于卫星图显示
- **`style=7`**: 矢量大字版 - 使用 `wprd` 域名，大字体矢量地图
- **`style=8`**: 标准矢量图层 - 使用 `webrd` 域名，**默认样式**，最常用
- **`style=9`**: 矢量注记版 - 使用 `wprd` 域名，带详细注记的矢量地图

### URL参数

- `style`: 地图样式 (6/7/8/9，默认8)
- `ltype`: 图层类型（可选，用于特定图层配置）
- `x`, `y`, `z`: 瓦片坐标
- `lng`, `lat`: 经纬度坐标（用于coordinate-tile接口）

### 例外规则配置

在`config/exception_rules`文件中配置需要进行WGS84到GCJ02转换的来源：

```
# 格式: 名称: 关键词1, 关键词2, 关键词3
openstreetmap: openstreetmap.org, osm.org
```

### GeoIP数据库

GeoIP功能通过配置文件控制，在 `config/settings.conf` 中进行配置：

#### 配置文件设置

配置文件位于 `config/settings.conf`：

```bash
# 启用GeoIP功能（需要有效的GeoLite2-City.mmdb文件）
GEOIP_ENABLED=true

# 禁用GeoIP功能（推荐在生产环境中禁用以提高性能）
GEOIP_ENABLED=false

# GeoIP数据库文件路径（可选，默认为项目根目录）
GEOIP_DB_PATH=./GeoLite2-City.mmdb
```

#### 数据库文件配置

1. **下载GeoLite2数据库**（需要MaxMind账户）：
   ```bash
   # 从MaxMind官网下载GeoLite2-City.mmdb文件
   # 将文件放置在项目根目录
   ```

2. **配置文件路径**：
   - **默认位置**：项目根目录 `./GeoLite2-City.mmdb`
   - **自定义位置**：通过`GEOIP_DB_PATH`环境变量指定

3. **Docker部署**：
   ```bash
   # 挂载GeoIP数据库文件到容器
   docker run -d -p 8280:8280 \
     -v ./GeoLite2-City.mmdb:/app/GeoLite2-City.mmdb:ro \
     -e GEOIP_ENABLED=true \
     lxg20082008/amap_proxy:latest
   ```

#### 工作原理

- **GEOIP_ENABLED=true** + **有效数据库文件** → 启用智能IP地理位置判断
- **GEOIP_ENABLED=false** → 跳过GeoIP检测，仅基于例外规则判断
- **文件不存在** + **GEOIP_ENABLED=true** → 自动禁用GeoIP功能，记录警告日志

### Docker镜像包含的文件

Docker构建时会自动复制以下关键文件到镜像中：

- **`app.py`** - 主应用程序
- **`test_tile.html`** - 高级测试页面
- **`config/settings.conf`** - 环境变量配置（包含GEOIP_ENABLED=false等设置）
- **`config/`** - 例外规则配置目录

> 💡 **提示**：镜像中已包含完整的测试环境，可以直接访问 `/test_tile.html` 进行高级功能测试。

## 项目结构

```
amap_proxy/
├── app.py                 # 主应用文件
├── requirements.txt        # Python依赖
├── config/
│   ├── settings.conf       # 环境变量配置
│   └── exception_rules    # 例外规则配置
├── docker-compose.yaml    # Docker Compose配置
├── Dockerfile            # Docker镜像构建文件
├── GeoLite2-City.mmdb    # GeoIP数据库文件
├── test_tile.html        # 高级测试页面
├── .github/
│   └── workflows/
│       └── docker-build.yml  # GitHub Actions自动构建
├── amap-cache/           # 瓦片缓存目录（运行时创建）
│   ├── {z}/              # 缩放级别目录
│   │   └── {x//100}/     # X坐标分片目录
│   │       └── style_{style}/  # 图层样式目录
│   │           └── {x}_{y}_{ltype}.jpg  # 瓦片文件
└── README.md             # 项目文档
```

## 测试页面

### 主页测试 (http://localhost:8280/)

提供完整的交互式测试环境：

- **🗺️ 实时地图预览**：集成OpenLayers地图组件
- **🎨 图层切换器**：下拉选择不同地图样式
  - 卫星影像 (style=6)
  - 标准矢量 (style=8) - 默认
  - 矢量大字版 (style=7)
  - 矢量注记版 (style=9)
- **📊 瓦片信息显示**：实时显示当前地图的：
  - 经纬度坐标
  - 缩放级别
  - 瓦片坐标 (x, y)
  - 瓦片URL
- **🩺 服务状态监控**：实时显示服务在线状态
- **🔄 坐标转换测试**：测试WGS84到GCJ02的坐标转换

### 高级测试页面 (http://localhost:8280/test_tile.html)

> 📝 **注意**：此页面已包含在Docker镜像中，无需额外配置

提供专业的地图瓦片分析工具：

- **🎯 坐标系统对比**：WGS84 vs GCJ02坐标差异可视化
- **📏 瓦片覆盖分析**：计算瓦片的地理覆盖范围
- **🔍 高精度测试**：支持Z17-Z18级别的高缩放测试
- **📐 坐标转换可视化**：显示偏移量和转换结果
- **🗂️ 多图层管理**：同时加载和比较多个图层
- **📍 坐标定位工具**：精确的坐标输入和定位功能

### 测试功能对比

| 功能 | 主页 | 高级测试页 |
|------|------|------------|
| 基础地图预览 | ✅ | ✅ |
| 图层切换 | ✅ | ✅ |
| 瓦片信息显示 | ✅ | ✅ |
| 坐标转换测试 | ✅ | ✅ |
| 坐标系统对比 | ❌ | ✅ |
| 瓦片覆盖分析 | ❌ | ✅ |
| 高精度测试 | ❌ | ✅ |
| 多图层对比 | ❌ | ✅ |
| 专业分析工具 | ❌ | ✅ |

## 使用场景

### 1. 开发测试
- **基础测试**：访问主页 `http://localhost:8280/` 进行快速功能验证
- **专业分析**：使用测试页面进行深度地图瓦片分析
- **图层对比**：在不同图层间切换，选择最适合的地图样式
- **坐标调试**：查看实时瓦片信息用于坐标系统调试

### 2. 生产部署
- 使用Docker容器部署，支持多架构
- 配置缓存提高访问速度
- 启用GeoIP进行智能坐标转换

### 3. 第三方集成
- 通过API接口获取指定样式的地图瓦片
- 支持WGS84和GCJ02坐标系的自动转换
- 兼容各种地图应用框架

### 4. 科研和教育
- **坐标系统研究**：对比WGS84和GCJ02坐标差异
- **地图投影教学**：演示Web Mercator投影原理
- **瓦片系统分析**：理解瓦片金字塔结构
- **地理信息系统学习**：实践GIS坐标转换