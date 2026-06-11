VENV := .venv/bin
SLIDESONNET := $(VENV)/slidesonnet

.PHONY: install test test-unit lint fmt typecheck clean \
	demos basel showcase \
	check-basel check-showcase \
	clean-basel clean-showcase clean-examples \
	purge-examples

install:
	$(VENV)/pip install -e ".[kokoro,dev]"

test:
	$(VENV)/pytest tests/

test-unit:
	$(VENV)/pytest tests/ -m "not integration"

lint:
	$(VENV)/ruff check src/ tests/
	$(VENV)/ruff format --check src/ tests/

fmt:
	$(VENV)/ruff format src/ tests/

typecheck:
	$(VENV)/mypy src/slidesonnet/

# --- Demos: compile the Beamer PDF, then render with Kokoro ---
# Each example ships a committed PDF, so rendering works without recompiling;
# these targets recompile from source for a from-scratch rebuild.

examples/basel-problem/basel-problem.pdf: examples/basel-problem/basel-problem.tex
	$(SLIDESONNET) sty -o examples/basel-problem/slidesonnet.sty
	cd examples/basel-problem && latexmk -pdf -interaction=nonstopmode basel-problem.tex

basel: examples/basel-problem/basel-problem.pdf
	$(SLIDESONNET) export examples/basel-problem/basel-problem.pdf \
		-o examples/basel-problem/basel-problem.mp4 --engine kokoro

check-basel:
	$(SLIDESONNET) check examples/basel-problem/basel-problem.pdf

examples/showcase/showcase.pdf: examples/showcase/showcase.tex
	$(SLIDESONNET) sty -o examples/showcase/slidesonnet.sty
	cd examples/showcase && latexmk -pdf -interaction=nonstopmode showcase.tex

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
	rm -rf dist/ *.egg-info/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .slidesonnet -exec rm -rf {} + 2>/dev/null || true
