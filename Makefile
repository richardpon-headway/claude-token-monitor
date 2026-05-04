.PHONY: install run dev build-ui install-launchagent uninstall-launchagent clean

install:
	uv sync
	cd ui && pnpm install

run:
	uv run python -m daemon.main

dev:
	@echo "TODO: run daemon + vite dev server in parallel"

build-ui:
	cd ui && pnpm build
	rm -rf daemon/static
	cp -r ui/dist daemon/static

install-launchagent:
	@echo "TODO"

uninstall-launchagent:
	@echo "TODO"

clean:
	rm -rf daemon/static ui/dist .venv ui/node_modules
