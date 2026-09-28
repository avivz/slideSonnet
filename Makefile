VENV := .venv/bin
SLIDESONNET := $(VENV)/slidesonnet

.PHONY: install test test-unit test-browser lint fmt typecheck clean \
	frontend frontend-deps frontend-dev test-frontend lint-frontend api-types check-api-types \
	demos basel showcase \
	check-basel check-showcase \
	clean-basel clean-showcase clean-examples \
	purge-examples

install:
	$(VENV)/pip install -e ".[kokoro,dev]"
	@if command -v npm >/dev/null; then $(MAKE) frontend; \
	else echo "note: npm not found — the editor's browser interface isn't built (make frontend)"; fi

test:
	$(VENV)/pytest tests/

# The unit tier (CI's tier): Python unit + API tests, ~25 s.
test-unit:
	$(VENV)/pytest tests/ -m "not integration and not browser"

# Real-browser editor journeys against the built frontend (local only).
test-browser: frontend
	$(VENV)/pytest tests/ -m browser

# --- Frontend (Vue + TypeScript, in frontend/) ---
# The build lands in src/slidesonnet/server/static/, which the Python package
# ships; installing a wheel or sdist never needs Node.
FRONTEND := frontend

$(FRONTEND)/node_modules: $(FRONTEND)/package-lock.json
	cd $(FRONTEND) && npm ci
	touch $@

frontend-deps: $(FRONTEND)/node_modules

STATIC := src/slidesonnet/server/static

# Builds beside the folder a running editor serves, then swaps it in: an editor
# left running never sends a half-written file (a reload picks the new build up).
frontend: frontend-deps
	cd $(FRONTEND) && npx vue-tsc -b && npx vite build --outDir ../$(STATIC).next --emptyOutDir
	rm -rf $(STATIC).old
	if [ -d $(STATIC) ]; then mv $(STATIC) $(STATIC).old; fi
	mv $(STATIC).next $(STATIC)
	rm -rf $(STATIC).old

# Vite on :5173 with hot reload, proxying /api, /ssmedia and the editor to a
# running `slidesonnet edit --no-browser` on :8080.
frontend-dev: frontend-deps
	cd $(FRONTEND) && npm run dev

test-frontend: frontend-deps
	cd $(FRONTEND) && npm test

lint-frontend: frontend-deps
	cd $(FRONTEND) && npm run lint && npm run typecheck

# Regenerate the TypeScript API types from the server's OpenAPI schema.
api-types: frontend-deps
	$(VENV)/python -m slidesonnet.server.openapi $(FRONTEND)/openapi.json
	cd $(FRONTEND) && npm run api-types

# CI: fail when the committed API types no longer match the server.
check-api-types: api-types
	git diff --exit-code -- $(FRONTEND)/openapi.json $(FRONTEND)/src/api/schema.d.ts

lint:
	$(VENV)/ruff check src/ tests/
	$(VENV)/ruff format --check src/ tests/

fmt:
	$(VENV)/ruff format src/ tests/

typecheck:
	$(VENV)/mypy src/slidesonnet/

# --- Demos: compile the Beamer PDF, then render with Kokoro ---
# Each example ships a committed PDF, so rendering works without recompiling;
# these targets recompile from source for a from-scratch rebuild — as *final*
# builds (\ssfinal), so page numbers and progress bars appear in the video.

examples/basel-problem/basel-problem.pdf: examples/basel-problem/basel-problem.tex
	$(SLIDESONNET) sty -o examples/basel-problem/slidesonnet.sty
	cd examples/basel-problem && latexmk -pdf -interaction=nonstopmode -usepretex='\def\ssfinal{}' basel-problem.tex

basel: examples/basel-problem/basel-problem.pdf
	$(SLIDESONNET) export examples/basel-problem/basel-problem.pdf \
		-o examples/basel-problem/basel-problem.mp4 --engine kokoro

check-basel:
	$(SLIDESONNET) check examples/basel-problem/basel-problem.pdf

examples/showcase/showcase.pdf: examples/showcase/showcase.tex
	$(SLIDESONNET) sty -o examples/showcase/slidesonnet.sty
	cd examples/showcase && latexmk -pdf -interaction=nonstopmode -usepretex='\def\ssfinal{}' showcase.tex

showcase: examples/showcase/showcase.pdf
	$(SLIDESONNET) export examples/showcase/showcase.pdf \
		-o examples/showcase/showcase.mp4 --engine kokoro

check-showcase:
	$(SLIDESONNET) check examples/showcase/showcase.pdf

demos: basel showcase

# --- Cleanup ---
clean-basel:
	$(SLIDESONNET) clean examples/basel-problem/basel-problem.pdf

clean-showcase:
	$(SLIDESONNET) clean examples/showcase/showcase.pdf

clean-examples: clean-basel clean-showcase

purge-examples:
	$(SLIDESONNET) clean examples/basel-problem/basel-problem.pdf --keep nothing -y
	$(SLIDESONNET) clean examples/showcase/showcase.pdf --keep nothing -y

clean:
	rm -rf dist/ *.egg-info/ src/slidesonnet/server/static/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@# every deck cache goes, except its review base (not regenerable: what was already seen)
	find . -type d -name .slidesonnet -prune -exec sh -c 'for d; do find "$$d" -mindepth 1 -maxdepth 1 ! -name review -exec rm -rf {} +; rmdir "$$d" 2>/dev/null || true; done' _ {} + 2>/dev/null || true
