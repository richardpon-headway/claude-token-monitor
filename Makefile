.PHONY: install run dev test build-ui install-launchagent uninstall-launchagent clean

# Python version for `uv sync`. uv resolves this via PATH (mise/homebrew/etc.)
# or downloads a managed standalone build if none is found.
PYTHON ?= 3.13

install:
	uv sync --python $(PYTHON)
	@if [ -f ui/package.json ]; then \
		cd ui && pnpm install; \
	else \
		echo "ui/package.json not present yet — skipping pnpm install"; \
	fi

run:
	uv run python -m daemon.main

dev:
	@echo "starting daemon (:47821) + vite dev (:5173 with /api proxy)"
	@(uv run python -m daemon.main 2>&1 | sed 's/^/[daemon] /') & \
	 (cd ui && pnpm dev 2>&1 | sed 's/^/[vite]   /') & \
	 wait

test:
	uv run pytest tests/ -v

build-ui:
	@if [ ! -f ui/package.json ]; then \
		echo "ui/package.json not present yet — nothing to build"; \
	else \
		cd ui && pnpm build && cd .. && rm -rf daemon/static && cp -r ui/dist daemon/static; \
	fi

install-launchagent:
	@echo "TODO — out of v1 scope (use 'make run' for now)"

uninstall-launchagent:
	@echo "TODO"

clean:
	rm -rf daemon/static ui/dist .venv ui/node_modules
