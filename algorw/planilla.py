import logging

from enum import Enum
from itertools import islice
from typing import Dict, List

from .models import Alumne, Docente, parse_rows, safeidx
from .sheets import PullDB


__all__ = [
    "Planilla",
]


class Hojas(str, Enum):
    Notas = "Notas"
    Alumnes = "DatosAlumnos"
    Docentes = "DatosDocentes"


class Planilla(PullDB):
    """Representación unificada de las varias hojas de nuestra planilla.

    Las hojas que se descargan y procesan son las del enum Hojas, arriba.
    """

    def parse_sheets(self, sheet_dict):
        self._logger = logging.getLogger("entregas")

        # Lista de Alumnes.
        self._alulist: List[Alumne] = parse_rows(sheet_dict[Hojas.Alumnes], Alumne)

        # Diccionario de docentes (indexados por nombre).
        self._docentes: Dict[str, Docente] = {
            d.nombre: d for d in parse_rows(sheet_dict[Hojas.Docentes], Docente)
        }

        # _alulist_by_id es un diccionario que incluye como claves todos
        # los legajos, y todos los identificadores de grupo. Los valores
        # son siempre *listas* de objetos Alumne.
        self._alulist_by_id = self._parse_notas(sheet_dict[Hojas.Notas])

        # correctores es un diccionario que se envía a index.html, y mapea
        # legajos a un arreglo con:
        #
        #  • corrector individual
        #  • corrector grupal
        #  • identificador de grupo (normalmente uno, o cero si es un grupo de
        #    una sola persona; podría haber más de uno si hubo rearme de grupos).
        #
        # Por ejemplo:
        #
        #  correctores = {"98765": ["Docente 1", "Docente 2", "G17"],
        #                 "54321": ["Docente 3"],
        #                 "12345": ["Docente 1", "Docente 3"],
        #  }
        self._correctores = {alu.legajo: [] for alu in self._alulist}

        for alu in self._alulist:
            for docente in (alu.ayudante_indiv, alu.ayudante_grupal):
                if docente:
                    self._correctores[alu.legajo].append(docente.nombre)
                else:
                    break
            else:
                if alu.grupo:
                    # TODO: extraer de la hoja Repos los casos con más de un grupo.
                    self._correctores[alu.legajo].append(alu.grupo)

    @property
    def correctores(self) -> Dict[str, List[str]]:
        return self._correctores.copy()

    def get_alu(self, legajo: str) -> Alumne:
        """Lookup de alumne  por legajo.

        Se lanza KeyError si no el legajo no está presente.
        """
        return self.get_alulist(legajo)[0]

    def get_alulist(self, identificador: str) -> List[Alumne]:
        """Devuelve les alumnes para un identificador (grupo o legajo).

        Si el identificador es un legajo, devuelve una lista de un solo
        elemento. Se lanza KeyError si no existe el identificador.
        """
        return self._alulist_by_id[identificador]

    def _parse_notas(self, rows) -> Dict[str, List[Alumne]]:
        """Construye el mapeo de identificadores a alumnes.

        Este método combina la planilla Notas con la lista de
        Alumnes, self._alulist, para construir (y devolver) el
        diccionario self._alulist_by_id, explicado arriba.
        """
        alulist_by_id = {x.legajo: [x] for x in self._alulist}
        headers = rows[0]
        padron = headers.index("Padrón")
        nro_grupo = headers.index("Nro Grupo")
        ayudante_indiv = headers.index("Ayudante")
        ayudante_grupal = headers.index("Ayudante grupo")

        for row in islice(rows, 1, None):
            if padron >= len(row) or not (legajo := row[padron]):
                continue
            try:
                (alu,) = alulist_by_id[str(legajo)]
            except KeyError:
                self._logger.warn(f"{legajo} aparece en Notas pero no en DatosAlumnos")
            else:
                alu.ayudante_indiv = self._docentes.get(safeidx(row, ayudante_indiv))
                alu.ayudante_grupal = self._docentes.get(safeidx(row, ayudante_grupal))
                if grupo := row[nro_grupo]:
                    alu.grupo = grupo
                    alulist_by_id.setdefault(grupo, []).append(alu)

        return alulist_by_id
