.PHONY: install test test-unit lint clean

install:
	pip install -e ".[piper,dev]"

test:
	pytest tests/

test-unit:
	pytest tests/ -m "not integration"

lint:
	ruff check src/ tests/
	ruff format --check src/ tests/

clean:
	rm -rf .build/ dist/ *.egg-info/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
