# Production Deployment Guide

This guide covers considerations for deploying the Enterprise AI Platform in production environments.

> **Note:** This reference implementation is designed for clarity. Production deployments require additional hardening, monitoring, and operational procedures.

## Infrastructure Requirements

### Compute

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| API Servers | 2 replicas | 4+ replicas with autoscaling |
| Database | 2 vCPU, 4GB RAM | 4 vCPU, 16GB RAM |
| Network | Standard | Low-latency to LLM providers |

### Database

- PostgreSQL 15+ with pgvector extension
- Connection pooling (PgBouncer recommended)
- Read replicas for audit log queries
- Automated backups with point-in-time recovery

## Secrets Management

**Never store secrets in code or configuration files.**

### Recommended Approach

```yaml
# Use cloud secrets manager
# AWS Secrets Manager, Azure Key Vault, GCP Secret Manager, HashiCorp Vault

# Kubernetes example with External Secrets Operator
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: ai-platform-secrets
spec:
  secretStoreRef:
    kind: ClusterSecretStore
    name: aws-secrets-manager
  target:
    name: ai-platform-secrets
  data:
    - secretKey: OPENAI_API_KEY
      remoteRef:
        key: prod/ai-platform/openai
        property: api_key
    - secretKey: DATABASE_URL
      remoteRef:
        key: prod/ai-platform/database
        property: connection_string
```

### Secret Rotation

- Implement automated key rotation
- LLM API keys: rotate quarterly
- Database credentials: rotate monthly
- Audit key rotation events

## Kubernetes Deployment

### Sample Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ai-platform-api
  labels:
    app: ai-platform
    component: api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: ai-platform
      component: api
  template:
    metadata:
      labels:
        app: ai-platform
        component: api
    spec:
      containers:
        - name: api
          image: your-registry/ai-platform:1.0.0
          ports:
            - containerPort: 8000
          envFrom:
            - secretRef:
                name: ai-platform-secrets
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
            initialDelaySeconds: 10
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 5
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
---
apiVersion: v1
kind: Service
metadata:
  name: ai-platform-api
spec:
  selector:
    app: ai-platform
    component: api
  ports:
    - port: 80
      targetPort: 8000
  type: ClusterIP
```

### Horizontal Pod Autoscaler

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: ai-platform-api-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: ai-platform-api
  minReplicas: 3
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

## Observability

### Logging

Integrate with centralized logging:

```python
# Example: Structured logging with OpenTelemetry
import structlog
from opentelemetry import trace

logger = structlog.get_logger()

async def triage_ticket(ticket: Ticket):
    with trace.get_tracer(__name__).start_as_current_span("triage_ticket"):
        logger.info(
            "ticket_triage_started",
            ticket_id=ticket.ticket_id,
            tenant_id=context.tenant_id,
        )
        # ... processing
```

### Metrics

Key metrics to track:

| Metric | Type | Description |
|--------|------|-------------|
| `triage_requests_total` | Counter | Total triage requests |
| `triage_latency_seconds` | Histogram | End-to-end latency |
| `llm_calls_total` | Counter | LLM API calls |
| `llm_cost_dollars` | Counter | Estimated LLM costs |
| `policy_denials_total` | Counter | Policy engine denials |
| `pii_redactions_total` | Counter | PII patterns redacted |

### Tracing

```python
# OpenTelemetry integration
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

FastAPIInstrumentor.instrument_app(app)
HTTPXClientInstrumentor().instrument()
```

### Dashboards

Create dashboards for:
- Request volume and latency
- LLM costs by tenant
- Policy decision distribution
- Error rates and types
- Severity distribution

## Security Hardening

### Network

- Deploy in private subnets
- Use service mesh for mTLS (Istio, Linkerd)
- Restrict egress to LLM provider IPs
- Implement WAF rules

### Authentication

Replace header-based auth with:
- OAuth 2.0 / OIDC integration
- JWT validation with key rotation
- API key management with rate limiting

### Database

```sql
-- Row-level security for tenant isolation
CREATE POLICY tenant_isolation ON audit_logs
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant'));

-- Audit log access restrictions
REVOKE UPDATE, DELETE ON audit_logs FROM app_user;
GRANT INSERT, SELECT ON audit_logs TO app_user;
```

### Container Security

```dockerfile
# Run as non-root
FROM python:3.11-slim
RUN useradd -r -u 1000 appuser
USER appuser

# Minimal image
# No shell, no package manager
```

## Rate Limiting

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.post("/tickets/triage")
@limiter.limit("100/minute")
async def triage_ticket(request: Request, ticket: TicketRequest):
    ...
```

## Disaster Recovery

### Backup Strategy

| Data | RPO | RTO | Method |
|------|-----|-----|--------|
| Audit logs | 1 hour | 4 hours | Continuous WAL archival |
| Token maps | 1 hour | 4 hours | With audit logs |
| Configuration | 1 day | 1 hour | GitOps |

### Failover

- Multi-AZ database deployment
- Cross-region replication for DR
- LLM provider failover (OpenAI → Azure OpenAI)

## Compliance Checklist

- [ ] Data encryption at rest (AES-256)
- [ ] Data encryption in transit (TLS 1.3)
- [ ] Audit log immutability enforced
- [ ] Token map encryption with tenant keys
- [ ] Access logging enabled
- [ ] Vulnerability scanning in CI/CD
- [ ] Penetration testing scheduled
- [ ] Incident response plan documented
- [ ] Data retention policies implemented
- [ ] DSAR (data subject access request) process ready

## Cost Optimization

### LLM Costs

- Implement caching for repeated queries
- Use smaller models for classification
- Batch requests where possible
- Set per-tenant budgets

### Infrastructure

- Right-size instances based on metrics
- Use spot instances for non-critical workloads
- Implement request coalescing
- Archive old audit logs to cold storage

## Go-Live Checklist

1. [ ] All secrets in secrets manager
2. [ ] Database backups configured and tested
3. [ ] Monitoring and alerting active
4. [ ] Runbooks documented
5. [ ] Load testing completed
6. [ ] Security review passed
7. [ ] Compliance audit completed
8. [ ] Rollback procedure tested
9. [ ] On-call rotation established
10. [ ] Stakeholders notified
