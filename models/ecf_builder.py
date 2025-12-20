# -*- coding: utf-8 -*-

"""
Constructor de JSON e-CF siguiendo el script probado al 100% con DGII
Este módulo replica EXACTAMENTE la lógica del script Python que funciona
"""

import math
import re
from typing import Any, Dict, List, Optional
from datetime import datetime


# ============================================================================
# UTILIDADES PARA LECTURA DE EXCEL (del script probado)
# ============================================================================

EMPTY_MARKERS = {"#e", "#E", "NULL", "null", ""}


def is_empty(v: Any) -> bool:
    """Verifica si un valor se considera vacío"""
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    if isinstance(v, str) and v.strip() in EMPTY_MARKERS:
        return True
    return False


def clean_value(v: Any) -> Any:
    """Limpia un valor eliminando espacios y convirtiendo marcadores vacíos a None"""
    if is_empty(v):
        return None
    return v.strip() if isinstance(v, str) else v


def get(row: Dict, col: str) -> Any:
    """
    Obtiene un valor de un diccionario, limpiándolo.
    Maneja variaciones comunes en nombres de columna (espacios, case).
    """
    # Intento directo
    if col in row:
        return clean_value(row[col])

    # Intento con espacios al final (común en Excel)
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


def to_int(v: Any) -> Optional[int]:
    """Convierte un valor a entero de manera segura"""
    v = clean_value(v)
    if v is None:
        return None
    try:
        if isinstance(v, str) and re.fullmatch(r"-?\d+(\.0+)?", v):
            return int(float(v))
        return int(float(v))
    except Exception:
        return None


def collect_indexed(row: Dict, base: str, max_n: int = 10) -> List[Any]:
    """Recolecta valores indexados (ej: TelefonoEmisor[1], TelefonoEmisor[2], ...)"""
    out = []
    for i in range(1, max_n + 1):
        v = get(row, f"{base}[{i}]")
        if v is not None:
            out.append(v)
    return out


# ============================================================================
# CONSTRUCCIÓN DE ESTRUCTURAS JSON (del script probado)
# ============================================================================


def build_tabla_formas_pago(row: Dict, max_n: int = 7) -> Optional[Dict[str, Any]]:
    """Construye TablaFormasPago desde los datos del Excel"""
    formas = []
    for i in range(1, max_n + 1):
        forma = to_int(get(row, f"FormaPago[{i}]"))
        monto = get(row, f"MontoPago[{i}]")
        if forma is None and monto is None:
            continue
        obj = {}
        if forma is not None:
            obj["FormaPago"] = forma
        if monto is not None:
            obj["MontoPago"] = monto
        if obj:
            formas.append(obj)
    if not formas:
        return None
    return {"FormaDePago": formas}


def build_items(row: Dict, max_items: int = 50) -> List[Dict[str, Any]]:
    """Construye los Items/DetallesItems desde el Excel"""
    items = []
    for i in range(1, max_items + 1):
        num = to_int(get(row, f"NumeroLinea[{i}]"))
        if num is None:
            continue

        it = {}

        # 1. NumeroLinea (siempre primero)
        it["NumeroLinea"] = num

        # 2. TablaCodigosItem (tipos 46, 47) - ANTES de IndicadorFacturacion
        codigos_item = []
        for j in range(1, 10):
            tipo_codigo = get(row, f"TipoCodigo[{i}][{j}]")
            codigo = get(row, f"CodigoItem[{i}][{j}]")
            if tipo_codigo or codigo:
                cod = {}
                add_if(cod, "TipoCodigo", tipo_codigo)
                add_if(cod, "CodigoItem", codigo)
                if cod:
                    codigos_item.append(cod)
        if codigos_item:
            it["TablaCodigosItem"] = {"CodigosItem": codigos_item}

        # 3. IndicadorFacturacion
        indf = to_int(get(row, f"IndicadorFacturacion[{i}]"))
        if indf is not None:
            it["IndicadorFacturacion"] = indf

        # 4. Retencion (tipos 41, 47) - DESPUÉS de IndicadorFacturacion, ANTES de NombreItem
        indicador_ret = get(row, f"IndicadorAgenteRetencionoPercepcion[{i}]")
        monto_itbis_ret = get(row, f"MontoITBISRetenido[{i}]")
        monto_isr_ret = get(row, f"MontoISRRetenido[{i}]")
        if indicador_ret or monto_itbis_ret or monto_isr_ret:
            retencion = {}
            if indicador_ret is not None:
                retencion["IndicadorAgenteRetencionoPercepcion"] = to_int(indicador_ret) or indicador_ret
            add_if(retencion, "MontoITBISRetenido", monto_itbis_ret)
            add_if(retencion, "MontoISRRetenido", monto_isr_ret)
            if retencion:
                it["Retencion"] = retencion

        # 5. NombreItem
        add_if(it, "NombreItem", get(row, f"NombreItem[{i}]"))

        # 6. IndicadorBienoServicio
        ibs = to_int(get(row, f"IndicadorBienoServicio[{i}]"))
        if ibs is not None:
            it["IndicadorBienoServicio"] = ibs

        # 7. DescripcionItem (tipos 41, 45)
        add_if(it, "DescripcionItem", get(row, f"DescripcionItem[{i}]"))

        # 8. CantidadItem
        add_if(it, "CantidadItem", get(row, f"CantidadItem[{i}]"))

        # 9. UnidadMedida
        add_if(it, "UnidadMedida", get(row, f"UnidadMedida[{i}]"))

        # 10. PrecioUnitarioItem
        add_if(it, "PrecioUnitarioItem", get(row, f"PrecioUnitarioItem[{i}]"))

        # 11. DescuentoMonto + TablaSubDescuento
        descuento_monto = get(row, f"DescuentoMonto[{i}]")
        if descuento_monto:
            add_if(it, "DescuentoMonto", descuento_monto)

            sub_descuentos = []
            for j in range(1, 10):
                tipo_sub_desc = get(row, f"TipoSubDescuento[{i}][{j}]")
                monto_sub_desc = get(row, f"MontoSubDescuento[{i}][{j}]")
                porc_sub_desc = get(row, f"SubDescuentoPorcentaje[{i}][{j}]")

                # Solo para j=1: si MontoSubDescuento está vacío pero hay TipoSubDescuento, usar DescuentoMonto
                if j == 1 and tipo_sub_desc and not monto_sub_desc:
                    monto_sub_desc = descuento_monto

                if tipo_sub_desc or monto_sub_desc or porc_sub_desc:
                    sub_desc = {}
                    add_if(sub_desc, "TipoSubDescuento", tipo_sub_desc)
                    add_if(sub_desc, "SubDescuentoPorcentaje", porc_sub_desc)
                    add_if(sub_desc, "MontoSubDescuento", monto_sub_desc)
                    if sub_desc:
                        sub_descuentos.append(sub_desc)
            if sub_descuentos:
                it["TablaSubDescuento"] = {"SubDescuento": sub_descuentos}

        # 12. RecargoMonto + TablaSubRecargo
        recargo_monto = get(row, f"RecargoMonto[{i}]")
        if recargo_monto:
            add_if(it, "RecargoMonto", recargo_monto)

            sub_recargos = []
            for j in range(1, 10):
                tipo_sub_rec = get(row, f"TipoSubRecargo[{i}][{j}]")
                monto_sub_rec = get(row, f"MontoSubRecargo[{i}][{j}]")
                porc_sub_rec = get(row, f"SubRecargoPorcentaje[{i}][{j}]")

                # Solo para j=1: si MontoSubRecargo está vacío pero hay TipoSubRecargo, usar RecargoMonto
                if j == 1 and tipo_sub_rec and not monto_sub_rec:
                    monto_sub_rec = recargo_monto

                if tipo_sub_rec or monto_sub_rec or porc_sub_rec:
                    sub_rec = {}
                    add_if(sub_rec, "TipoSubRecargo", tipo_sub_rec)
                    add_if(sub_rec, "SubRecargoPorcentaje", porc_sub_rec)
                    add_if(sub_rec, "MontoSubRecargo", monto_sub_rec)
                    if sub_rec:
                        sub_recargos.append(sub_rec)
            if sub_recargos:
                it["TablaSubRecargo"] = {"SubRecargo": sub_recargos}

        # 13. OtraMonedaDetalle (tipo 45) - ANTES de MontoItem
        monto_item_otra_moneda = get(row, f"MontoItemOtraMoneda[{i}]")
        precio_otra_moneda = get(row, f"PrecioOtraMoneda[{i}]")
        if monto_item_otra_moneda or precio_otra_moneda:
            otra_mon_det = {}
            add_if(otra_mon_det, "PrecioOtraMoneda", precio_otra_moneda)
            add_if(otra_mon_det, "MontoItemOtraMoneda", monto_item_otra_moneda)
            add_if(otra_mon_det, "MontoDescuentoOtraMoneda", get(row, f"MontoDescuentoOtraMoneda[{i}]"))
            add_if(otra_mon_det, "MontoItemConDescuentoOtraMoneda", get(row, f"MontoItemConDescuentoOtraMoneda[{i}]"))
            if otra_mon_det:
                it["OtraMonedaDetalle"] = otra_mon_det

        # 14. MontoItem (siempre al final del item)
        # NOTA: ItbisItem NO se incluye según ejemplos válidos DGII
        add_if(it, "MontoItem", get(row, f"MontoItem[{i}]"))

        items.append(it)
    return items


def build_informaciones_adicionales(row: Dict) -> Optional[Dict[str, Any]]:
    """Construye InformacionesAdicionales con SOLO los campos permitidos por el schema XSD de la DGII"""
    # CRÍTICO: La DGII SOLO acepta estos 12 campos en InformacionesAdicionales
    # Cualquier otro campo causará rechazo con código 2
    # El orden también DEBE respetarse exactamente como está aquí
    info = {}
    campos = [
        "FechaEmbarque",
        "NumeroEmbarque",
        "NumeroContenedor",
        "NumeroReferencia",
        "PesoBruto",
        "PesoNeto",
        "UnidadPesoBruto",
        "UnidadPesoNeto",
        "CantidadBulto",
        "UnidadBulto",
        "VolumenBulto",
        "UnidadVolumen"
    ]

    # Insertar SOLO los campos permitidos en el orden correcto
    for campo in campos:
        # Nota: NumeroContenedor tiene un espacio extra en algunas columnas del Excel
        if campo == "NumeroContenedor":
            valor = get(row, "NumeroContenedor ") or get(row, "NumeroContenedor")
        else:
            valor = get(row, campo)

        add_if(info, campo, valor)

    return info if info else None


def build_descuentos_o_recargos(row: Dict, max_n: int = 50) -> Optional[Dict[str, Any]]:
    """Construye DescuentosORecargos si existen"""
    descuentos = []
    for i in range(1, max_n + 1):
        num_linea = get(row, f"NumeroLineaDoR[{i}]")
        if num_linea is None:
            continue

        dor = {}
        add_if(dor, "NumeroLinea", num_linea)
        add_if(dor, "TipoAjuste", get(row, f"TipoAjuste[{i}]"))
        add_if(dor, "DescripcionDescuentooRecargo", get(row, f"DescripcionDescuentooRecargo[{i}]"))
        add_if(dor, "TipoValor", get(row, f"TipoValor[{i}]"))
        add_if(dor, "MontoDescuentooRecargo", get(row, f"MontoDescuentooRecargo[{i}]"))
        add_if(dor, "IndicadorFacturacionDescuentooRecargo", get(row, f"IndicadorFacturacionDescuentooRecargo[{i}]"))

        if dor:
            descuentos.append(dor)

    if not descuentos:
        return None
    return {"DescuentoORecargo": descuentos}


def build_transporte(row: Dict) -> Optional[Dict[str, Any]]:
    """Construye sección Transporte para facturas de consumo >= 250k (tipo 32) y otros tipos"""
    transporte = {}
    campos = [
        "Conductor",
        "DocumentoTransporte",
        "Ficha",
        "Placa",
        "RutaTransporte",
        "ZonaTransporte",
        "NumeroAlbaran",
        "PaisDestino",  # Tipo 47 - Pagos al exterior
        "PaisOrigen"    # Exportaciones
    ]

    for campo in campos:
        add_if(transporte, campo, get(row, campo))

    return transporte if transporte else None


def build_informacion_referencia(row: Dict) -> Optional[Dict[str, Any]]:
    """Construye InformacionReferencia para Notas de Débito (tipo 33) y Notas de Crédito (tipo 34)"""
    info_ref = {}

    # NCFModificado y RNCAnterior son opcionales pero al menos uno debe existir
    add_if(info_ref, "NCFModificado", get(row, "NCFModificado") or get(row, "eNCFReferencia"))
    add_if(info_ref, "RNCAnterior", get(row, "RNCAnterior"))
    add_if(info_ref, "FechaNCFModificado", get(row, "FechaNCFModificado") or get(row, "FechaNCFReferencia"))

    # CodigoModificacion o RazonModificacion
    add_if(info_ref, "CodigoModificacion", get(row, "CodigoModificacion"))
    add_if(info_ref, "RazonModificacion", get(row, "RazonModificacion"))

    return info_ref if info_ref else None


def build_otra_moneda(row: Dict) -> Optional[Dict[str, Any]]:
    """Construye sección OtraMoneda para exportaciones (tipo 45)"""
    otra_moneda = {}

    add_if(otra_moneda, "TipoMoneda", get(row, "TipoMoneda"))
    add_if(otra_moneda, "TipoCambio", get(row, "TipoCambio"))
    add_if(otra_moneda, "MontoGravadoTotalOtraMoneda", get(row, "MontoGravadoTotalOtraMoneda"))
    add_if(otra_moneda, "MontoGravado1OtraMoneda", get(row, "MontoGravado1OtraMoneda"))
    add_if(otra_moneda, "MontoGravado2OtraMoneda", get(row, "MontoGravado2OtraMoneda"))
    add_if(otra_moneda, "MontoGravado3OtraMoneda", get(row, "MontoGravado3OtraMoneda"))
    add_if(otra_moneda, "MontoExentoOtraMoneda", get(row, "MontoExentoOtraMoneda"))
    add_if(otra_moneda, "TotalITBISOtraMoneda", get(row, "TotalITBISOtraMoneda"))
    add_if(otra_moneda, "TotalITBIS1OtraMoneda", get(row, "TotalITBIS1OtraMoneda"))
    add_if(otra_moneda, "TotalITBIS2OtraMoneda", get(row, "TotalITBIS2OtraMoneda"))
    add_if(otra_moneda, "TotalITBIS3OtraMoneda", get(row, "TotalITBIS3OtraMoneda"))
    add_if(otra_moneda, "MontoTotalOtraMoneda", get(row, "MontoTotalOtraMoneda"))

    return otra_moneda if otra_moneda else None


def build_ecf_json(row: Dict) -> Dict[str, Any]:
    """
    Construye el JSON del ECF completo desde una fila del Excel
    IMPORTANTE: Esta es la función EXACTA del script probado que funciona al 100%
    """
    encabezado: Dict[str, Any] = {}
    encabezado["Version"] = get(row, "Version") or "1.0"

    # ===== IdDoc =====
    iddoc: Dict[str, Any] = {}
    tipo_ecf = get(row, "TipoeCF")
    add_if(iddoc, "TipoeCF", tipo_ecf)
    encf = get(row, "ENCF") or get(row, "eNCF")
    add_if(iddoc, "eNCF", encf)

    # IndicadorNotaCredito (tipo 34)
    if tipo_ecf == "34":
        add_if(iddoc, "IndicadorNotaCredito", get(row, "IndicadorNotaCredito"))

    add_if(iddoc, "FechaVencimientoSecuencia", get(row, "FechaVencimientoSecuencia"))
    add_if(iddoc, "IndicadorMontoGravado", get(row, "IndicadorMontoGravado"))
    add_if(iddoc, "TipoIngresos", get(row, "TipoIngresos"))
    add_if(iddoc, "TipoPago", get(row, "TipoPago"))

    tabla_fp = build_tabla_formas_pago(row)
    if tabla_fp:
        iddoc["TablaFormasPago"] = tabla_fp

    encabezado["IdDoc"] = iddoc

    # ===== Emisor =====
    emisor: Dict[str, Any] = {}
    for k in ["RNCEmisor", "RazonSocialEmisor", "NombreComercial", "DireccionEmisor", "Municipio", "Provincia"]:
        add_if(emisor, k, get(row, k))
    tels = collect_indexed(row, "TelefonoEmisor", 10)
    if tels:
        emisor["TablaTelefonoEmisor"] = {"TelefonoEmisor": tels}
    for k in ["CorreoEmisor", "WebSite", "CodigoVendedor", "NumeroFacturaInterna", "NumeroPedidoInterno", "ZonaVenta", "FechaEmision"]:
        add_if(emisor, k, get(row, k))
    encabezado["Emisor"] = emisor

    # ===== Comprador =====
    comprador: Dict[str, Any] = {}

    # IdentificadorExtranjero o RNCComprador (mutuamente excluyentes, va primero)
    add_if(comprador, "IdentificadorExtranjero", get(row, "IdentificadorExtranjero"))
    add_if(comprador, "RNCComprador", get(row, "RNCComprador"))

    for k in ["RazonSocialComprador", "ContactoComprador", "CorreoComprador", "DireccionComprador",
              "MunicipioComprador", "ProvinciaComprador"]:
        add_if(comprador, k, get(row, k))

    # TelefonoAdicional (tipo 32)
    add_if(comprador, "TelefonoAdicional", get(row, "TelefonoAdicional"))

    for k in ["FechaEntrega", "FechaOrdenCompra", "NumeroOrdenCompra", "CodigoInternoComprador"]:
        add_if(comprador, k, get(row, k))

    if comprador:
        encabezado["Comprador"] = comprador

    # ===== Transporte =====
    # Tipo 32 >= 250k usa Transporte (no InformacionesAdicionales)
    # Tipos 44, 45, 46, 47 pueden usar Transporte si tienen datos
    monto_total = get(row, "MontoTotal")

    # Determinar si debe incluir sección Transporte
    incluir_transporte = False

    # Tipo 32 >= 250,000
    if tipo_ecf == "32" and monto_total:
        try:
            monto = float(str(monto_total).replace(",", ""))
            if monto >= 250000:
                incluir_transporte = True
        except:
            pass

    # Tipos 44, 45, 46, 47: incluir Transporte si tiene datos
    if tipo_ecf in ["44", "45", "46", "47"]:
        transporte_test = build_transporte(row)
        if transporte_test:
            incluir_transporte = True

    if incluir_transporte:
        transporte = build_transporte(row)
        if transporte:
            encabezado["Transporte"] = transporte

    # ===== InformacionesAdicionales =====
    # NOTA: No se incluye si ya se incluyó Transporte (son mutuamente excluyentes para tipo 32)
    if not incluir_transporte:
        info_adic = build_informaciones_adicionales(row)
        if info_adic:
            encabezado["InformacionesAdicionales"] = info_adic

    # ===== Totales =====
    totales: Dict[str, Any] = {}
    for k in ["MontoGravadoTotal", "MontoGravadoI1", "MontoGravadoI2", "MontoGravadoI3", "MontoGravadoI4", "MontoGravadoI5"]:
        add_if(totales, k, get(row, k))
    add_if(totales, "MontoExento", get(row, "MontoExento"))
    for k in ["ITBIS1", "ITBIS2", "ITBIS3", "ITBIS4", "ITBIS5",
              "TotalITBIS", "TotalITBIS1", "TotalITBIS2", "TotalITBIS3", "TotalITBIS4", "TotalITBIS5"]:
        add_if(totales, k, get(row, k))

    # MontoTotal ANTES de los campos especiales
    add_if(totales, "MontoTotal", get(row, "MontoTotal"))
    add_if(totales, "MontoPeriodo", get(row, "MontoPeriodo"))
    add_if(totales, "ValorPagar", get(row, "ValorPagar"))

    # TotalITBISRetenido y TotalISRRetencion (tipos 41, 47) - DESPUÉS de MontoTotal
    add_if(totales, "TotalITBISRetenido", get(row, "TotalITBISRetenido"))
    add_if(totales, "TotalISRRetencion", get(row, "TotalISRRetencion"))

    # MontoNoFacturable (tipo 34) - DESPUÉS de MontoTotal
    add_if(totales, "MontoNoFacturable", get(row, "MontoNoFacturable"))

    encabezado["Totales"] = totales

    ecf: Dict[str, Any] = {"Encabezado": encabezado}

    # ===== DetallesItems =====
    items = build_items(row)
    if items:
        ecf["DetallesItems"] = {"Item": items}

    # ===== DescuentosORecargos (si existe) =====
    dor = build_descuentos_o_recargos(row)
    if dor:
        ecf["DescuentosORecargos"] = dor

    # ===== InformacionReferencia (tipos 33 y 34 - Notas de Débito y Crédito) =====
    if tipo_ecf in ["33", "34"]:
        info_ref = build_informacion_referencia(row)
        if info_ref:
            ecf["InformacionReferencia"] = info_ref

    # ===== OtraMoneda (tipo 45 - Exportaciones) =====
    if tipo_ecf == "45":
        otra_moneda = build_otra_moneda(row)
        if otra_moneda:
            # OtraMoneda va después de Totales en Encabezado, no en ECF raíz
            encabezado["OtraMoneda"] = otra_moneda

    # ===== FechaHoraFirma =====
    fecha = get(row, "FechaHoraFirma") or datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    ecf["FechaHoraFirma"] = fecha

    return {"ECF": ecf}
