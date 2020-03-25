# Entregas

Pequeña aplicación web para que los alumnos hagan las entregas de TPs.

## Ejecución

- Crear el ambiente virtual e instalar los requerimientos:

        $ pyton3 -m venv venv
        $ venv/bin/pip3 install -r requirements.txt

- Copiar el archivo `config-sample.py` a `config.py` y completarlo:

    * `SPREADSHEET_ID` es el id de la planilla.
    * `RECAPTCHA_*` son credenciales de [recaptcha](https://www.google.com/recaptcha/admin).
    * `ENTREGAS` es un diccionario en el que se especifican las entregas
      que se muestran en el dropdown.


## Correr local

- Es suficiente con correr Flask desde el directorio _venv:_

        $ FLASK_ENV=development venv/bin/flask run


## Habilitar una entrega

- Para habilitar una entrega:

	- Abrir `config.py` en `/srv/algo2/entregas/repo`
	- Descomentar la entrega que queremos habilitar
	- Reiniciar la app con `touch entregas2.ini` en `/srv/algo2/entregas`


## Actualización de dependencias (directas e indirectas)

Las dependencias directas de la aplicación se listan en el archivo `deps.txt`.
En dicho archivo se especifica también la versión a usar. Para actualizar todas
las bibliotecas a su última versión, manteniendo compatibilidad con las
versiones en _deps.txt_, se debe:

1.  crear un nuevo _virtualenv_:

        $ rm -rf venv
        $ python3 -m venv venv

2.  reinstalar el software a partir de _deps.txt:_

        $ venv/bin/pip3 install -r deps.txt

3.  una vez verificado que la aplicación sigue funcionando, actualizar el
    archivo `requirements.txt` con las nuevas versiones:

        $ venv/bin/pip3 freeze >requirements.txt

Si se desea actualizar alguna dependencia directa a una versión superior (p.ej.
_1.2 → 1.3_ o _1.3 → 2.0_), se debe actualizar el archivo _deps.txt,_ y
entonces realizar los tres pasos descritos.
