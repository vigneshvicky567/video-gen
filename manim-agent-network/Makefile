.PHONY: build run down logs rebuild

build:
	docker-compose build

run:
	docker-compose up -d

down:
	docker-compose down

logs:
	docker-compose logs -f

rebuild:
	docker-compose build --no-cache
	docker-compose up -d --force-recreate
