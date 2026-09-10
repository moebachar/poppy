start:
	source venv/bin/activate
	npm run build
	python3 ./web/server.py

first-launch:
	python3 -m venv venv
	npm install web/ui/package.json
	start