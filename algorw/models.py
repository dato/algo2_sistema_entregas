from itertools import islice
from logging import getLogger
from typing import ClassVar, List, Optional, Sequence, Type

from pydantic import BaseModel, EmailStr, ValidationError


__all__ = [
    "Model",
    "Alumne",
    "Docente",
    "parse_rows",
]


class Model(BaseModel):
    """Clase base para los objetos leídos de una planilla.

    Esta clase define solamente la presencia de un variable de clase
    COLUMNAS, que indica siempre el nombre de las columnas donde se
    alojan los atributos del modelo.
    """

    COLUMNAS: ClassVar[Sequence[str]]


class Docente(Model):
    # https://pydantic-docs.helpmanual.io/usage/models/#field-ordering
    nombre: str
    correo: EmailStr
    github: Optional[str]

    COLUMNAS: ClassVar = ("Nombre", "Mail", "Github")


class Alumne(Model):
    legajo: str
    nombre: str
    correo: EmailStr
    github: Optional[str]
    grupo: Optional[str]
    ayudante_indiv: Optional[Docente]
    ayudante_grupal: Optional[Docente]

    # Deben cubrir todos los campos obligatorios, en el mismo orden.
    COLUMNAS: ClassVar = ("Padrón", "Alumno", "Email", "Github")


def parse_rows(rows: List[List[str]], model: Type[Model]) -> List[Model]:
    """Construye objetos de una clase modelo a partir de filas de planilla.

    Argumentos:
      rows: lista de filas de la hoja. Se asume que la primera fila
          son los nombres de las columnas.
      model: Model con que construir los objetos, usando model.COLUMNAS
          como origen (ordenado) de los atributos.

    Returns:
      una lista de los objetos construidos.
    """
    logger = getLogger(__name__)
    fields = model.__fields__.keys()
    indices = []
    objects = []
    headers = rows[0]

    for field in model.COLUMNAS:
        indices.append(headers.index(field))

    for row in islice(rows, 1, None):
        attrs = {field: _safeidx(row, idx) for field, idx in zip(fields, indices)}
        try:
            objects.append(model.parse_obj(attrs))
        except ValidationError as ex:
            errors = ex.errors()
            failed = ", ".join(e["loc"][0] for e in errors)
            logger.warn(ex)
            logger.warn(f"ValidationError: {failed} in {attrs}")

    return objects


def _safeidx(lst, i):
    """Devuelve el índice i-ésimo (columna i-ésima)d e una lista (fila).

    Si la lista no tiene el tamaño suficiente, o contiene la cadena vacía,
    se devuelve None.
    """
    return None if i >= len(lst) or lst[i] == "" else lst[i]
