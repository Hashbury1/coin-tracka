.PHONY: up down logs test lint build

up:
	docker compose up --build

down:
	docker compose down -v

logs:
	docker compose logs -f

test:
	pip install -r tests/requirements-test.txt -q
	pytest tests/ --cov=services --cov-report=term-missing

lint:
	pip install ruff -q
	ruff check services/

build:
	docker compose build
