.PHONY: help build up down logs test clean

help:
	@echo "API Behavior Tracker - Makefile Commands"
	@echo ""
	@echo "  make build     - Build Docker images"
	@echo "  make up        - Start services with docker-compose"
	@echo "  make down      - Stop services"
	@echo "  make logs      - View application logs"
	@echo "  make test      - Run test requests"
	@echo "  make clean     - Clean up containers and volumes"

build:
	docker-compose build

up:
	docker-compose up -d
	@echo "Waiting for services to be ready..."
	@sleep 5
	@echo "Services started! Access at http://localhost:5000"

down:
	docker-compose down

logs:
	docker-compose logs -f api-tracker

test:
	@echo "Testing health endpoint..."
	@curl -s http://localhost:5000/health | python -m json.tool
	@echo "\nTesting analytics summary..."
	@curl -s http://localhost:5000/api/analytics/summary | python -m json.tool

clean:
	docker-compose down -v
	docker system prune -f
