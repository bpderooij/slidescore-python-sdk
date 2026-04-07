.PHONY: install install-dev build publish publish-test test clean

install:
	uv pip install -e .

install-dev:
	uv pip install -e ".[dev,numpy]"

build:
	uv build

publish: build
	uv publish

publish-test: build
	uv publish --publish-url https://test.pypi.org/legacy/

test:
	uv run pytest tests/

clean:
	rm -rf dist build *.egg-info
