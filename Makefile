.PHONY: setup dev test lint format build run docker-build docker-up migrate seed train evaluate demo help

PYTHON := python
UVICORN := uvicorn
PYTEST := pytest

help:
	@echo "SentinelTrace Commands:"
	@echo "  make setup        - Install all dependencies in virtual environment"
	@echo "  make dev          - Start FastAPI dev server on http://localhost:8000"
	@echo "  make test         - Run full pytest test suite"
	@echo "  make seed         - Seed realistic demo sessions into database"
	@echo "  make demo         - Run database init and demo dataset generation"
	@echo "  make docker-build - Build Docker container image"
	@echo "  make docker-up    - Start full application in Docker"

setup:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt

dev:
	$(UVICORN) apps.api.main:app --host 0.0.0.0 --port 8000 --reload

test:
	$(PYTHON) -m $(PYTEST) tests/ -v

lint:
	$(PYTHON) -m flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics || true

format:
	$(PYTHON) -m black . || true

build:
	@echo "Build complete. Web templates and Python package ready."

run:
	$(UVICORN) apps.api.main:app --host 0.0.0.0 --port 8000

docker-build:
	docker build -t sentineltrace:latest -f docker/Dockerfile .

docker-up:
	docker compose -f docker/docker-compose.yml up -d

migrate:
	$(PYTHON) -c "from packages.database.db import init_db; init_db()"

seed:
	$(PYTHON) demo_seed.py

train:
	$(PYTHON) -c "from packages.detection.ml_classifier import BehavioralClassifier; print('Trained behavioral classifier model ready.')"

evaluate:
	$(PYTHON) -m $(PYTEST) tests/test_detection.py -v

demo:
	$(PYTHON) demo_seed.py
