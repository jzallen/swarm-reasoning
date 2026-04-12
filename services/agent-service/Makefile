.PHONY: validate validate-unit validate-up validate-down

COMPOSE_FILE := ../../docs/infrastructure/docker-compose.yml
COMPOSE := docker compose -f $(COMPOSE_FILE)

# Run the full validation harness against a live stack
validate: validate-up
	@echo "Waiting for stack to become healthy..."
	@sleep 10
	python -m pytest tests/validation/ -v --tb=short -m integration || \
		($(COMPOSE) down && exit 1)
	$(COMPOSE) down
	@echo "Validation complete."

# Run only unit tests (no infrastructure required)
validate-unit:
	python -m pytest tests/validation/ -v --tb=short -m "not integration"

# Start infrastructure for validation
validate-up:
	$(COMPOSE) up -d
	@echo "Infrastructure started."

# Stop infrastructure
validate-down:
	$(COMPOSE) down
	@echo "Infrastructure stopped."
