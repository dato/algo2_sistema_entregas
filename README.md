# Entregas

Pequeña aplicación web para que los alumnos hagan las entregas de TPs.


## Configuración

- Verificar que los campos `cuatri` y `spreadsheet_id` están actualizados
  en _entregas.yml_.

- Copiar el archivo _.secrets.template_ a _.secrets_ y completarlo:

    * `OAUTH_*` son nuestras credenciales de Google para enviar mail.
    * `RECAPTCHA_*` son credenciales de [reCAPTCHA](https://www.google.com/recaptcha/admin).

- Habilitar las entregas apropiadas en _entregas.yml_.

## Ejecución local

- Crear el ambiente virtual e instalar los requerimientos:

        $ pipenv install --ignore-pipfile

- Es suficiente con correr Flask desde el entorno creado por _[pipenv]:_

        $ pipenv shell
        $ FLASK_ENV=development flask run

  O se puede usar `pipenv run` si no se desea modificar el shell:

        $ FLASK_ENV=development pipenv run flask run

[pipenv]: https://pipenv.pypa.io/en/stable/

## Deploy

Para instalar en el server, usar el comando `pipenv sync` con una variable de entorno que indique que el _virtualenv_ se debe crear en una ubicación predecible, _.venv_ (por omisión, _pipenv_ usa un hash digest de las dependencias para nombrar el entorno):

    $ PIPENV_VENV_IN_PROJECT=1 pipenv install --deploy

El fichero de configuración de uWSGI especificará entonces:

    virtualenv = %d/.venv

### Habilitar una entrega

- Para habilitar una entrega:

	- Abrir `entregas.yml` en `/srv/algo2/entregas/repo`
	- Mover la entrega de manera que quede dentro del campo _entregas_
	- Reiniciar la app con `touch entregas2.ini` en `/srv/algo2/entregas`


## Actualización de dependencias (directas e indirectas)

Las dependencias directas de la aplicación se listan en el archivo [Pipfile](Pipfile), junto con la versión a usar. Se pueden actualizar todas las bibliotecas a su última versión compatible con `pipenv update`.

Si se desea actualizar alguna dependencia directa a una versión superior (p.ej., _urlfetch_), se puede hacer `pipenv install "urlfetch==1.2.*"` o similar.
