# Entregas

Pequeña aplicación web para que los alumnos hagan las entregas de TPs.

## Ejecución

- Crear el ambiente virtual e instalar los requerimientos:

    - `python3 -m venv .`
    - `pip install -r requirements.txt`

- Copiar el archivo `config-sample.py` a `config.py` y completarlo:
    * `SPREADSHEET_ID` es el id de la planilla.
    * `RECAPTCHA_*` son credenciales de [recaptcha](https://www.google.com/recaptcha/admin).
    * `ENTREGAS` es un diccionario en el que se especifican las entregas
    que se muestran en el dropdown.

## Correr local

- Activar el ambiente y ejecutar flask:

    - `source bin/activate`
    - `FLASK_APP=main.py flask run`