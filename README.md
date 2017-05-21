# Entregas

Pequeña aplicación web para que los alumnos hagan las entregas de TPs.
Corre en Google App Engine.

## Instalación

Instalar [gcloud sdk](https://cloud.google.com/appengine/docs/standard/python/download)

## Correr local

`make start`

## Deploy

`make deploy`

## TODO

* Leer los datos de la planilla (emails de los docentes, asignaciones de TPs,
  emails de los alumnos).

* Agregar `reply_to: <email del alumno>` al enviar el mail.

* ¿Poner un captcha?
