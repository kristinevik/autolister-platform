# Developer entry points. CI runs `make install check`; `make help` lists targets.

SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

PYTHON ?= python3
VENV := .venv
BIN := $(CURDIR)/$(VENV)/bin
PACKAGES := libs/core services/engine services/signer
SERVICES := engine signer
IMAGE_TAG ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo dev)
PIP_COMPILE := $(BIN)/pip-compile --quiet --generate-hashes --allow-unsafe --strip-extras --resolver=backtracking
export PIP_DISABLE_PIP_VERSION_CHECK := 1

.PHONY: help install hooks fmt lint typecheck test check lock images tf-check clean

help: ## List the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

# The lock is the complete set of dependencies, so pip installs exactly that
# (--no-deps) and `pip check` then proves it is consistent.
$(VENV)/.installed: requirements-dev.txt
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --quiet --require-hashes --no-deps -r requirements-dev.txt
	$(BIN)/pip install --quiet --no-deps --no-build-isolation $(addprefix -e ,$(PACKAGES))
	$(BIN)/pip check
	touch $@

install: $(VENV)/.installed ## Create .venv: the locked toolchain and every package, editable

hooks: install ## Run the pre-commit checks on every commit
	$(BIN)/pre-commit install

fmt: install ## Format the code
	$(BIN)/isort .
	$(BIN)/black .

lint: install ## Check formatting and lint
	$(BIN)/black --check .
	$(BIN)/isort --check-only .
	$(BIN)/flake8

typecheck: install ## Type-check every package (mypy, strict)
	$(BIN)/mypy

test: install ## Run each package's tests, with coverage
	for package in $(PACKAGES); do \
		echo "== $$package"; \
		(cd $$package && $(BIN)/pytest --cov); \
	done

check: lint typecheck test ## Everything CI checks, except Terraform

lock: install ## Pin dependencies after editing a requirements.in (UPGRADE=1 takes newer versions)
	$(PIP_COMPILE) $(if $(UPGRADE),--upgrade) services/signer/requirements.in
	$(PIP_COMPILE) $(if $(UPGRADE),--upgrade) services/engine/requirements.in
	$(PIP_COMPILE) $(if $(UPGRADE),--upgrade) requirements-dev.in

images: ## Build both container images
	for service in $(SERVICES); do \
		docker build --file services/$$service/Dockerfile --tag autolister-$$service:$(IMAGE_TAG) .; \
	done

tf-check: ## Check the Terraform's formatting and validity (needs no cloud access)
	terraform -chdir=infra/terraform fmt -check -recursive
	terraform -chdir=infra/terraform init -backend=false -input=false > /dev/null
	terraform -chdir=infra/terraform validate

clean: ## Remove the virtualenv and every cache
	rm -rf $(VENV) .mypy_cache
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .hypothesis \
		-o -name '*.egg-info' \) -prune -exec rm -rf {} +
	find . -name .coverage -delete
