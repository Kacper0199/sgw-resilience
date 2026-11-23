.DEFAULT_GOAL := help
-include mk/*.mk

.PHONY: help
help:
	@uv run python -c "import re,glob;[print(f'  {m.group(1):<22} {m.group(2)}') for f in ['Makefile',*sorted(glob.glob('mk/*.mk'))] for m in re.finditer(r'^([a-zA-Z0-9_.-]+):.*?## (.*)$$', open(f).read(), re.M)]"
