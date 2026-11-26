# Commandes essentielles de la console de gouvernance. `make` affiche l'aide.
SHELL := /bin/bash
.DEFAULT_GOAL := help
COMPOSE := docker compose
PREFIX  := /opt/claude-governance
S       ?=            # services ciblés, ex. : make logs S=proxy

.PHONY: help up down restart rebuild rebuild-proxy rebuild-admin ps logs health smoke test hooks trusted install

help: ## Affiche cette aide
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[1;34m%-15s\033[0m %s\n", $$1, $$2}'
	@echo "  Option : S=\"proxy admin\" pour cibler des services (up, restart, rebuild, logs)"

up: ## Démarre la stack (ou les services S)
	$(COMPOSE) up -d $(S)

down: ## Arrête la stack (les volumes sont conservés)
	$(COMPOSE) down

restart: ## Redémarre sans rebuild (relit le .env)
	$(COMPOSE) up -d --force-recreate $(S)

rebuild: ## Reconstruit et relance (tout, ou les services S)
	$(COMPOSE) up -d --build $(S)

rebuild-proxy: ## Reconstruit et relance le proxy (coupe brièvement les sessions Claude)
	$(COMPOSE) up -d --build proxy

rebuild-admin: ## Reconstruit et relance la console d'administration
	$(COMPOSE) up -d --build admin

ps: ## État des conteneurs
	$(COMPOSE) ps

logs: ## Suit les logs (proxy par défaut, ou S)
	$(COMPOSE) logs -f --tail=100 $(or $(S),proxy)

health: ## Vérifie que le proxy répond
	@curl -fsS http://127.0.0.1:8787/healthz && echo || { echo "proxy injoignable"; exit 1; }

smoke: ## Vérification de bout en bout
	./scripts/smoke-test.sh

test: ## Lance les tests pytest
	python3 -m pytest -q tests

hooks: ## Redéploie hooks + politique dans /opt/claude-governance (sans toucher à Docker)
	sudo install -d -m 755 $(PREFIX)/hooks $(PREFIX)/policy
	sudo install -m 644 proxy/app/pii.py hooks/common.py $(PREFIX)/hooks/
	sudo install -m 755 hooks/guard_prompt.py hooks/guard_tool.py hooks/audit.py hooks/statusline.py $(PREFIX)/hooks/
	sudo install -m 644 policy/policy.json $(PREFIX)/policy/policy.json

trusted: ## Affiche le fournisseur de confiance configuré dans le proxy (sans la clé)
	@$(COMPOSE) exec proxy sh -c 'echo "nom : $${TRUSTED_NAME:-(défaut)}"; echo "url : $${TRUSTED_URL:-(non défini)}"; echo "modèle : $${TRUSTED_MODEL:-(non défini)}"'

install: ## Installation complète (./install.sh)
	./install.sh
