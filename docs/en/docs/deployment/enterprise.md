# Enterprise Deployment Guide

This guide covers deploying FastAPI applications in enterprise environments with production-grade infrastructure, security, and observability.

## Architecture Overview

```
┌─────────────────────────────────────────────────┐
│                   Internet                       │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│          Load Balancer / CDN                     │
│        (AWS ELB, Cloudflare, etc.)              │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│           Reverse Proxy                          │
│         (nginx, Traefik, Envoy)                 │
│   - SSL Termination                             │
│   - Rate Limiting                               │
│   - Request Buffering                           │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│        ASGI Server Cluster                       │
│        (Uvicorn / Gunicorn + Uvicorn)           │
│                                                  │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│   │ Worker 1 │  │ Worker 2 │  │ Worker N │    │
│   │ FastAPI  │  │ FastAPI  │  │ FastAPI  │    │
│   └──────────┘  └──────────┘  └──────────┘    │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│            Service Layer                         │
│                                                  │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│   │ Database │  │  Redis   │  │  Queue   │    │
│   │(Postgres)│  │ (Cache)  │ │(RabbitMQ)│    │
│   └──────────┘  └──────────┘  └──────────┘    │
└─────────────────────────────────────────────────┘
```

## 1. Server Configuration

### Uvicorn with Gunicorn

For production, use Gunicorn as a process manager with Uvicorn workers:

```bash
# Install
pip install "fastapi[standard]" gunicorn

# Run
gunicorn main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --access-logfile - \
  --error-logfile - \
  --log-level info \
  --timeout 120 \
  --graceful-timeout 30 \
  --keep-alive 5
```

### Worker Count

Formula: `workers = (2 x CPU cores) + 1`

For CPU-bound: `workers = CPU cores`
For I/O-bound: `workers = (2 x CPU cores) + 1`

### Environment Variables

```bash
# .env.production
ENVIRONMENT=production
LOG_LEVEL=info
WORKERS=4
TIMEOUT=120
KEEPALIVE=5

# Database
DATABASE_URL=postgresql://user:pass@db:5432/dbname
DATABASE_POOL_SIZE=20
DATABASE_MAX_OVERFLOW=10

# Redis
REDIS_URL=redis://redis:6379/0
REDIS_POOL_SIZE=10

# Security
SECRET_KEY=your-secret-key-here
ALLOWED_HOSTS=["yourdomain.com"]
CORS_ORIGINS=["https://yourdomain.com"]

# Observability
SENTRY_DSN=https://your-sentry-dsn
PROMETHEUS_PORT=9090
JAEGER_HOST=jaeger
JAEGER_PORT=6831
```

## 2. Enterprise Middleware Stack

### Complete Configuration

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

# Enterprise middleware
from fastapi.middleware.security_headers import SecurityHeadersMiddleware
from fastapi.middleware.rate_limit import RateLimitMiddleware
from fastapi.middleware.logging import (
    RequestIDMiddleware,
    StructuredLoggingMiddleware,
    configure_structured_logging,
)
from fastapi.middleware.audit import AuditLoggingMiddleware
from fastapi.middleware.opentelemetry import OpenTelemetryMiddleware
from fastapi.middleware.cache import CacheMiddleware, RedisCache
from fastapi.middleware.circuit_breaker import CircuitBreakerMiddleware
from fastapi.middleware.metrics import PrometheusMiddleware, expose_metrics_endpoint
from fastapi.middleware.error_tracking import configure_sentry, SentryMiddleware

import redis

# Initialize app
app = FastAPI(
    title="My Enterprise API",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# Configure logging
configure_structured_logging(log_level="INFO", json_format=True)

# Configure Sentry
configure_sentry(
    dsn=os.getenv("SENTRY_DSN"),
    environment=os.getenv("ENVIRONMENT", "production"),
    traces_sample_rate=0.1,
)

# Add middleware (order matters!)
# 1. Error tracking (outermost - catches all errors)
app.add_middleware(SentryMiddleware)

# 2. Metrics collection
app.add_middleware(PrometheusMiddleware)

# 3. Security headers
app.add_middleware(
    SecurityHeadersMiddleware,
    csp="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'",
    hsts_max_age=31536000,
)

# 4. Trusted hosts
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=os.getenv("ALLOWED_HOSTS", "").split(","),
)

# 5. Rate limiting
app.add_middleware(
    RateLimitMiddleware,
    requests_per_minute=60,
    requests_per_hour=1000,
    requests_per_day=10000,
)

# 6. CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 7. Request ID tracking
app.add_middleware(RequestIDMiddleware)

# 8. Structured logging
app.add_middleware(
    StructuredLoggingMiddleware,
    skip_paths=["/health", "/metrics"],
)

# 9. Audit logging
app.add_middleware(
    AuditLoggingMiddleware,
    audit_paths=["/api/admin", "/api/users"],
)

# 10. OpenTelemetry tracing
app.add_middleware(
    OpenTelemetryMiddleware,
    tracer_name="my-api",
    exclude_paths=["/health", "/metrics"],
)

# 11. Caching (with Redis)
redis_client = redis.Redis.from_url(os.getenv("REDIS_URL"))
app.add_middleware(
    CacheMiddleware,
    backend=RedisCache(redis_client),
    default_ttl=60,
    cache_paths=["/api/data"],
)

# 12. Circuit breaker
app.add_middleware(
    CircuitBreakerMiddleware,
    failure_threshold=5,
    timeout=60,
    protected_paths=["/api/external"],
)

# 13. GZIP compression (innermost)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Expose metrics endpoint
expose_metrics_endpoint(app, path="/metrics")
```

## 3. Database Configuration

### Connection Pooling (SQLAlchemy)

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(
    DATABASE_URL,
    pool_size=20,           # Max pool size
    max_overflow=10,        # Max overflow connections
    pool_pre_ping=True,     # Verify connections
    pool_recycle=3600,      # Recycle connections after 1 hour
    echo=False,             # Disable SQL logging in production
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

### Async Database (SQLAlchemy 2.0 + asyncpg)

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL").replace("postgresql://", "postgresql+asyncpg://")

engine = create_async_engine(
    DATABASE_URL,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    echo=False,
)

AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
```

## 4. Caching Strategy

### Redis Configuration

```python
import redis.asyncio as aioredis

redis_pool = aioredis.ConnectionPool.from_url(
    os.getenv("REDIS_URL"),
    max_connections=10,
    decode_responses=True,
)

redis_client = aioredis.Redis(connection_pool=redis_pool)

# Cache decorator
from functools import wraps
import json

def cache(ttl: int = 60):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Generate cache key
            key = f"{func.__name__}:{json.dumps(args)}:{json.dumps(kwargs)}"

            # Try to get from cache
            cached = await redis_client.get(key)
            if cached:
                return json.loads(cached)

            # Call function
            result = await func(*args, **kwargs)

            # Store in cache
            await redis_client.setex(key, ttl, json.dumps(result))

            return result
        return wrapper
    return decorator
```

## 5. Security Hardening

### SSL/TLS Configuration (nginx)

```nginx
server {
    listen 443 ssl http2;
    server_name yourdomain.com;

    # SSL certificates
    ssl_certificate /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;

    # SSL protocols and ciphers
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;

    # HSTS
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;

    # Security headers
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Proxy to FastAPI
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # Rate limiting
    limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
    limit_req zone=api_limit burst=20 nodelay;
}
```

### Secrets Management

Use environment variables or secret management services:

- **AWS**: Secrets Manager, Parameter Store
- **GCP**: Secret Manager
- **Azure**: Key Vault
- **HashiCorp**: Vault
- **Kubernetes**: Secrets

```python
import os
from functools import lru_cache

@lru_cache()
def get_settings():
    return Settings(
        database_url=os.getenv("DATABASE_URL"),
        secret_key=os.getenv("SECRET_KEY"),
        # ... other secrets
    )
```

## 6. Monitoring & Observability

### Metrics (Prometheus + Grafana)

```python
# Expose metrics
from fastapi.middleware.metrics import PrometheusMetrics, expose_metrics_endpoint

metrics = PrometheusMetrics(app, app_name="my-api")
expose_metrics_endpoint(app)
```

**Prometheus Configuration** (`prometheus.yml`):

```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'fastapi'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
```

### Distributed Tracing (Jaeger)

```python
from fastapi.middleware.opentelemetry import configure_opentelemetry

configure_opentelemetry(
    service_name="my-api",
    exporter_type="jaeger",
    jaeger_host=os.getenv("JAEGER_HOST", "localhost"),
)
```

### Logging (ELK Stack)

```python
from fastapi.middleware.logging import configure_structured_logging

configure_structured_logging(
    log_level="INFO",
    json_format=True,
    include_timestamp=True,
)
```

**Logstash Configuration**:

```ruby
input {
  file {
    path => "/var/log/fastapi/*.log"
    codec => "json"
  }
}

filter {
  # Parse JSON logs
}

output {
  elasticsearch {
    hosts => ["elasticsearch:9200"]
    index => "fastapi-logs-%{+YYYY.MM.dd}"
  }
}
```

## 7. Docker Deployment

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Run application
CMD ["gunicorn", "main:app", \
     "--workers", "4", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
```

### Docker Compose

```yaml
version: '3.8'

services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/dbname
      - REDIS_URL=redis://redis:6379/0
      - SENTRY_DSN=${SENTRY_DSN}
    depends_on:
      - db
      - redis
    restart: unless-stopped

  db:
    image: postgres:15
    environment:
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass
      - POSTGRES_DB=dbname
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./ssl:/etc/nginx/ssl
    depends_on:
      - api
    restart: unless-stopped

  prometheus:
    image: prom/prometheus
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    restart: unless-stopped

  grafana:
    image: grafana/grafana
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    restart: unless-stopped

volumes:
  postgres_data:
```

## 8. Kubernetes Deployment

### Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: fastapi-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app: fastapi
  template:
    metadata:
      labels:
        app: fastapi
    spec:
      containers:
      - name: fastapi
        image: your-registry/fastapi:latest
        ports:
        - containerPort: 8000
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: fastapi-secrets
              key: database-url
        - name: REDIS_URL
          valueFrom:
            secretKeyRef:
              name: fastapi-secrets
              key: redis-url
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "1Gi"
            cpu: "1000m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
```

### Service

```yaml
apiVersion: v1
kind: Service
metadata:
  name: fastapi-service
spec:
  selector:
    app: fastapi
  ports:
  - protocol: TCP
    port: 80
    targetPort: 8000
  type: LoadBalancer
```

### Ingress

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: fastapi-ingress
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  tls:
  - hosts:
    - yourdomain.com
    secretName: fastapi-tls
  rules:
  - host: yourdomain.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: fastapi-service
            port:
              number: 80
```

## 9. CI/CD Pipeline

### GitHub Actions

```yaml
name: Deploy to Production

on:
  push:
    tags:
      - 'v*'

jobs:
  deploy:
    runs-on: ubuntu-latest

    steps:
    - uses: actions/checkout@v4

    - name: Run tests
      run: |
        pip install -e ".[dev]"
        pytest

    - name: Build Docker image
      run: docker build -t myregistry/fastapi:${{ github.ref_name }} .

    - name: Push to registry
      run: docker push myregistry/fastapi:${{ github.ref_name }}

    - name: Deploy to Kubernetes
      uses: azure/k8s-deploy@v4
      with:
        manifests: |
          k8s/deployment.yaml
          k8s/service.yaml
        images: |
          myregistry/fastapi:${{ github.ref_name }}
```

## 10. Performance Optimization

### Best Practices

1. **Use async/await**: For I/O-bound operations
2. **Connection pooling**: Database and Redis
3. **Caching**: Redis for frequently accessed data
4. **Response compression**: GZIP middleware
5. **CDN**: Serve static assets via CDN
6. **Database indexing**: Index frequently queried columns
7. **Query optimization**: Avoid N+1 queries
8. **Response models**: Use `response_model` to filter data

### Load Testing

```bash
# Install locust
pip install locust

# Run load test
locust -f load_tests.py --host=https://yourdomain.com
```

## 11. Compliance & Audit

### SOC 2 Requirements

- ✅ Audit logging (AuditLoggingMiddleware)
- ✅ Access control (OAuth2, RBAC)
- ✅ Encryption (TLS/SSL)
- ✅ Monitoring (Prometheus, Sentry)
- ✅ Backup & recovery (Database backups)

### GDPR Compliance

- ✅ Data minimization
- ✅ Right to erasure
- ✅ Data portability
- ✅ Consent management
- ✅ Audit trails

## 12. Disaster Recovery

### Backup Strategy

- **Database**: Daily automated backups
- **Redis**: AOF persistence + RDB snapshots
- **Application logs**: Retained for 90 days
- **Metrics**: Retained for 1 year

### High Availability

- **Multi-region deployment**
- **Database replication** (read replicas)
- **Redis cluster** (sentinel or cluster mode)
- **Load balancer** (health checks, failover)
- **Auto-scaling** (based on CPU/memory)

## Summary

This guide covers enterprise-grade deployment of FastAPI applications with:

- ✅ Production-ready server configuration
- ✅ Comprehensive middleware stack
- ✅ Database and caching optimization
- ✅ Security hardening
- ✅ Monitoring and observability
- ✅ Container orchestration
- ✅ CI/CD automation
- ✅ Performance optimization
- ✅ Compliance and audit
- ✅ Disaster recovery

For specific cloud providers, see:
- [AWS Deployment](aws.md)
- [GCP Deployment](gcp.md)
- [Azure Deployment](azure.md)
