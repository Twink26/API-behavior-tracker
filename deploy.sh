#!/bin/bash
# Deployment script for Kubernetes

set -e

echo "🚀 API Behavior Tracker - Kubernetes Deployment Script"
echo "========================================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if kubectl is installed
if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}Error: kubectl is not installed${NC}"
    exit 1
fi

# Check if docker is installed (for building image)
if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}Warning: docker is not installed. Skipping image build.${NC}"
    SKIP_BUILD=true
fi

# Build Docker image if docker is available
if [ "$SKIP_BUILD" != true ]; then
    echo -e "${GREEN}Building Docker image...${NC}"
    docker build -t api-tracker:latest .
    echo -e "${GREEN}✓ Docker image built${NC}"
    echo ""
fi

# Apply Kubernetes manifests
echo -e "${GREEN}Applying Kubernetes manifests...${NC}"

echo "Creating namespace..."
kubectl apply -f k8s/namespace.yaml

echo "Creating ConfigMap..."
kubectl apply -f k8s/configmap.yaml

echo "Creating Secrets..."
if [ ! -f "k8s/secret.yaml" ] || ! grep -q "AWS_ACCESS_KEY_ID:" k8s/secret.yaml || grep -q 'AWS_ACCESS_KEY_ID: ""' k8s/secret.yaml; then
    echo -e "${YELLOW}⚠ Warning: Please update k8s/secret.yaml with your AWS credentials before deploying!${NC}"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi
kubectl apply -f k8s/secret.yaml

echo "Deploying PostgreSQL..."
kubectl apply -f k8s/postgres-deployment.yaml

echo "Waiting for PostgreSQL to be ready..."
kubectl wait --for=condition=ready pod -l app=postgres -n api-tracker --timeout=300s || {
    echo -e "${RED}PostgreSQL failed to start. Check logs with: kubectl logs -f deployment/postgres -n api-tracker${NC}"
    exit 1
}

echo "Deploying API Tracker..."
kubectl apply -f k8s/deployment.yaml

echo ""
echo -e "${GREEN}✓ Deployment complete!${NC}"
echo ""
echo "Checking status..."
kubectl get pods -n api-tracker
echo ""
kubectl get services -n api-tracker
echo ""
echo -e "${GREEN}To view logs:${NC}"
echo "  kubectl logs -f deployment/api-tracker -n api-tracker"
echo ""
echo -e "${GREEN}To scale the application:${NC}"
echo "  kubectl scale deployment api-tracker --replicas=3 -n api-tracker"
echo ""
echo -e "${GREEN}To get service URL:${NC}"
echo "  kubectl get svc api-tracker-service -n api-tracker"
