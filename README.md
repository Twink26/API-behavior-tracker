# API Behavior Tracker

A production-inspired monitoring system that tracks and analyzes backend API usage. Built with Flask, PostgreSQL, Docker, and Kubernetes, designed to run on AWS (EKS or EC2).

## Features

- **Automatic Request Logging**: Every API request is automatically logged with endpoint, method, status code, latency, and timestamp
- **PostgreSQL Storage**: All request data is stored in a relational database with proper indexing
- **Analytics Endpoints**: REST APIs to query metrics like:
  - Most frequently used endpoints
  - Error rates by endpoint
  - Average response times
  - Overall summary statistics
- **CloudWatch Integration**: Optional AWS CloudWatch logging for centralized log management
- **Kubernetes Ready**: Complete K8s manifests for deployment
- **Docker Containerized**: Production-ready Docker configuration

## Architecture

```
┌─────────────┐
│   Client    │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────┐
│   Kubernetes Service            │
│   (LoadBalancer/NodePort)       │
└──────┬──────────────────────────┘
       │
       ▼
┌─────────────────────────────────┐
│   API Tracker Pods (2 replicas)│
│   - Flask Application           │
│   - Request Middleware           │
│   - CloudWatch Logger           │
└──────┬──────────────────────────┘
       │
       ├─────────────────┐
       ▼                 ▼
┌─────────────┐   ┌──────────────┐
│ PostgreSQL  │   │  CloudWatch  │
│  Database   │   │     Logs     │
└─────────────┘   └──────────────┘
```

## Quick Start

### Local Development with Docker Compose

1. **Clone and navigate to the project**:
```bash
cd "API behaviour tracker"
```

2. **Set up environment variables** (optional, for CloudWatch):
```bash
export AWS_ACCESS_KEY_ID=your_access_key
export AWS_SECRET_ACCESS_KEY=your_secret_key
export AWS_REGION=us-east-1
```

3. **Start the services**:
```bash
docker-compose up -d
```

4. **Verify the application is running**:
```bash
curl http://localhost:5000/health
```

5. **Make some test requests**:
```bash
curl http://localhost:5000/api/analytics/summary
curl http://localhost:5000/api/analytics/most-used
```

### Kubernetes Deployment

#### Prerequisites
- Kubernetes cluster (EKS or EC2 with kubeadm)
- `kubectl` configured
- Docker image built and pushed to a registry

#### Step 1: Build and Push Docker Image

```bash
# Build the image
docker build -t api-tracker:latest .

# Tag for your registry (example for ECR)
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-east-1.amazonaws.com
docker tag api-tracker:latest <account-id>.dkr.ecr.us-east-1.amazonaws.com/api-tracker:latest
docker push <account-id>.dkr.ecr.us-east-1.amazonaws.com/api-tracker:latest
```

#### Step 2: Update Kubernetes Manifests

1. **Update `k8s/deployment.yaml`** with your container image URL:
```yaml
image: <your-registry>/api-tracker:latest
```

2. **Update `k8s/secret.yaml`** with your AWS credentials:
```bash
# Encode your secrets
echo -n 'your-aws-access-key' | base64
echo -n 'your-aws-secret-key' | base64
```

#### Step 3: Deploy to Kubernetes

```bash
# Create namespace
kubectl apply -f k8s/namespace.yaml

# Create secrets (update with your values first!)
kubectl apply -f k8s/secret.yaml

# Create configmap
kubectl apply -f k8s/configmap.yaml

# Deploy PostgreSQL
kubectl apply -f k8s/postgres-deployment.yaml

# Wait for PostgreSQL to be ready
kubectl wait --for=condition=ready pod -l app=postgres -n api-tracker --timeout=300s

# Deploy API Tracker
kubectl apply -f k8s/deployment.yaml

# Check status
kubectl get pods -n api-tracker
kubectl get services -n api-tracker
```

#### Step 4: Access the Service

**For EKS (LoadBalancer)**:
```bash
kubectl get svc api-tracker-service -n api-tracker
# Use the EXTERNAL-IP from the output
```

**For EC2 (NodePort)**:
```bash
# Change service type to NodePort in k8s/deployment.yaml
kubectl get svc api-tracker-service -n api-tracker
# Access via <node-ip>:<nodeport>
```

## API Endpoints

### Health Check
```
GET /health
```
Returns application health status.

### Analytics Endpoints

#### Summary Statistics
```
GET /api/analytics/summary?hours=24
```
Returns overall statistics:
- Total requests
- Error count and rate
- Average latency
- Unique endpoints

#### Most Used Endpoints
```
GET /api/analytics/most-used?limit=10&hours=24
```
Returns the most frequently accessed endpoints.

#### Error Rates
```
GET /api/analytics/error-rates?hours=24
```
Returns error rates by endpoint (status codes >= 400).

#### Average Response Times
```
GET /api/analytics/response-times?hours=24
```
Returns average, min, and max latency by endpoint.

#### Recent Requests
```
GET /api/requests?limit=100&hours=1
```
Returns recent API requests with full details.

## Database Schema

```sql
CREATE TABLE api_requests (
    id SERIAL PRIMARY KEY,
    endpoint VARCHAR(500) NOT NULL,
    method VARCHAR(10) NOT NULL,
    status_code INTEGER NOT NULL,
    latency_ms FLOAT NOT NULL,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ip_address VARCHAR(45),
    user_agent VARCHAR(500)
);

-- Indexes for performance
CREATE INDEX idx_endpoint ON api_requests(endpoint);
CREATE INDEX idx_method ON api_requests(method);
CREATE INDEX idx_status_code ON api_requests(status_code);
CREATE INDEX idx_timestamp ON api_requests(timestamp);
```

## Configuration

### Environment Variables

- `DATABASE_URL`: PostgreSQL connection string (default: `postgresql://api_tracker:password@localhost:5432/api_tracker`)
- `PORT`: Application port (default: `5000`)
- `AWS_REGION`: AWS region for CloudWatch (default: `us-east-1`)
- `AWS_ACCESS_KEY_ID`: AWS access key for CloudWatch
- `AWS_SECRET_ACCESS_KEY`: AWS secret key for CloudWatch
- `CLOUDWATCH_LOG_GROUP`: CloudWatch log group name (default: `api-behavior-tracker`)
- `CLOUDWATCH_LOG_STREAM`: CloudWatch log stream name (default: `api-requests`)

### Kubernetes ConfigMap

Configuration is managed via `k8s/configmap.yaml`. Update it to change non-sensitive settings.

### Kubernetes Secrets

Sensitive data (AWS credentials, database passwords) are stored in `k8s/secret.yaml`. **Never commit real secrets to version control!**

## Monitoring and Scaling

### View Logs
```bash
# Application logs
kubectl logs -f deployment/api-tracker -n api-tracker

# PostgreSQL logs
kubectl logs -f deployment/postgres -n api-tracker
```

### Scale the Application
```bash
kubectl scale deployment api-tracker --replicas=5 -n api-tracker
```

### Check Metrics
```bash
# Pod status
kubectl get pods -n api-tracker

# Service endpoints
kubectl get endpoints api-tracker-service -n api-tracker

# Resource usage
kubectl top pods -n api-tracker
```

## Production Considerations

1. **Database**: Use managed PostgreSQL (RDS) instead of in-cluster database
2. **Secrets**: Use AWS Secrets Manager or External Secrets Operator
3. **Monitoring**: Integrate with Prometheus and Grafana
4. **Backup**: Set up database backups
5. **Security**: Use TLS/HTTPS, network policies, and RBAC
6. **High Availability**: Use multiple database replicas and proper health checks
7. **Resource Limits**: Adjust CPU/memory limits based on load

## SQL Query Examples

The application uses several meaningful SQL queries:

### Most Used Endpoints
```sql
SELECT endpoint, method, COUNT(*) as count
FROM api_requests
WHERE timestamp >= NOW() - INTERVAL '24 hours'
GROUP BY endpoint, method
ORDER BY count DESC
LIMIT 10;
```

### Error Rates
```sql
SELECT 
    endpoint,
    method,
    COUNT(*) as total,
    SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END) as errors,
    ROUND(SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as error_rate
FROM api_requests
WHERE timestamp >= NOW() - INTERVAL '24 hours'
GROUP BY endpoint, method
ORDER BY error_rate DESC;
```

### Average Response Times
```sql
SELECT 
    endpoint,
    method,
    AVG(latency_ms) as avg_latency,
    MIN(latency_ms) as min_latency,
    MAX(latency_ms) as max_latency,
    COUNT(*) as request_count
FROM api_requests
WHERE timestamp >= NOW() - INTERVAL '24 hours'
GROUP BY endpoint, method
ORDER BY avg_latency DESC;
```

## Troubleshooting

### Database Connection Issues
```bash
# Check PostgreSQL pod
kubectl get pods -n api-tracker
kubectl logs postgres-xxx -n api-tracker

# Test connection
kubectl exec -it postgres-xxx -n api-tracker -- psql -U api_tracker -d api_tracker
```

### Application Not Starting
```bash
# Check pod logs
kubectl logs -f deployment/api-tracker -n api-tracker

# Check pod events
kubectl describe pod <pod-name> -n api-tracker
```

### CloudWatch Not Logging
- Verify AWS credentials are set correctly
- Check IAM permissions for CloudWatch Logs
- Verify log group exists in CloudWatch console

## License

MIT License - feel free to use this project for learning and production purposes.
