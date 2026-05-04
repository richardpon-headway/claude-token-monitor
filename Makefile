.PHONY: install run dev test build-ui install-launchagent uninstall-launchagent clean

# Default python for `uv sync`. Pinned to the Homebrew binary because the
# pyenv shim hangs uv interpreter discovery on this machine. Override on
# non-macOS dev boxes: `make install PYTHON=python3.13`.
PYTHON ?= /opt/homebrew/bin/python3.13

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
	@echo "TODO: run daemon + vite dev server in parallel"
	@echo "(vite isn't scaffolded yet — use 'make run' until then)"

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
