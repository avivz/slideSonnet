VENV := .venv/bin
SLIDESONNET := $(VENV)/slidesonnet

.PHONY: install test test-unit test-fast test-browser lint fmt typecheck clean \
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

# Full unit tier (CI's tier). The in-process GUI tests dominate (~90 s); they
# don't parallelize (xdist gives no speedup — see CLAUDE.md), so this is serial.
test-unit:
	$(VENV)/pytest tests/ -m "not integration and not browser"

# Fast inner loop (~16 s): skip the slow in-process GUI tests. Run test-unit before pushing.
test-fast:
	$(VENV)/pytest tests/ -m "not integration and not browser and not gui"

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

frontend: frontend-deps
	cd $(FRONTEND) && npm run build

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
	$(VENV)/python -m slidesonnet.server.openapi > $(FRONTEND)/openapi.json
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
	find . -type d -name .slidesonnet -exec rm -rf {} + 2>/dev/null || true
