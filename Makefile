# Oracle VM deployment helpers -- see DEPLOYMENT_ORACLE.md for the full walkthrough.
# Mirrors the exact nginx-bootstrap -> ssl -> nginx-install sequence already proven
# working for jamanvar.kelviontech.in and restaurant.kelviontech.in on this same VM.

DOMAIN          ?= whatsapp.kelviontech.in
CERTBOT_EMAIL   ?= kelviontech@gmail.com
KELVIONTECH_DIR ?= /home/ubuntu/KelvionTech
NGINX_CONTAINER ?= kelviontech-nginx-1
COMPOSE         := docker compose -f docker-compose.yml -f docker-compose.oracle.yml

.PHONY: up down restart ps logs logs-backend logs-frontend build \
        nginx-bootstrap nginx-install ssl seed check

up: ## Build and start this project's stack (isolated ports, see docker-compose.oracle.yml)
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f

logs-backend:
	$(COMPOSE) logs -f backend

logs-frontend:
	$(COMPOSE) logs -f frontend

build:
	$(COMPOSE) build

# Phase 1 -- install an HTTP-only vhost so the domain is reachable and the ACME
# challenge path works BEFORE a certificate exists (nginx -t fails if the full vhost's
# ssl_certificate line points at a file that isn't on disk yet).
nginx-bootstrap:
	sudo cp nginx/$(DOMAIN).bootstrap.conf $(KELVIONTECH_DIR)/nginx/conf.d/$(DOMAIN).conf
	docker exec $(NGINX_CONTAINER) nginx -t
	docker exec $(NGINX_CONTAINER) nginx -s reload
	@echo "Bootstrap vhost installed -> http://$(DOMAIN) should now proxy to the app."

# Phase 2 -- issue the certificate. --entrypoint override is required: the certbot
# service's own entrypoint is a renewal loop that never reads a "certonly" command
# without this, and just runs forever instead of issuing anything.
ssl:
	cd $(KELVIONTECH_DIR) && docker compose run --rm --entrypoint certbot certbot certonly \
		--webroot -w /var/www/certbot \
		-d $(DOMAIN) \
		--email $(CERTBOT_EMAIL) --agree-tos --no-eff-email

# Phase 3 -- swap in the full HTTP-redirect + HTTPS vhost now that the cert exists.
nginx-install:
	sudo cp nginx/$(DOMAIN).conf $(KELVIONTECH_DIR)/nginx/conf.d/$(DOMAIN).conf
	docker exec $(NGINX_CONTAINER) nginx -t
	docker exec $(NGINX_CONTAINER) nginx -s reload
	@echo "Live at https://$(DOMAIN)"

seed:
	$(COMPOSE) exec backend python -m app.seed
	$(COMPOSE) exec backend python -m app.scripts.seed_niche_templates

check:
	curl -sf http://127.0.0.1:8002/health && echo "backend: ok"
	curl -sfI http://127.0.0.1:3003 > /dev/null && echo "frontend: ok"
	docker exec $(NGINX_CONTAINER) wget -qO- http://172.17.0.1:8002/health && echo "backend reachable from nginx container: ok"
