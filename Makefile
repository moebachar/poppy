root := $(shell pwd)

.PHONY: start first-launch

start:
	bash -c "source $(root)/venv/bin/activate && \
	cd $(root)/web/ui && \
	npm run build && \
	python3 $(root)/web/server.py"

first-launch:
	python3 -m venv ${root}/venv
	cd $(root)/web/ui && npm install
	$(MAKE) start