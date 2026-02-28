VENV := .venv/bin

.PHONY: install test test-unit lint typecheck clean showcase showcase-piper

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

showcase:
	cd examples/showcase && ../../$(VENV)/slidesonnet build lecture.md

showcase-piper:
	cd examples/showcase && ../../$(VENV)/slidesonnet build lecture.md --tts piper

clean:
	rm -rf .build/ dist/ *.egg-info/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
