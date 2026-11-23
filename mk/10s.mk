# Edge image targets: the web app is built inside docker/caddy/Dockerfile (no Node needed on the host).
# The user path is `uv run sgw up --demo`, which builds sgw/caddy when it is missing; these targets rebuild it.
COMPOSE_EDGE := docker compose -p sgw --env-file var/compose.env

.PHONY: web-image web-image-up web-image-multiarch
web-image: ## Build sgw/caddy (web/dist + Caddyfile on the pinned Caddy)
	$(COMPOSE_EDGE) build caddy

web-image-up: ## Rebuild sgw/caddy and recreate only the caddy container of the running stack
	$(COMPOSE_EDGE) up -d --no-deps --build --wait caddy

web-image-multiarch: ## Build sgw/caddy for linux/amd64 and linux/arm64 without loading it (K20 check)
	docker buildx build --platform linux/amd64,linux/arm64 -f docker/caddy/Dockerfile .
