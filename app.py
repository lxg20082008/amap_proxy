from flask import Flask, jsonify, request, send_file
import math
import logging
import requests
from io import BytesIO
import os
import hashlib
from datetime import datetime
from pathlib import Path
import geoip2.database
import geoip2.errors
from dotenv import load_dotenv

# 加载配置文件中的环境变量
load_dotenv('config/settings.conf')

app = Flask(__name__)
# 获取环境变量中的日志级别，默认为INFO
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, log_level))
logger = logging.getLogger(__name__)

# GeoIP配置
GEOIP_ENABLED = os.environ.get("GEOIP_ENABLED", "true").lower() == "true"
GEOIP_DB_PATH = os.environ.get("GEOIP_DB_PATH", os.path.join(os.path.dirname(__file__), 'geoip', 'GeoLite2-City.mmdb'))

# 初始化GeoIP读取器
geoip_reader = None
if GEOIP_ENABLED:
    try:
        if os.path.exists(GEOIP_DB_PATH):
            geoip_reader = geoip2.database.Reader(GEOIP_DB_PATH)
            logger.info(f"GeoIP数据库已加载: {GEOIP_DB_PATH}")
        else:
            logger.warning(f"GeoIP数据库文件不存在: {GEOIP_DB_PATH}")
            GEOIP_ENABLED = False
    except Exception as e:
        logger.error(f"加载GeoIP数据库失败: {e}")
        GEOIP_ENABLED = False

# 缓存配置
CACHE_ENABLED = os.environ.get("CACHE_ENABLED", "false").lower() == "true"
CACHE_DIR = os.environ.get("CACHE_DIR", "/app/cache")
# 确保缓存目录存在
if CACHE_ENABLED:
    Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)
    logger.info(f"缓存已启用，缓存目录: {CACHE_DIR}")

# ===== 坐标转换函数 =====
def wgs84_to_gcj02(lng, lat):
    """WGS84转GCJ02坐标系"""
    if not (73.66 <= lng <= 135.05 and 3.86 <= lat <= 53.55):
        return lng, lat
        
    a = 6378245.0
    ee = 0.00669342162296594323
    
    def transform_lat(x, y):
        ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
        ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
        ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
        return ret

    def transform_lon(x, y):
        ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
        ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
        ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
        return ret

    dlat = transform_lat(lng - 105.0, lat - 35.0)
    dlng = transform_lon(lng - 105.0, lat - 35.0)
    
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - ee * magic * magic
    sqrtmagic = math.sqrt(magic)
    
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
    dlng = (dlng * 180.0) / (a / sqrtmagic * math.cos(radlat) * math.pi)
    
    mglat = lat + dlat
    mglng = lng + dlng
    
    return mglng, mglat

def tile_to_lnglat(x, y, z):
    """瓦片坐标转经纬度"""
    n = 2.0 ** z
    lng = x / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    lat = lat_rad * 180.0 / math.pi
    return lng, lat

def lnglat_to_tile(lng, lat, z):
    """经纬度转瓦片坐标"""
    n = 2.0 ** z
    x = int((lng + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y

# ===== GeoIP检测 =====
def is_china_mainland_ip(ip_address):
    """检查IP是否为中国大陆IP"""
    if not GEOIP_ENABLED or not geoip_reader:
        logger.debug("GeoIP功能未启用，跳过IP检测")
        return False
    
    try:
        # 忽略私有IP和本地IP
        if ip_address in ('127.0.0.1', 'localhost', '::1') or ip_address.startswith(('10.', '172.16.', '192.168.')):
            logger.debug(f"本地/私有IP: {ip_address}, 跳过GeoIP检测")
            return False
            
        response = geoip_reader.city(ip_address)
        country_code = response.country.iso_code
        
        is_china = country_code == 'CN'
        logger.debug(f"IP: {ip_address}, 国家: {country_code}, 是否中国大陆: {is_china}")
        return is_china
    except geoip2.errors.AddressNotFoundError:
        logger.debug(f"IP地址未找到: {ip_address}")
        return False
    except Exception as e:
        logger.error(f"GeoIP检测错误: {e}")
        return False

# ===== 例外规则处理 =====
def load_exception_rules():
    """加载例外规则"""
    rules = {}
    rule_file = os.path.join(os.path.dirname(__file__), 'config', 'exception_rules')
    
    try:
        with open(rule_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                if ':' in line:
                    name, patterns = line.split(':', 1)
                    name = name.strip()
                    # 分割模式并清理空格
                    patterns = [p.strip() for p in patterns.split(',') if p.strip()]
                    rules[name] = patterns
                    
        logger.info(f"加载了 {len(rules)} 个例外规则")
        return rules
    except Exception as e:
        logger.error(f"加载例外规则失败: {e}")
        return {}

def is_wgs84_source(referer='', user_agent='', ip_address=''):
    """检查是否为需要转换的WGS84来源"""
    referer = referer.lower() if referer else ''
    user_agent = user_agent.lower() if user_agent else ''
    
    # 1. 首先检查例外规则
    wgs84_sources = load_exception_rules()
    
    for source_name, patterns in wgs84_sources.items():
        for pattern in patterns:
            if pattern and (pattern in referer or pattern in user_agent):
                logger.info(f"匹配例外规则: {source_name} - {pattern}")
                return True
    
    # 2. 如果没有匹配例外规则，且IP不是中国大陆，则认为是WGS84来源
    if ip_address and GEOIP_ENABLED and not is_china_mainland_ip(ip_address):
        logger.info(f"非中国大陆IP: {ip_address}, 判定为WGS84来源")
        return True
        
    return False

# ===== 缓存功能 =====
def get_cache_path(z, x, y, style=8, ltype=None):
    """获取瓦片缓存路径"""
    if not CACHE_ENABLED:
        return None
    
    # 创建多级目录结构，避免单个目录下文件过多
    cache_dir = Path(CACHE_DIR) / str(z) / str(x // 100) / f"style_{style}"
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    # 生成缓存文件名，包含ltype参数以区分不同类型的瓦片
    ltype_suffix = f"_{ltype}" if ltype else ""
    cache_file = cache_dir / f"{x}_{y}{ltype_suffix}.jpg"
    return cache_file

def save_tile_to_cache(z, x, y, content, style=8, ltype=None):
    """保存瓦片到缓存"""
    if not CACHE_ENABLED:
        return
    
    try:
        cache_path = get_cache_path(z, x, y, style, ltype)
        if cache_path:
            with open(cache_path, 'wb') as f:
                f.write(content)
            logger.debug(f"已缓存瓦片: z={z}, x={x}, y={y}, style={style}, ltype={ltype}")
    except Exception as e:
        logger.error(f"缓存瓦片失败: {e}")

def get_tile_from_cache(z, x, y, style=8, ltype=None):
    """从缓存获取瓦片"""
    if not CACHE_ENABLED:
        return None
    
    try:
        cache_path = get_cache_path(z, x, y, style, ltype)
        if cache_path and cache_path.exists():
            logger.debug(f"从缓存读取瓦片: z={z}, x={x}, y={y}, style={style}, ltype={ltype}")
            return send_file(
                cache_path,
                mimetype='image/jpeg',
                as_attachment=False,
                max_age=86400
            )
    except Exception as e:
        logger.error(f"读取缓存瓦片失败: {e}")
    
    return None

# ===== 高德地图配置 =====
AMAP_SERVERS = ["webrd01.is.autonavi.com", "webrd02.is.autonavi.com", "webrd03.is.autonavi.com", "webrd04.is.autonavi.com"]

# 导出必要的变量和函数供其他模块使用
__all__ = [
    'app', 'fetch_amap_tile', 'tile_to_lnglat', 'lnglat_to_tile', 
    'wgs84_to_gcj02', 'is_wgs84_source', 'CACHE_ENABLED', 'GEOIP_ENABLED',
    'GEOIP_DB_PATH', 'get_tile_from_cache', 'save_tile_to_cache',
    'load_exception_rules'
]

def fetch_amap_tile(z, x, y, style=8, ltype=None):
    """获取高德地图瓦片"""
    try:
        # 先尝试从缓存获取
        cached_tile = get_tile_from_cache(z, x, y, style, ltype)
        if cached_tile:
            return cached_tile
        
        # 根据style选择合适的域名
        if style == 6:  # 纯影像，使用webst域名
            domains = [
                "webst01.is.autonavi.com",
                "webst02.is.autonavi.com", 
                "webst03.is.autonavi.com",
                "webst04.is.autonavi.com"
            ]
        elif style in [7, 9]:  # 矢量大字版，使用wprd域名
            domains = [
                "wprd01.is.autonavi.com",
                "wprd02.is.autonavi.com",
                "wprd03.is.autonavi.com", 
                "wprd04.is.autonavi.com"
            ]
        else:  # style=8或其他，使用webrd域名
            domains = [
                "webrd01.is.autonavi.com",
                "webrd02.is.autonavi.com",
                "webrd03.is.autonavi.com",
                "webrd04.is.autonavi.com"
            ]
        
        # 计算初始服务器编号
        server_num = (x + y) % len(domains)
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://www.amap.com/"
        }
        
        last_error = None
        # 尝试所有域名
        for i in range(len(domains)):
            try:
                current_server = (server_num + i) % len(domains)
                domain = domains[current_server]
                
                # 构建URL，支持style和ltype参数
                url = f"https://{domain}/appmaptile?lang=zh_cn&size=1&scale=1&style={style}&x={x}&y={y}&z={z}"
                if ltype:
                    url += f"&ltype={ltype}"
                
                response = requests.get(url, headers=headers, timeout=5)
                response.raise_for_status()
                
                # 验证响应是否为有效图片
                content_type = response.headers.get('content-type', '')
                if not content_type.startswith('image/') or len(response.content) < 100:
                    logger.warning(f"服务器 {domain} 返回了无效的图片响应: {content_type}, 大小: {len(response.content)} 字节")
                    continue
                
                # 保存到缓存
                if CACHE_ENABLED:
                    save_tile_to_cache(z, x, y, response.content, style, ltype)
                
                return send_file(
                    BytesIO(response.content),
                    mimetype='image/jpeg',
                    as_attachment=False,
                    max_age=86400
                )
            except Exception as e:
                last_error = e
                logger.warning(f"从服务器 {domain} 获取瓦片失败: {e}")
                continue
        
        # 如果所有服务器都失败了
        error_msg = f"所有服务器获取瓦片都失败了。最后一个错误: {last_error}"
        logger.error(error_msg)
        return jsonify({"error": error_msg}), 500
            
    except Exception as e:
        logger.error(f"获取高德瓦片失败: {e}")
        return jsonify({"error": str(e)}), 500

# ===== 路由定义 =====
@app.route("/")
def index():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>高德地图瓦片代理 - 智能坐标转换</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <meta charset="utf-8">
        <script src="https://cdn.jsdelivr.net/npm/ol@v7.5.2/dist/ol.js"></script>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/ol@v7.5.2/ol.css">
        <style>
            body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }
            .container { max-width: 1200px; margin: 0 auto; }
            .header { background: #fff; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
            .card { background: white; padding: 20px; margin: 15px 0; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
            .btn { padding: 10px 15px; background: #1890ff; color: white; border: none; border-radius: 4px; cursor: pointer; margin: 5px; }
            .btn:hover { background: #40a9ff; }
            .result { margin-top: 10px; padding: 10px; background: #fafafa; border-radius: 4px; }
            .map-container { height: 400px; border: 1px solid #ddd; border-radius: 4px; margin: 10px 0; }
            .layer-selector { margin: 10px 0; }
            .layer-selector select { padding: 8px 12px; border: 1px solid #ddd; border-radius: 4px; margin-left: 10px; }
            .status-indicator { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 8px; }
            .status-online { background: #52c41a; }
            .status-offline { background: #ff4d4f; }
            .info-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 15px; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🗺️ 高德地图瓦片代理服务</h1>
                <p>基于默认GCJ02 + 例外规则的智能坐标转换</p>
                <div class="layer-selector">
                    <strong>地图图层：</strong>
                    <select id="layerSelect" onchange="changeMapLayer()">
                        <option value="6">卫星影像 (style=6)</option>
                        <option value="8" selected>标准矢量 (style=8)</option>
                        <option value="7">矢量大字版 (style=7)</option>
                        <option value="9">矢量注记版 (style=9)</option>
                    </select>
                </div>
            </div>
            
            <div class="info-grid">
                <div class="card">
                    <h3><span class="status-indicator" id="serviceStatus"></span>服务状态</h3>
                    <button class="btn" onclick="testService()">测试服务</button>
                    <div id="status-result" class="result"></div>
                </div>

                <div class="card">
                    <h3>坐标转换测试</h3>
                    <p>默认GCJ02输入，例外WGS84转换</p>
                    <button class="btn" onclick="testCoord()">测试坐标转换</button>
                    <div id="coord-result" class="result"></div>
                </div>
            </div>

            <div class="card">
                <h3>地图预览</h3>
                <div class="layer-selector">
                    <strong>当前图层：</strong>
                    <span id="currentLayer">标准矢量 (style=8)</span>
                </div>
                <div id="map" class="map-container"></div>
                <div style="margin-top: 10px;">
                    <button class="btn" onclick="resetMapView()">重置视图</button>
                    <button class="btn" onclick="getCurrentTileInfo()">当前瓦片信息</button>
                </div>
                <div id="tile-info" class="result"></div>
            </div>
        </div>

        <script>
            let map;
            let currentStyle = 8;
            
            // 初始化地图
            function initMap() {
                map = new ol.Map({
                    target: 'map',
                    layers: [
                        new ol.layer.Tile({
                            source: new ol.source.XYZ({
                                url: '/amap/{z}/{x}/{y}.jpg?style=' + currentStyle,
                                attributions: '© 高德地图'
                            })
                        })
                    ],
                    view: new ol.View({
                        center: ol.proj.fromLonLat([116.3974, 39.9093]),
                        zoom: 12
                    })
                });
            }
            
            // 切换地图图层
            function changeMapLayer() {
                const select = document.getElementById('layerSelect');
                currentStyle = parseInt(select.value);
                const layerNames = {
                    '6': '卫星影像 (style=6)',
                    '8': '标准矢量 (style=8)',
                    '7': '矢量大字版 (style=7)',
                    '9': '矢量注记版 (style=9)'
                };
                
                document.getElementById('currentLayer').textContent = layerNames[currentStyle];
                
                // 更新地图图层
                const newLayer = new ol.layer.Tile({
                    source: new ol.source.XYZ({
                        url: '/amap/{z}/{x}/{y}.jpg?style=' + currentStyle,
                        attributions: '© 高德地图'
                    })
                });
                
                // 移除旧图层，添加新图层
                map.removeLayer(map.getLayers().item(0));
                map.addLayer(newLayer);
            }
            
            // 重置地图视图
            function resetMapView() {
                map.getView().setCenter(ol.proj.fromLonLat([116.3974, 39.9093]));
                map.getView().setZoom(12);
            }
            
            // 获取当前瓦片信息
            function getCurrentTileInfo() {
                const view = map.getView();
                const center = view.getCenter();
                const zoom = Math.round(view.getZoom());
                const lonlat = ol.proj.toLonLat(center);
                
                // 计算瓦片坐标
                const n = Math.pow(2, zoom);
                const x = Math.floor((lonlat[0] + 180) / 360 * n);
                const y = Math.floor((1 - Math.log(Math.tan(Math.PI/4 + lonlat[1]*Math.PI/360)) / Math.PI) / 2 * n);
                
                const info = `
                    <strong>当前瓦片信息：</strong><br>
                    经纬度: ${lonlat[0].toFixed(6)}, ${lonlat[1].toFixed(6)}<br>
                    缩放级别: ${zoom}<br>
                    瓦片坐标: (${x}, ${y})<br>
                    当前图层: style=${currentStyle}<br>
                    瓦片URL: /amap/${zoom}/${x}/${y}.jpg?style=${currentStyle}
                `;
                
                document.getElementById('tile-info').innerHTML = info;
            }
            
            async function testService() {
                const result = document.getElementById('status-result');
                const statusIndicator = document.getElementById('serviceStatus');
                result.innerHTML = '测试中...';
                statusIndicator.className = 'status-indicator';
                
                try {
                    const response = await fetch('/health');
                    const data = await response.json();
                    
                    if (response.ok) {
                        statusIndicator.className = 'status-indicator status-online';
                        result.innerHTML = `<h4>服务状态正常</h4><pre>${JSON.stringify(data, null, 2)}</pre>`;
                    } else {
                        throw new Error('服务响应异常');
                    }
                } catch (error) {
                    statusIndicator.className = 'status-indicator status-offline';
                    result.innerHTML = '错误: ' + error.message;
                }
            }

            async function testCoord() {
                const result = document.getElementById('coord-result');
                result.innerHTML = '测试中...';
                try {
                    const response = await fetch('/api/test-coord?lng=116.391265&lat=39.907339');
                    const data = await response.json();
                    result.innerHTML = "<h4>坐标转换结果:</h4><pre>" + JSON.stringify(data, null, 2) + "</pre>";
                } catch (error) {
                    result.innerHTML = '错误: ' + error.message;
                }
            }
            
            // 页面加载完成后初始化
            document.addEventListener('DOMContentLoaded', function() {
                initMap();
                testService(); // 自动测试服务状态
            });
        </script>
    </body>
    </html>
    """

@app.route("/health")
def health():
    """健康检查接口"""
    return jsonify({
        "status": "healthy",
        "service": "amap-tile-proxy",
        "version": "2.0-smart",
        "coordinate_strategy": "默认GCJ02 + 例外WGS84转换 + GeoIP智能判断",
        "exception_rules_loaded": len(load_exception_rules()),
        "geoip_enabled": GEOIP_ENABLED,
        "geoip_db_path": GEOIP_DB_PATH if GEOIP_ENABLED else None,
        "timestamp": datetime.now().isoformat()
    })

@app.route("/api/test-coord")
def test_coord():
    """测试坐标转换"""
    lng = float(request.args.get('lng', 116.3974))
    lat = float(request.args.get('lat', 39.9093))
    
    gcj_lng, gcj_lat = wgs84_to_gcj02(lng, lat)
    
    return jsonify({
        "wgs84": {"lng": lng, "lat": lat},
        "gcj02": {"lng": round(gcj_lng, 6), "lat": round(gcj_lat, 6)},
        "offset": {
            "lng": round(gcj_lng - lng, 6),
            "lat": round(gcj_lat - lat, 6)
        }
    })

@app.route("/amap/<int:z>/<int:x>/<int:y>.jpg")
def get_tile(z, x, y):
    """获取高德地图瓦片 - 基于例外规则和GeoIP的智能转换"""
    try:
        # 获取客户端IP
        client_ip = request.remote_addr
        
        # 检查是否为需要转换的例外情况
        need_conversion = is_wgs84_source(
            referer=request.headers.get('Referer', ''),
            user_agent=request.headers.get('User-Agent', ''),
            ip_address=client_ip
        )
        
        logger.info(f"瓦片请求: z={z}, x={x}, y={y}, IP: {client_ip}, 需要转换: {need_conversion}")
        
        if need_conversion:
            # 例外情况：WGS84 → GCJ02 转换
            wgs_lng, wgs_lat = tile_to_lnglat(x, y, z)
            gcj_lng, gcj_lat = wgs84_to_gcj02(wgs_lng, wgs_lat)
            gcj_x, gcj_y = lnglat_to_tile(gcj_lng, gcj_lat, z)
            target_x, target_y = gcj_x, gcj_y
        else:
            # 默认情况：直接使用（GCJ02输入）
            target_x, target_y = x, y
        
        # 获取style参数，默认为8（标准矢量）
        style = int(request.args.get('style', 8))
        ltype = request.args.get('ltype')
        
        return fetch_amap_tile(z, target_x, target_y, style, ltype)
            
    except Exception as e:
        logger.error(f"瓦片处理错误: {e}")
        return jsonify({"error": "Internal server error"}), 500


def register_test_routes():
    """注册测试路由"""
    @app.route("/test_tile.html")
    def test_tile():
        """提供测试页面"""
        try:
            file_path = os.path.join(os.path.dirname(__file__), 'test_tile.html')
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            return jsonify({"error": "测试页面文件不存在"}), 404

@app.route("/tile")
def get_tile_query():
    """获取高德地图瓦片 - 查询参数格式 (兼容测试页面)"""
    try:
        x = int(request.args.get('x', 0))
        y = int(request.args.get('y', 0))
        z = int(request.args.get('z', 0))

        # 验证参数
        if z < 1 or z > 18:
            return jsonify({"error": "无效的缩放级别，应在1-18范围内"}), 400

        # 计算该缩放级别下的有效坐标范围
        scale = 1 << z  # 等同于 Math.pow(2, z)
        if x < 0 or x >= scale or y < 0 or y >= scale:
            logger.warning(f"无效的瓦片坐标: z={z}, x={x}, y={y}，该缩放级别下的有效范围应为：0 ≤ x,y < {scale}")
            return jsonify({
                "error": f"无效的瓦片坐标，对于缩放级别{z}，x和y应在0-{scale-1}范围内",
                "valid_range": {
                    "min": 0,
                    "max": scale - 1,
                    "zoom": z,
                    "total_tiles": scale * scale
                }
            }), 400

        # 获取style参数，默认为8（标准矢量）
        style = int(request.args.get('style', 8))
        ltype = request.args.get('ltype')
        
        logger.info(f"瓦片请求(查询参数): z={z}, x={x}, y={y}, style={style}, ltype={ltype} (缩放级别范围: 0-{scale-1})")
        return fetch_amap_tile(z, x, y, style, ltype)
    except ValueError as e:
        logger.error(f"无效的参数格式: {e}")
        return jsonify({"error": "无效的参数格式，x、y和z都应该是整数"}), 400
    except Exception as e:
        logger.error(f"瓦片处理错误(查询参数): {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/coordinate-tile")
def get_coordinate_tile():
    """根据经纬度坐标获取瓦片 - 支持GCJ02和WGS84坐标系"""
    try:
        lng = float(request.args.get('lng', 116.3974))
        lat = float(request.args.get('lat', 39.9093))
        z = int(request.args.get('z', 15))
        coord_type = request.args.get('coord_type', 'gcj02').lower()
        client_ip = request.remote_addr
        logger.info(f"坐标瓦片请求: lng={lng}, lat={lat}, z={z}, coord_type={coord_type}, IP: {client_ip}")
        
        if coord_type == 'wgs84':
            gcj_lng, gcj_lat = wgs84_to_gcj02(lng, lat)
            x, y = lnglat_to_tile(gcj_lng, gcj_lat, z)
        else:
            x, y = lnglat_to_tile(lng, lat, z)
        
        # 获取style参数，默认为8（标准矢量）
        style = int(request.args.get('style', 8))
        ltype = request.args.get('ltype')
        
        logger.info(f"坐标瓦片请求转换后: z={z}, x={x}, y={y}, style={style}, ltype={ltype}")
        return fetch_amap_tile(z, x, y, style, ltype)
    except Exception as e:
        logger.error(f"坐标瓦片处理错误: {e}")
        return jsonify({"error": "Internal server error"}), 500


# 注册测试路由
register_test_routes()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8280))
    debug = os.environ.get("DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)