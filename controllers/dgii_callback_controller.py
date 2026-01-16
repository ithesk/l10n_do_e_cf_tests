"""
Controladores para endpoints de callback DGII.

Implementa los endpoints de:
- Recepción de e-CF: /fe/recepcion/api/ecf
- Aprobación Comercial: /fe/aprobacioncomercial/api/ecf
- Autenticación (Semilla): /fe/autenticacion/api/semilla
- Autenticación (Validación): /fe/autenticacion/api/validacioncertificado

Características:
- Almacenamiento de request raw + headers
- Procesamiento asíncrono con queue_job
- Manejo de duplicados e idempotencia
- Rate limiting y logging
- Soporte para múltiples ambientes
- Selección automática de base de datos (sin necesidad de header X-Odoo-Database)
"""
import json
import logging
import hashlib
import base64
from datetime import datetime
from functools import wraps

from lxml import etree

from odoo import http, SUPERUSER_ID, api
from odoo.http import request, Response
from odoo.modules.registry import Registry
from odoo.service import db as db_service

_logger = logging.getLogger(__name__)


def _get_database_name():
    """
    Obtiene el nombre de la base de datos a usar.

    Prioridad:
    1. Header X-Odoo-Database si está presente
    2. Única base de datos disponible
    3. Base de datos con el módulo l10n_do_e_cf_tests instalado

    Returns:
        str: Nombre de la base de datos o None si no se puede determinar
    """
    # 1. Verificar header explícito
    db_name = request.httprequest.headers.get('X-Odoo-Database')
    if db_name:
        return db_name

    # 2. Obtener lista de bases de datos
    try:
        db_list = db_service.list_dbs()
    except Exception as e:
        _logger.warning("[DGII Callback] Error listando bases de datos: %s", e)
        return None

    if not db_list:
        _logger.warning("[DGII Callback] No hay bases de datos disponibles")
        return None

    # 3. Si solo hay una, usarla
    if len(db_list) == 1:
        return db_list[0]

    # 4. Buscar una base de datos con el módulo instalado
    for db_name in db_list:
        try:
            db_registry = Registry(db_name)
            with db_registry.cursor() as cr:
                cr.execute("""
                    SELECT 1 FROM ir_module_module
                    WHERE name = 'l10n_do_e_cf_tests'
                    AND state = 'installed'
                    LIMIT 1
                """)
                if cr.fetchone():
                    _logger.info("[DGII Callback] Base de datos seleccionada: %s", db_name)
                    return db_name
        except Exception as e:
            _logger.debug("[DGII Callback] Error verificando BD %s: %s", db_name, e)
            continue

    # 5. Fallback: usar la primera
    _logger.warning("[DGII Callback] No se encontró BD con el módulo, usando primera: %s", db_list[0])
    return db_list[0]


def _ensure_db():
    """
    Asegura que haya una base de datos seleccionada en el request.
    Si no hay, intenta seleccionar una automáticamente.

    Returns:
        bool: True si hay BD disponible, False si no
    """
    # Si ya hay una BD seleccionada, OK
    if request.db:
        return True

    # Intentar obtener una BD
    db_name = _get_database_name()
    if not db_name:
        return False

    # Establecer la BD en el request
    request._cr = None
    request._env = None
    request.db = db_name

    return True

# Cache simple para rate limiting (en memoria del proceso)
_rate_limit_cache = {}


def dgii_endpoint(callback_type):
    """
    Decorador para endpoints DGII que maneja:
    - Selección automática de base de datos
    - Rate limiting
    - Logging estructurado
    - Almacenamiento de request
    - Manejo de errores
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            start_time = datetime.now()
            callback_request = None

            try:
                # Asegurar que hay una base de datos seleccionada
                if not _ensure_db():
                    _logger.error("[DGII Callback] No se pudo determinar la base de datos")
                    return self._error_response(
                        "NO_DATABASE",
                        "No se pudo determinar la base de datos. Configure db_name en odoo.conf o use el header X-Odoo-Database.",
                        status_code=503
                    )

                # Obtener IP del cliente
                remote_ip = request.httprequest.remote_addr

                # Log de entrada
                _logger.info(
                    "[DGII Callback] %s request desde %s - Path: %s - DB: %s",
                    callback_type.upper(), remote_ip, request.httprequest.path, request.db
                )

                # Obtener configuración
                env = request.env(user=SUPERUSER_ID)
                config = env['dgii.callback.config'].get_config()

                # Verificar rate limiting
                if config and config.enable_rate_limit:
                    allowed, remaining, reset_at = config.check_rate_limit(remote_ip, _rate_limit_cache)
                    if not allowed:
                        _logger.warning(
                            "[DGII Callback] Rate limit excedido para IP %s",
                            remote_ip
                        )
                        return self._error_response(
                            "RATE_LIMIT_EXCEEDED",
                            "Se ha excedido el límite de solicitudes. Intente más tarde.",
                            status_code=429
                        )

                # Verificar IP whitelist
                if config and config.enable_ip_whitelist:
                    if not config.is_ip_allowed(remote_ip):
                        _logger.warning(
                            "[DGII Callback] IP no autorizada: %s",
                            remote_ip
                        )
                        return self._error_response(
                            "IP_NOT_ALLOWED",
                            "IP no autorizada para este servicio.",
                            status_code=403
                        )

                # Crear registro de callback request
                callback_request = env['dgii.callback.request'].create_from_http_request(
                    request.httprequest,
                    callback_type
                )

                # Si es duplicado, retornar respuesta del original
                if callback_request.state == 'duplicate' and callback_request.original_request_id:
                    original = callback_request.original_request_id
                    _logger.info(
                        "[DGII Callback] Request duplicado detectado. Original: %s",
                        original.id
                    )
                    if original.response_body:
                        return Response(
                            response=original.response_body,
                            status=original.response_status_code or 200,
                            content_type='application/xml; charset=utf-8'
                        )

                # Ejecutar el handler real
                response = func(self, callback_request, *args, **kwargs)

                # Registrar respuesta
                processing_time = int((datetime.now() - start_time).total_seconds() * 1000)
                callback_request.write({
                    'response_status_code': response.status_code if hasattr(response, 'status_code') else 200,
                    'response_body': response.response[0].decode('utf-8') if response.response else '',
                    'response_sent_at': datetime.now(),
                    'processing_time_ms': processing_time,
                })

                # Encolar para procesamiento asíncrono si corresponde
                if callback_request.state == 'received':
                    if config and config.async_processing:
                        callback_request.queue_for_processing()
                    else:
                        callback_request.process_callback()

                _logger.info(
                    "[DGII Callback] %s completado en %dms - Request ID: %s",
                    callback_type.upper(), processing_time, callback_request.id
                )

                return response

            except Exception as e:
                _logger.exception("[DGII Callback] Error en %s", callback_type)

                # Registrar error si tenemos el callback_request
                if callback_request:
                    callback_request.write({
                        'state': 'error',
                        'error_message': str(e),
                    })

                return self._error_response(
                    "INTERNAL_ERROR",
                    f"Error interno del servidor: {str(e)}",
                    status_code=500
                )

        return wrapper
    return decorator


class DgiiCallbackController(http.Controller):
    """
    Controlador para recibir callbacks de la DGII.

    Endpoints disponibles:
    - POST /fe/recepcion/api/ecf - Recepción de e-CF
    - POST /fe/aprobacioncomercial/api/ecf - Aprobación comercial
    - GET /fe/autenticacion/api/semilla - Obtener semilla
    - POST /fe/autenticacion/api/validacioncertificado - Validar certificado
    - GET /fe/status - Health check
    """

    # =========================================================================
    # Endpoint de Recepción de e-CF
    # =========================================================================

    @http.route(
        '/fe/recepcion/api/ecf',
        type='http',
        auth='public',
        methods=['POST'],
        csrf=False,
        save_session=False
    )
    @dgii_endpoint('recepcion')
    def dgii_recepcion(self, callback_request, **kwargs):
        """
        Endpoint para recibir e-CF de la DGII o proveedores.

        Request esperado:
        - Content-Type: application/xml
        - Body: XML del e-CF firmado

        Response:
        - XML con acuse de recibo incluyendo TrackID
        """
        # =====================================================================
        # DEPURACIÓN DETALLADA DEL REQUEST
        # =====================================================================
        _logger.info("=" * 80)
        _logger.info("[DGII Recepcion] ===== INICIO REQUEST RECEPCION =====")
        _logger.info("[DGII Recepcion] Remote IP: %s", callback_request.remote_ip)
        _logger.info("[DGII Recepcion] Content-Type: %s", callback_request.content_type)
        _logger.info("[DGII Recepcion] Content-Length: %s", callback_request.content_length)
        _logger.info("[DGII Recepcion] User-Agent: %s", callback_request.user_agent)

        # Log de headers completos
        try:
            headers_dict = json.loads(callback_request.request_headers_raw or '{}')
            _logger.info("[DGII Recepcion] Headers recibidos:")
            for key, value in headers_dict.items():
                # Ocultar valores sensibles
                if any(x in key.lower() for x in ['auth', 'token', 'key', 'secret']):
                    _logger.info("[DGII Recepcion]   %s: ***HIDDEN***", key)
                else:
                    _logger.info("[DGII Recepcion]   %s: %s", key, value)
        except Exception as e:
            _logger.warning("[DGII Recepcion] Error parseando headers: %s", e)

        # Log del body recibido
        body_raw = callback_request.request_body_raw or ""
        _logger.info("[DGII Recepcion] Body Length: %d bytes", len(body_raw))
        _logger.info("[DGII Recepcion] Body (primeros 2000 chars):\n%s", body_raw[:2000])
        if len(body_raw) > 2000:
            _logger.info("[DGII Recepcion] ... (truncado, total %d bytes)", len(body_raw))

        # =====================================================================
        # DETECTAR SI ES JSON O XML Y EXTRAER DATOS
        # =====================================================================
        # El body puede ser:
        # 1. JSON del microservicio: {"ecfXmlReceived": "<?xml...", "arecfXmlSigned": "...", ...}
        # 2. XML directo de DGII: <?xml version="1.0"...

        xml_data = ""
        arecf_from_body = None
        ecf_info_from_body = None
        arecf_status_from_body = None
        is_json_body = False

        body_stripped = body_raw.strip()
        if body_stripped.startswith('{'):
            # Es JSON - proviene del microservicio
            is_json_body = True
            _logger.info("[DGII Recepcion] Body es JSON (del microservicio)")
            try:
                body_json = json.loads(body_raw)
                xml_data = body_json.get('ecfXmlReceived', '')
                arecf_from_body = body_json.get('arecfXmlSigned', '')
                ecf_info_from_body = body_json.get('ecfInfo', {})
                arecf_status_from_body = body_json.get('arecfStatus', '')

                _logger.info("[DGII Recepcion] Extraído del JSON:")
                _logger.info("[DGII Recepcion]   ecfXmlReceived: %d bytes", len(xml_data) if xml_data else 0)
                _logger.info("[DGII Recepcion]   arecfXmlSigned: %d bytes", len(arecf_from_body) if arecf_from_body else 0)
                _logger.info("[DGII Recepcion]   ecfInfo: %s", ecf_info_from_body)
                _logger.info("[DGII Recepcion]   arecfStatus: %s", arecf_status_from_body)
            except json.JSONDecodeError as e:
                _logger.error("[DGII Recepcion] Error parseando JSON: %s", e)
                xml_data = body_raw  # Fallback al body completo
        elif body_stripped.startswith('<'):
            # Es XML directo - proviene de DGII
            _logger.info("[DGII Recepcion] Body es XML directo (de DGII)")
            xml_data = body_raw
        else:
            _logger.warning("[DGII Recepcion] Body no reconocido, usando como XML")
            xml_data = body_raw

        # =====================================================================
        # EXTRACCIÓN DE DATOS DEL XML
        # =====================================================================
        ncf_value = callback_request.encf or ""
        rnc_emisor_value = callback_request.rnc_emisor or ""
        rnc_comprador_value = callback_request.rnc_receptor or ""
        fecha_emision = ""
        monto_total = ""
        fecha_firma = ""
        codigo_seguridad = ""

        # Intentar extraer más datos del XML
        try:
            if xml_data and xml_data.strip():
                root = etree.fromstring(xml_data.encode('utf-8') if isinstance(xml_data, str) else xml_data)

                # Extraer todos los campos relevantes
                ncf_value = ncf_value or self._find_xml_text(root, ['eNCF', 'NumeroNCF', 'NCF', 'ENCF']) or ""
                rnc_emisor_value = rnc_emisor_value or self._find_xml_text(root, ['RNCEmisor', 'RncEmisor']) or ""
                rnc_comprador_value = rnc_comprador_value or self._find_xml_text(root, ['RNCComprador', 'RncComprador']) or ""
                fecha_emision = self._find_xml_text(root, ['FechaEmision', 'fechaEmision']) or ""
                monto_total = self._find_xml_text(root, ['MontoTotal', 'montoTotal', 'TotalMonto']) or ""
                fecha_firma = self._find_xml_text(root, ['FechaFirma', 'fechaFirma', 'FechaHoraFirma']) or ""

                # El código de seguridad puede estar como tag independiente o se extrae del SignatureValue
                codigo_seguridad = self._find_xml_text(root, ['CodigoSeguridad', 'codigoSeguridad']) or ""
                if not codigo_seguridad:
                    # Extraer de los primeros 6 caracteres del SignatureValue (estándar e-CF)
                    signature_value = self._find_xml_text(root, ['SignatureValue']) or ""
                    if signature_value:
                        codigo_seguridad = signature_value[:6]
                        _logger.info("[DGII Recepcion] Código Seguridad extraído de SignatureValue: %s", codigo_seguridad)

                _logger.info("[DGII Recepcion] Datos extraídos del XML:")
                _logger.info("[DGII Recepcion]   eNCF: %s", ncf_value)
                _logger.info("[DGII Recepcion]   RNC Emisor: %s", rnc_emisor_value)
                _logger.info("[DGII Recepcion]   RNC Comprador: %s", rnc_comprador_value)
                _logger.info("[DGII Recepcion]   Fecha Emisión: %s", fecha_emision)
                _logger.info("[DGII Recepcion]   Monto Total: %s", monto_total)
                _logger.info("[DGII Recepcion]   Fecha Firma: %s", fecha_firma)
                _logger.info("[DGII Recepcion]   Código Seguridad: %s", codigo_seguridad)

        except Exception as e:
            _logger.error("[DGII Recepcion] Error parseando XML: %s", e)
            _logger.error("[DGII Recepcion] XML que falló: %s", xml_data[:500] if xml_data else "EMPTY")

        # =====================================================================
        # Actualizar callback_request con datos extraídos
        # =====================================================================
        callback_request.write({
            'encf': ncf_value or callback_request.encf,
            'rnc_emisor': rnc_emisor_value or callback_request.rnc_emisor,
            'rnc_receptor': rnc_comprador_value or callback_request.rnc_receptor,
        })

        # =====================================================================
        # CREAR REGISTRO DE e-CF RECIBIDO
        # =====================================================================
        env = request.env(user=SUPERUSER_ID)
        ecf_received = None

        try:
            EcfReceived = env['ecf.received']
            ecf_received = EcfReceived.create_from_xml(
                xml_string=xml_data,
                callback_request_id=callback_request.id
            )
            _logger.info("[DGII Recepcion] e-CF Recibido creado: ID=%s, e-NCF=%s",
                        ecf_received.id, ecf_received.encf)
        except Exception as e:
            _logger.exception("[DGII Recepcion] Error creando e-CF Recibido: %s", e)

        # =====================================================================
        # PROCESAR DATOS - DEPENDE DE SI YA VINO DEL MICROSERVICIO O NO
        # =====================================================================
        import requests as http_requests
        import time

        # env ya fue definido arriba
        ApiLog = env['ecf.api.log']

        api_success = False
        api_error = None
        track_id = None
        api_log = None
        arecf_xml_signed = None
        ecf_info = None
        response_data = None

        if is_json_body and arecf_from_body:
            # =====================================================================
            # CASO 1: DATOS YA VIENEN DEL MICROSERVICIO (JSON)
            # =====================================================================
            # El microservicio ya procesó todo y nos envía el resultado
            # Solo guardamos los datos, no llamamos a la API
            _logger.info("[DGII Recepcion] ===== DATOS YA PROCESADOS POR MICROSERVICIO =====")

            arecf_xml_signed = arecf_from_body
            ecf_info = ecf_info_from_body or {}
            arecf_status = arecf_status_from_body

            # Estado 0 = Aceptado
            api_success = str(arecf_status) == "0"

            if api_success:
                _logger.info("[DGII Recepcion] ARECF recibido del microservicio - Estado: Aceptado")
            else:
                api_error = f"ARECF con estado: {arecf_status}"
                _logger.warning("[DGII Recepcion] ARECF recibido con estado: %s", arecf_status)

            # Construir response_data para actualizar ecf_received
            response_data = {
                'ecfXmlReceived': xml_data,
                'arecfXmlSigned': arecf_xml_signed,
                'ecfInfo': ecf_info,
                'arecfStatus': arecf_status
            }

            # Actualizar callback_request con info del documento
            if ecf_info:
                callback_request.write({
                    'encf': ecf_info.get('eNCF') or ncf_value,
                    'rnc_emisor': ecf_info.get('rncEmisor') or rnc_emisor_value,
                    'rnc_receptor': ecf_info.get('rncComprador') or rnc_comprador_value,
                })

            # Crear log de la recepción (sin llamada a API externa)
            api_provider = env['ecf.api.provider'].get_default_provider()
            if api_provider:
                api_log = ApiLog.create_from_request(
                    provider=api_provider,
                    origin='callback_recepcion_json',
                    request_url='/fe/recepcion/api/ecf (JSON from microservice)',
                    request_payload={"source": "microservice", "has_arecf": True},
                    request_headers={},
                    rnc=rnc_comprador_value,
                    encf=ncf_value,
                    tipo_ecf=ncf_value[:3] if ncf_value else None,
                    incoming_xml=xml_data
                )
                api_log.update_with_response(
                    success=api_success,
                    status_code=200,
                    response_body=json.dumps(response_data),
                    response_json=response_data,
                    signed_xml=arecf_xml_signed,
                    error_message=api_error,
                    response_time_ms=0
                )

            _logger.info("[DGII Recepcion] ecfInfo: %s", json.dumps(ecf_info, indent=2) if ecf_info else "N/A")
            _logger.info("[DGII Recepcion] ARECF guardado: %d bytes", len(arecf_xml_signed) if arecf_xml_signed else 0)

        else:
            # =====================================================================
            # CASO 2: XML DIRECTO - LLAMAR A LA API DEL MICROSERVICIO
            # =====================================================================
            # Flujo: DGII envía XML directo -> Odoo llama al microservicio
            _logger.info("[DGII Recepcion] ===== ENVIANDO e-CF A MICROSERVICIO =====")

            api_provider = env['ecf.api.provider'].get_default_provider()

            if not api_provider:
                api_error = "No hay proveedor de API configurado"
                _logger.warning("[DGII Recepcion] %s", api_error)
            else:
                # Construir URL para /invoice/receipt
                api_url = api_provider.api_url or ""
                if api_url:
                    if '/invoice/send' in api_url:
                        api_url_receipt = api_url.replace('/invoice/send', '/invoice/receipt')
                    elif '/invoice/' in api_url:
                        api_base = api_url.split('/invoice/')[0]
                        api_url_receipt = f"{api_base}/invoice/receipt"
                    else:
                        api_url_receipt = api_url.rstrip('/') + '/invoice/receipt'
                else:
                    api_url_receipt = ""

                api_key = api_provider.auth_token or ""
                api_environment = api_provider.environment or "cert"

                # Preparar datos para la API - Enviar XML original del e-CF
                receipt_data = {
                    "ecfXml": xml_data,  # XML original del e-CF recibido
                    "rnc": rnc_comprador_value,  # RNC del receptor (nosotros)
                    "environment": api_environment
                }

                # Headers para la API
                headers = {
                    "Content-Type": "application/json",
                }
                if api_key:
                    header_name = api_provider.api_key_header or "x-api-key"
                    headers[header_name] = api_key

                # Crear log ANTES de enviar
                api_log = ApiLog.create_from_request(
                    provider=api_provider,
                    origin='callback_recepcion',
                    request_url=api_url_receipt,
                    request_payload={"ecfXml": "[XML e-CF]", "rnc": rnc_comprador_value, "environment": api_environment},
                    request_headers=headers,
                    rnc=rnc_comprador_value,
                    encf=ncf_value,
                    tipo_ecf=ncf_value[:3] if ncf_value else None,
                    incoming_xml=xml_data  # XML original que llegó de DGII
                )

                _logger.info("[DGII Recepcion] Proveedor: %s", api_provider.name)
                _logger.info("[DGII Recepcion] API URL: %s", api_url_receipt)
                _logger.info("[DGII Recepcion] Log ID: %s", api_log.id)
                _logger.info("[DGII Recepcion] RNC Receptor: %s", rnc_comprador_value)
                _logger.info("[DGII Recepcion] eNCF: %s", ncf_value)

                start_time = time.time()

                try:
                    api_response = http_requests.post(
                        api_url_receipt,
                        json=receipt_data,
                        headers=headers,
                        timeout=api_provider.timeout or 30
                    )

                    response_time_ms = int((time.time() - start_time) * 1000)
                    _logger.info("[DGII Recepcion] API Response Status: %s", api_response.status_code)
                    _logger.info("[DGII Recepcion] API Response Body (primeros 1000): %s",
                                api_response.text[:1000] if api_response.text else "EMPTY")

                    response_data = None
                    try:
                        response_data = api_response.json()
                    except Exception:
                        response_data = {"raw": api_response.text}

                    if api_response.status_code == 200:
                        # Extraer datos de la respuesta del microservicio
                        arecf_xml_signed = response_data.get('arecfXmlSigned')
                        ecf_info = response_data.get('ecfInfo', {})
                        arecf_status = response_data.get('arecfStatus')
                        arecf_reject_code = response_data.get('arecfRejectCode')

                        # Estado 0 = Aceptado
                        api_success = arecf_status == "0" or arecf_status == 0

                        if api_success:
                            _logger.info("[DGII Recepcion] ARECF enviado exitosamente a DGII")
                            _logger.info("[DGII Recepcion] ecfInfo: %s", json.dumps(ecf_info, indent=2))
                        else:
                            api_error = f"ARECF rechazado. Status: {arecf_status}, Code: {arecf_reject_code}"
                            _logger.warning("[DGII Recepcion] %s", api_error)

                        # Actualizar callback_request con info del documento
                        if ecf_info:
                            callback_request.write({
                                'encf': ecf_info.get('eNCF') or ncf_value,
                                'rnc_emisor': ecf_info.get('rncEmisor') or rnc_emisor_value,
                                'rnc_receptor': ecf_info.get('rncComprador') or rnc_comprador_value,
                            })
                    else:
                        api_error = f"HTTP {api_response.status_code}: {api_response.text[:500]}"
                        _logger.error("[DGII Recepcion] API HTTP Error: %s", api_error)

                    # Actualizar log con respuesta
                    api_log.update_with_response(
                        success=api_success,
                        status_code=api_response.status_code,
                        response_body=api_response.text,
                        response_json=response_data,
                        signed_xml=arecf_xml_signed,  # XML del ARECF firmado
                        error_message=api_error,
                        response_time_ms=response_time_ms
                    )

                except http_requests.exceptions.Timeout:
                    api_error = "API Timeout"
                    response_time_ms = int((time.time() - start_time) * 1000)
                    _logger.error("[DGII Recepcion] API Timeout")
                    api_log.update_with_response(
                        success=False,
                        error_message=api_error,
                        response_time_ms=response_time_ms
                    )
                except http_requests.exceptions.ConnectionError as e:
                    api_error = f"Connection Error: {str(e)}"
                    response_time_ms = int((time.time() - start_time) * 1000)
                    _logger.error("[DGII Recepcion] API Connection Error: %s", e)
                    api_log.update_with_response(
                        success=False,
                        error_message=api_error,
                        response_time_ms=response_time_ms
                    )
                except Exception as e:
                    api_error = str(e)
                    response_time_ms = int((time.time() - start_time) * 1000)
                    _logger.exception("[DGII Recepcion] API Exception: %s", e)
                    api_log.update_with_response(
                        success=False,
                        error_message=api_error,
                        response_time_ms=response_time_ms
                    )

        # =====================================================================
        # ACTUALIZAR e-CF RECIBIDO CON RESPUESTA DE LA API
        # =====================================================================
        if ecf_received and response_data:
            try:
                ecf_received.update_from_api_response(response_data)
                # Relacionar con el log de API
                if api_log:
                    ecf_received.write({'api_log_id': api_log.id})
                _logger.info("[DGII Recepcion] e-CF Recibido actualizado con respuesta API")
            except Exception as e:
                _logger.exception("[DGII Recepcion] Error actualizando e-CF Recibido: %s", e)

        # =====================================================================
        # GENERAR RESPUESTA LOCAL
        # =====================================================================
        # Flujo: DGII -> API (microservicio) -> Odoo (nosotros, solo para log)
        # La API ya se encargó de firmar y enviar el ARECF a DGII
        # Nosotros solo guardamos la información para trazabilidad

        if not api_success and api_error:
            callback_request.write({
                'error_message': f"API Error: {api_error}",
            })

        fecha_recepcion = datetime.now().strftime("%d-%m-%Y %H:%M:%S")

        # Respuesta de confirmación
        if api_success:
            response_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<ARECF xmlns="http://dgii.gov.do/eNCF/ver1.0">
    <DetalleAcusedeRecibo>
        <Version>1.0</Version>
        <RNCEmisor>{rnc_emisor_value}</RNCEmisor>
        <RNCComprador>{rnc_comprador_value}</RNCComprador>
        <eNCF>{ncf_value}</eNCF>
        <Estado>Procesado</Estado>
        <CodigoMensaje>0</CodigoMensaje>
        <Mensaje>Documento recibido y guardado correctamente</Mensaje>
        <FechaHoraAcuseRecibo>{fecha_recepcion}</FechaHoraAcuseRecibo>
    </DetalleAcusedeRecibo>
</ARECF>"""
        else:
            response_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<ARECF xmlns="http://dgii.gov.do/eNCF/ver1.0">
    <DetalleAcusedeRecibo>
        <Version>1.0</Version>
        <RNCEmisor>{rnc_emisor_value}</RNCEmisor>
        <RNCComprador>{rnc_comprador_value}</RNCComprador>
        <eNCF>{ncf_value}</eNCF>
        <Estado>Error</Estado>
        <CodigoMensaje>1</CodigoMensaje>
        <Mensaje>Error al procesar: {api_error or 'Error desconocido'}</Mensaje>
        <FechaHoraAcuseRecibo>{fecha_recepcion}</FechaHoraAcuseRecibo>
    </DetalleAcusedeRecibo>
</ARECF>"""

        # =====================================================================
        # LOG FINAL
        # =====================================================================
        _logger.info("[DGII Recepcion] ===== PROCESAMIENTO COMPLETADO =====")
        _logger.info("[DGII Recepcion] API Success: %s", api_success)
        _logger.info("[DGII Recepcion] eNCF: %s", ncf_value)
        _logger.info("[DGII Recepcion] RNC Emisor: %s", rnc_emisor_value)
        _logger.info("[DGII Recepcion] ARECF Firmado guardado: %s", "Sí" if arecf_xml_signed else "No")
        if ecf_info:
            _logger.info("[DGII Recepcion] ecfInfo: tipoeCF=%s, montoTotal=%s, totalITBIS=%s",
                        ecf_info.get('tipoeCF'), ecf_info.get('montoTotal'), ecf_info.get('totalITBIS'))
        _logger.info("[DGII Recepcion] ===== FIN REQUEST RECEPCION =====")
        _logger.info("=" * 80)

        return Response(
            response=response_xml,
            status=200,
            content_type='application/xml; charset=utf-8'
        )

    # =========================================================================
    # Endpoint de Aprobación Comercial
    # =========================================================================

    @http.route(
        '/fe/aprobacioncomercial/api/ecf',
        type='http',
        auth='public',
        methods=['POST'],
        csrf=False,
        save_session=False
    )
    @dgii_endpoint('aprobacion_comercial')
    def dgii_aprobacion_comercial(self, callback_request, **kwargs):
        """
        Endpoint para recibir aprobaciones/rechazos comerciales.

        Request esperado:
        - Content-Type: application/xml
        - Body: XML con decisión de aprobación/rechazo

        Response:
        - XML con confirmación de procesamiento
        """
        # Extraer datos del request
        track_id = callback_request.track_id or "UNKNOWN"
        estado = callback_request.estado_aprobacion or "UNKNOWN"

        # Intentar extraer del XML si no se obtuvo
        if track_id == "UNKNOWN":
            try:
                xml_data = callback_request.request_body_raw
                root = etree.fromstring(xml_data.encode('utf-8'))
                track_id = self._find_xml_text(root, ['TrackId', 'TrackID', 'trackId']) or track_id
            except Exception:
                pass

        # Mapear estado
        estado_texto = "APROBADO" if estado == "aprobado" else ("RECHAZADO" if estado == "rechazado" else "PROCESADO")

        # Generar respuesta XML
        response_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<ConfirmacionAprobacion xmlns="http://www.dgii.gov.do/ecf">
    <Estado>PROCESADO</Estado>
    <TrackID>{track_id}</TrackID>
    <ResultadoAprobacion>{estado_texto}</ResultadoAprobacion>
    <FechaProcesamiento>{datetime.now().isoformat()}</FechaProcesamiento>
    <Mensaje>Aprobación comercial registrada correctamente.</Mensaje>
</ConfirmacionAprobacion>"""

        _logger.info(
            "[DGII Aprobacion] Aprobación recibida: TrackID=%s, Estado=%s",
            track_id, estado_texto
        )

        return Response(
            response=response_xml,
            status=200,
            content_type='application/xml; charset=utf-8'
        )

    # =========================================================================
    # Endpoints de Autenticación
    # =========================================================================

    @http.route(
        ['/fe/autenticacion/api/semilla', '/api/Autenticacion/Semilla'],
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
        save_session=False
    )
    def dgii_get_semilla(self, **kwargs):
        """
        Endpoint GET para obtener semilla de autenticación.

        Flujo:
        1. Cliente hace GET a este endpoint
        2. Servidor genera y retorna una semilla única en base64
        3. Cliente debe firmar la semilla y enviarla a ValidarCertificado
        """
        start_time = datetime.now()
        remote_ip = request.httprequest.remote_addr

        try:
            # Asegurar que hay una base de datos seleccionada
            if not _ensure_db():
                _logger.error("[DGII Semilla] No se pudo determinar la base de datos")
                return self._error_response(
                    "NO_DATABASE",
                    "No se pudo determinar la base de datos.",
                    status_code=503
                )

            _logger.info("[DGII Semilla] Request desde %s - DB: %s", remote_ip, request.db)

            # Registrar callback request
            env = request.env(user=SUPERUSER_ID)

            # Crear registro manualmente (no usar decorador para GET simple)
            callback_request = env['dgii.callback.request'].create({
                'callback_type': 'autenticacion_semilla',
                'request_method': 'GET',
                'request_path': request.httprequest.path,
                'request_query_string': request.httprequest.query_string.decode('utf-8') if request.httprequest.query_string else '',
                'request_headers_raw': json.dumps(dict(request.httprequest.headers)),
                'remote_ip': remote_ip,
                'user_agent': request.httprequest.headers.get('User-Agent', ''),
                'received_at': datetime.now(),
                'state': 'processed',  # GET simple, no requiere procesamiento
            })

            # Generar semilla única
            import random
            import string

            timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
            random_data = ''.join(random.choices(string.ascii_letters + string.digits, k=64))
            seed_value = f"{timestamp}_{random_data}"

            # Codificar en base64
            seed_base64 = base64.b64encode(seed_value.encode()).decode()

            # Generar respuesta XML (formato oficial DGII)
            response_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<SemillaModel xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
    <valor>{seed_base64}</valor>
    <fecha>{datetime.now().isoformat()}</fecha>
</SemillaModel>"""

            # Actualizar callback con respuesta
            processing_time = int((datetime.now() - start_time).total_seconds() * 1000)
            callback_request.write({
                'response_status_code': 200,
                'response_body': response_xml,
                'response_sent_at': datetime.now(),
                'processing_time_ms': processing_time,
            })

            _logger.info(
                "[DGII Semilla] Semilla generada en %dms, Request ID: %s",
                processing_time, callback_request.id
            )

            return Response(
                response=response_xml,
                status=200,
                content_type='application/xml; charset=utf-8'
            )

        except Exception as e:
            _logger.exception("[DGII Semilla] Error")
            return self._error_response(
                "ERROR_SEMILLA",
                str(e),
                status_code=500
            )

    @http.route(
        ['/fe/autenticacion/api/validacioncertificado',
         '/api/Autenticacion/ValidarSemilla'],
        type='http',
        auth='public',
        methods=['POST'],
        csrf=False,
        save_session=False
    )
    @dgii_endpoint('autenticacion_validacion')
    def dgii_validar_certificado(self, callback_request, **kwargs):
        """
        Endpoint POST para validar semilla firmada y obtener token.

        Flujo:
        1. Cliente obtiene semilla con GET /semilla
        2. Cliente genera XML con RNC + Fecha + Semilla
        3. Cliente firma XML con certificado digital
        4. Cliente envía XML firmado a este endpoint (POST)
        5. Servidor valida firma y semilla
        6. Servidor retorna token de sesión (válido 1 hora)
        """
        xml_data = callback_request.request_body_raw
        rnc_value = callback_request.rnc_emisor or "UNKNOWN"

        # Intentar extraer RNC del XML si no se obtuvo
        if rnc_value == "UNKNOWN":
            try:
                root = etree.fromstring(xml_data.encode('utf-8'))
                rnc_value = self._find_xml_text(root, ['RNCEmisor', 'RncEmisor', 'rnc']) or rnc_value

                # Verificar presencia de firma digital
                signature = root.find('.//{http://www.w3.org/2000/09/xmldsig#}Signature')
                has_signature = signature is not None

                _logger.info(
                    "[DGII Validacion] RNC: %s, Firma digital: %s",
                    rnc_value, "Presente" if has_signature else "Ausente"
                )

                # En producción, aquí se validaría:
                # - La firma digital con el certificado
                # - Que la semilla sea válida y no expirada
                # - Que el RNC esté autorizado

            except Exception as e:
                _logger.warning("[DGII Validacion] Error parseando XML de auth: %s", e)

        # Generar token de prueba
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        token_hash = hashlib.sha256(f"{rnc_value}:{timestamp}".encode()).hexdigest()[:32]
        token = f"Bearer_DGII_{timestamp}_{token_hash}"

        # Generar respuesta JSON
        response_data = {
            "token": token,
            "expiresIn": 3600,  # 1 hora en segundos
            "tokenType": "Bearer",
            "rncEmisor": rnc_value,
            "fechaEmision": datetime.now().isoformat(),
            "mensaje": "Autenticación exitosa"
        }

        response_json = json.dumps(response_data, ensure_ascii=False)

        _logger.info(
            "[DGII Validacion] Token generado para RNC %s: %s...",
            rnc_value, token[:30]
        )

        return Response(
            response=response_json,
            status=200,
            content_type='application/json; charset=utf-8'
        )

    # =========================================================================
    # Health Check y Status
    # =========================================================================

    @http.route(
        '/fe/status',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
        save_session=False
    )
    def dgii_status(self, **kwargs):
        """
        Endpoint de verificación de estado del servicio.
        Útil para healthchecks y monitoreo.
        """
        # Asegurar que hay una base de datos seleccionada
        if not _ensure_db():
            # Retornar status básico sin BD
            status_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<ServiceStatus xmlns="http://www.dgii.gov.do/ecf">
    <Estado>DEGRADADO</Estado>
    <Servicio>DGII e-CF Callback Endpoints</Servicio>
    <Version>1.0.0</Version>
    <Fecha>{datetime.now().isoformat()}</Fecha>
    <Error>No se pudo conectar a la base de datos</Error>
</ServiceStatus>"""
            return Response(
                response=status_xml,
                status=503,
                content_type='application/xml; charset=utf-8'
            )

        env = request.env(user=SUPERUSER_ID)

        # Obtener estadísticas
        try:
            callback_model = env['dgii.callback.request']
            stats = callback_model.get_statistics(days=1)
        except Exception:
            stats = {'total': 0}

        status_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<ServiceStatus xmlns="http://www.dgii.gov.do/ecf">
    <Estado>OPERATIVO</Estado>
    <Servicio>DGII e-CF Callback Endpoints</Servicio>
    <Version>1.0.0</Version>
    <Fecha>{datetime.now().isoformat()}</Fecha>
    <Estadisticas>
        <CallbacksUltimas24h>{stats.get('total', 0)}</CallbacksUltimas24h>
        <Errores>{stats.get('errors', 0)}</Errores>
    </Estadisticas>
    <Endpoints>
        <Endpoint metodo="POST" tipo="recepcion">/fe/recepcion/api/ecf</Endpoint>
        <Endpoint metodo="POST" tipo="aprobacion">/fe/aprobacioncomercial/api/ecf</Endpoint>
        <Endpoint metodo="GET" tipo="semilla">/fe/autenticacion/api/semilla</Endpoint>
        <Endpoint metodo="POST" tipo="validacion">/fe/autenticacion/api/validacioncertificado</Endpoint>
    </Endpoints>
    <Descripcion>
        Sistema de callbacks para recepción de e-CF y aprobaciones comerciales DGII.
        Flujo de autenticación:
        1. GET /fe/autenticacion/api/semilla - Obtener semilla
        2. POST /fe/autenticacion/api/validacioncertificado - Enviar semilla firmada y recibir token
    </Descripcion>
</ServiceStatus>"""

        return Response(
            response=status_xml,
            status=200,
            content_type='application/xml; charset=utf-8'
        )

    # =========================================================================
    # API de Consulta (para uso interno)
    # =========================================================================

    @http.route(
        '/fe/callback/consulta',
        type='json',
        auth='user',
        methods=['POST'],
        csrf=False
    )
    def consulta_callback(self, track_id=None, encf=None, **kwargs):
        """
        API JSON para consultar estado de callbacks (uso interno).

        Args:
            track_id: ID de seguimiento del documento
            encf: Número e-NCF

        Returns:
            dict con información del callback
        """
        if not track_id and not encf:
            return {'error': 'Se requiere track_id o encf'}

        domain = []
        if track_id:
            domain.append(('track_id', '=', track_id))
        if encf:
            domain.append(('encf', '=', encf))

        callback = request.env['dgii.callback.request'].search(domain, limit=1)

        if not callback:
            return {'error': 'Callback no encontrado', 'track_id': track_id, 'encf': encf}

        return {
            'id': callback.id,
            'name': callback.name,
            'callback_type': callback.callback_type,
            'state': callback.state,
            'track_id': callback.track_id,
            'encf': callback.encf,
            'rnc_emisor': callback.rnc_emisor,
            'received_at': callback.received_at.isoformat() if callback.received_at else None,
            'processed_at': callback.processed_at.isoformat() if callback.processed_at else None,
            'ecf_inbox_id': callback.ecf_inbox_id.id if callback.ecf_inbox_id else None,
        }

    @http.route(
        '/fe/callback/estadisticas',
        type='json',
        auth='user',
        methods=['POST'],
        csrf=False
    )
    def estadisticas_callbacks(self, days=7, **kwargs):
        """
        API JSON para obtener estadísticas de callbacks (uso interno).

        Args:
            days: Número de días a consultar (default 7)

        Returns:
            dict con estadísticas
        """
        return request.env['dgii.callback.request'].get_statistics(days=days)

    # =========================================================================
    # Métodos Auxiliares
    # =========================================================================

    def _find_xml_text(self, root, tag_names):
        """
        Busca el texto de un tag por múltiples nombres, ignorando namespaces.
        """
        for tag in tag_names if isinstance(tag_names, list) else [tag_names]:
            # Buscar sin namespace
            el = root.find(f".//{tag}")
            if el is not None and el.text:
                return el.text.strip()
            # Buscar con cualquier namespace
            for child in root.iter():
                local_name = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                if local_name == tag and child.text:
                    return child.text.strip()
        return None

    def _error_response(self, code, message, status_code=400):
        """Genera una respuesta de error XML."""
        error_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<ErrorResponse xmlns="http://www.dgii.gov.do/ecf">
    <Estado>ERROR</Estado>
    <Codigo>{code}</Codigo>
    <Mensaje>{message}</Mensaje>
    <Fecha>{datetime.now().isoformat()}</Fecha>
</ErrorResponse>"""

        return Response(
            response=error_xml,
            status=status_code,
            content_type='application/xml; charset=utf-8'
        )
