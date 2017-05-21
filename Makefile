start:
	dev_appserver.py $(PWD)

deploy:
	gcloud app deploy --project algoritmos1rw --verbosity=info app.yaml

.PHONY: start deploy
