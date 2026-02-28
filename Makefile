VENV := .venv/bin
SLIDESONNET := $(VENV)/slidesonnet

.PHONY: install test test-unit lint typecheck clean \
	showcase showcase-piper \
	basel basel-piper \
	basel-he basel-he-piper \
	clean-showcase clean-basel clean-basel-he clean-examples

install:
	$(VENV)/pip install -e ".[piper,dev]"

test:
	$(VENV)/pytest tests/

test-unit:
	$(VENV)/pytest tests/ -m "not integration"

lint:
	$(VENV)/ruff check src/ tests/
	$(VENV)/ruff format --check src/ tests/

typecheck:
	$(VENV)/mypy src/slidesonnet/

# --- Examples: showcase ---
showcase:
	cd examples/showcase && ../../$(SLIDESONNET) build lecture.md

showcase-piper:
	cd examples/showcase && ../../$(SLIDESONNET) build lecture.md --tts piper

clean-showcase:
	cd examples/showcase && ../../$(SLIDESONNET) clean lecture.md

# --- Examples: basel-problem ---
basel:
	cd examples/basel-problem && ../../$(SLIDESONNET) build lecture.md

basel-piper:
	cd examples/basel-problem && ../../$(SLIDESONNET) build lecture.md --tts piper

clean-basel:
	cd examples/basel-problem && ../../$(SLIDESONNET) clean lecture.md

# --- Examples: basel-problem-he ---
basel-he:
	cd examples/basel-problem-he && ../../$(SLIDESONNET) build lecture.md

basel-he-piper:
	cd examples/basel-problem-he && ../../$(SLIDESONNET) build lecture.md --tts piper

clean-basel-he:
	cd examples/basel-problem-he && ../../$(SLIDESONNET) clean lecture.md

# --- Aggregate ---
clean-examples: clean-showcase clean-basel clean-basel-he

clean:
	rm -rf cache/ dist/ *.egg-info/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
