# -*- coding: utf-8 -*-

"""
Constructor de JSON ACECF (Aprobacion Comercial e-CF) para DGII
Este modulo convierte filas de Excel a formato JSON para enviar a la API
"""

import math
from typing import Any, Dict, Optional
from datetime import datetime


# ============================================================================
# UTILIDADES PARA LECTURA DE EXCEL
# ============================================================================

EMPTY_MARKERS = {"#e", "#E", "NULL", "null", ""}


def is_empty(v: Any) -> bool:
    """Verifica si un valor se considera vacio"""
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    if isinstance(v, str) and v.strip() in EMPTY_MARKERS:
        return True
    return False


def clean_value(v: Any) -> Any:
    """Limpia un valor eliminando espacios y convirtiendo marcadores vacios a None"""
    if is_empty(v):
        return None
    return v.strip() if isinstance(v, str) else v


def get(row: Dict, col: str) -> Any:
    """
    Obtiene un valor de un diccionario, limpiandolo.
    Maneja variaciones comunes en nombres de columna (espacios, case).
    """
    # Intento directo
    if col in row:
        return clean_value(row[col])

    # Intento con espacios al final (comun en Excel)
    if f"{col} " in row:
        return clean_value(row[f"{col} "])

    # Intento con espacios al inicio
    if f" {col}" in row:
        return clean_value(row[f" {col}"])

    # Intento case-insensitive (solo si el nombre es exacto)
    col_lower = col.lower()
    for key in row:
        if key and isinstance(key, str) and key.lower() == col_lower:
            return clean_value(row[key])

    return None


def add_if(d: Dict[str, Any], key: str, value: Any) -> None:
    """Agrega una clave al diccionario solo si el valor no es None"""
    if value is not None:
        d[key] = value


def format_monto(value: Any) -> Optional[str]:
    """Formatea un monto a string, eliminando .0 si es entero"""
    if value is None:
        return None
    try:
        num = float(value)
        if num == int(num):
            return str(int(num))
        return str(num)
    except (ValueError, TypeError):
        return str(value) if value else None


def format_estado(value: Any) -> Optional[str]:
    """Formatea el estado a string"""
    if value is None:
        return None
    try:
        num = int(float(value))
        return str(num)
    except (ValueError, TypeError):
        return str(value) if value else None


# ============================================================================
# CONSTRUCCION DE JSON ACECF
# ============================================================================


def build_acecf_json(row: Dict) -> Dict[str, Any]:
    """
    Construye el JSON del ACECF completo desde una fila del Excel

    Estructura esperada del Excel (hoja ACEECF_Generadas):
    - Version
    - RNCEmisor
    - eNCF
    - FechaEmision
    - MontoTotal
    - RNCComprador
    - Estado
    - DetalleMotivoRechazo (opcional)
    - FechaHoraAprobacionComercial

    Estructura JSON de salida:
    {
        "ACECF": {
            "DetalleAprobacionComercial": {
                "Version": "1.0",
                "RNCEmisor": "131880681",
                "eNCF": "E310000000001",
                "FechaEmision": "01-04-2020",
                "MontoTotal": "7080",
                "RNCComprador": "131037879",
                "Estado": "1",
                "FechaHoraAprobacionComercial": "15-01-2026 12:05:21"
            },
            "_xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "_xmlns:xsd": "http://www.w3.org/2001/XMLSchema"
        }
    }
    """
    detalle: Dict[str, Any] = {}

    # Version (requerido)
    detalle["Version"] = get(row, "Version") or "1.0"

    # RNCEmisor (requerido)
    add_if(detalle, "RNCEmisor", get(row, "RNCEmisor"))

    # eNCF (requerido)
    encf = get(row, "eNCF") or get(row, "ENCF")
    add_if(detalle, "eNCF", encf)

    # FechaEmision (requerido, formato DD-MM-YYYY)
    add_if(detalle, "FechaEmision", get(row, "FechaEmision"))

    # MontoTotal (requerido, como string)
    monto_total = get(row, "MontoTotal")
    add_if(detalle, "MontoTotal", format_monto(monto_total))

    # RNCComprador (requerido)
    add_if(detalle, "RNCComprador", get(row, "RNCComprador"))

    # Estado (requerido, 1=Aprobado, 2=Rechazado)
    estado = get(row, "Estado")
    add_if(detalle, "Estado", format_estado(estado))

    # DetalleMotivoRechazo (opcional, solo si Estado=2)
    detalle_motivo = get(row, "DetalleMotivoRechazo")
    if detalle_motivo:
        add_if(detalle, "DetalleMotivoRechazo", detalle_motivo)

    # FechaHoraAprobacionComercial (requerido, formato DD-MM-YYYY HH:MM:SS)
    fecha_hora = get(row, "FechaHoraAprobacionComercial")
    if not fecha_hora:
        fecha_hora = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    add_if(detalle, "FechaHoraAprobacionComercial", fecha_hora)

    # Construir estructura completa ACECF
    acecf = {
        "ACECF": {
            "DetalleAprobacionComercial": detalle,
            "_xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "_xmlns:xsd": "http://www.w3.org/2001/XMLSchema"
        }
    }

    return acecf


def build_acecf_list_json(rows: list) -> list:
    """
    Construye una lista de JSONs ACECF desde multiples filas del Excel

    Args:
        rows: Lista de diccionarios, cada uno representando una fila del Excel

    Returns:
        Lista de diccionarios JSON ACECF
    """
    result = []
    for row in rows:
        try:
            acecf_json = build_acecf_json(row)
            result.append(acecf_json)
        except Exception as e:
            # Log el error pero continua con las demas filas
            import logging
            _logger = logging.getLogger(__name__)
            _logger.warning(f"Error al construir ACECF JSON: {e}")
            continue
    return result
