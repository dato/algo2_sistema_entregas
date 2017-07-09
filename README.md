# Entregas

Pequeña aplicación web para que los alumnos hagan las entregas de TPs.
Corre en Google App Engine.

## Instalación

* Instalar [gcloud sdk](https://cloud.google.com/appengine/docs/standard/python/download)

## Configuración

* En el proyecto de Google Cloud:
    * Activar "Drive API".
    * Ir a "Credentials > New Credentials > Service Account Key". Eso produce
      un archivo json que se usa en el siguiente paso.

* Copiar el archivo `config-sample.py` a `config.py` y completarlo:
    * `SPREADSHEET_ID` es el id de la planilla.
    * `SERVICE_ACCOUNT_CREDENTIALS` es el json generado arriba.
    * `RECAPTCHA_*` son credenciales de [recaptcha](https://www.google.com/recaptcha/admin).

* Compartir la planilla al email asociado con el Service Account (campo
  `client_email` del json).

## Correr local

`make start`

## Deploy

`make deploy`
