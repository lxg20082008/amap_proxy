FROM python:3.9-alpine

WORKDIR /app

# 安装系统依赖
RUN apk update && apk add --no-cache curl

# 创建非root用户
RUN addgroup -S appgroup && adduser -S appuser -G appgroup

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 创建缓存目录结构（支持多图层分层缓存）
RUN mkdir -p /app/cache && chown -R appuser:appgroup /app/cache

# 创建空的GeoIP数据库文件，用户可以在运行时挂载实际文件
RUN touch /app/GeoLite2-City.mmdb && chown appuser:appgroup /app/GeoLite2-City.mmdb

# 验证安装（更新为实际使用的依赖）
RUN python -c "import flask; import requests; import geoip2.database; from dotenv import load_dotenv; print('✅ 所有依赖安装成功')"

# 复制应用代码和配置
COPY app.py .
COPY test_tile.html .
COPY config/settings.conf ./config/
COPY config /app/config
COPY GeoLite2-City.mmdb .

# 设置权限
RUN chown -R appuser:appgroup /app

# 设置环境变量
ENV CACHE_ENABLED=true
ENV CACHE_DIR=/app/cache
ENV LOG_LEVEL=INFO
ENV GEOIP_ENABLED=true

EXPOSE 8280

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8280/health || exit 1

VOLUME ["/app/cache"]

# 切换到非root用户
USER appuser

CMD ["python", "app.py"]