start:
	dev_appserver.py $(PWD)

deploy:
	gcloud app deploy --project algoritmos2rw --verbosity=info app.yaml

.PHONY: start deploy
