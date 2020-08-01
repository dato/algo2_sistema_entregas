import threading

from dataclasses import dataclass
from typing import Dict, List

from googleapiclient import discovery  # type: ignore


__all__ = ["Config", "PullDB"]


@dataclass
class Config:
    spreadsheet_id: str
    credentials: Dict
    sheet_list: List[str]


class PullDB:
    """Clase para descargar hojas de Google Sheets.
    """

    def __init__(self, cfg: Config, /, *, initial_fetch=False):
        self._cfg = cfg
        self._lock = threading.Lock()
        self.__data = None

        if initial_fetch:
            self.refresh()

    @property
    def data(self):
        return self.get()

    def get(self, *, refresh=False):
        """
        """
        if refresh or self.__data is None:
            self.refresh()
        return self.__data

    def refresh(self):
        """Descarga de Google las hojas que fueron configuradas en el constructor.

        Si ya habían sido descargadas, se remplazan los datos anteriores con los nuevos.
        """
        service = discovery.build("sheets", "v4", credentials=self._cfg.credentials)
        spreadsheets = service.spreadsheets()
        query = spreadsheets.values().batchGet(
            spreadsheetId=self._cfg.spreadsheet_id,
            ranges=self._cfg.sheet_list,
            valueRenderOption="UNFORMATTED_VALUE",
        )
        result = query.execute()
        sheets = parse_sheets(result["valueRanges"])
        new_data = self.parse_sheets(sheets)
        if new_data is not None:
            with self._lock:
                self.__data = new_data

    def parse_sheets(self, sheet_dict):
        """
        """
        raise NotImplementedError


def parse_sheets(sheet_ranges: List[Dict]) -> Dict[str, List[List[str]]]:
    """Segrega por hoja la lista de rango/valores obtenidos.

    Args:
      sheet_ranges: el resultado "valueRanges" de batchGet(), esto es,
          una lista de diccionarios con las celdas de cada hoja.

    Returns:
      un diccionario con los valores asociados a cada hoja.
    """
    hojas_dict = {}

    for sheet_data in sheet_ranges:
        sheet_rows = sheet_data["values"]
        sheet_name, _ = sheet_data["range"].split("!", 1)
        hojas_dict[sheet_name] = sheet_rows

    return hojas_dict
