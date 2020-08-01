import logging

from enum import Enum
from itertools import islice
from typing import Dict, List

from .models import Alumne, Docente, parse_rows
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
        self._alulist = parse_rows(sheet_dict[Hojas.Alumnes], Alumne)

        # Diccionario de docentes (indexados por nombre).
        self._docentes = {
            d.nombre: d for d in parse_rows(sheet_dict[Hojas.Docentes], Docente)
        }

        # _alulist_by_id es un diccionario que incluye como claves todos
        # los legajos, y todos los identificadores de grupo. Los valores
        # son siempre *listas* de objetos Alumne.
        self._alulist_by_id = self._parse_notas(sheet_dict[Hojas.Notas])

        # correctores es un diccionario que mapea:
        #
        #  • legajo ("98765") a corrector individual
        #  • identificador de grupo ("G07") a corrector grupal
        #  • 'g' + legajo (p.ej. "g98765") a su corrector grupal correspondiente
        #
        # Esto último se usa en las validaciones Javascript en el navegador.
        self._correctores = {alu.grupo: alu.ayudante_grupal for alu in self._alulist}
        self._correctores = {alu.legajo: alu.ayudante_indiv for alu in self._alulist}
        self._correctores.update(
            {f"g{alu.legajo}": alu.ayudante_grupal for alu in self._alulist}
        )

    @property
    def correctores(self) -> Dict[str, str]:
        # Compatibilidad con la antigua planilla. (Se incluye solo el nombre del
        # ayudante, y se filtran asignaciones nulas.)
        return {k: v.nombre for k, v in self._correctores.items() if v is not None}

    def get_alulist(self, identificador: str) -> List[Alumne]:
        """Devuelve les alumnes para un identificador (grupo o legajo).

        Si el identificador es un legajo, devuelve una lista de un solo
        elemento. Se lanza KeyError si noexiste el identificador.
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
                alu.ayudante_indiv = self._docentes.get(row[ayudante_indiv])
                alu.ayudante_grupal = self._docentes.get(row[ayudante_grupal])
                if grupo := row[nro_grupo]:
                    alu.grupo = grupo
                    alulist_by_id.setdefault(grupo, []).append(alu)

        return alulist_by_id
