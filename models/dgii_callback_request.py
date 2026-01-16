"""
Modelo para almacenar requests de callbacks DGII.

Este modelo guarda el request raw completo junto con headers para:
- Trazabilidad completa de comunicaciones DGII
- Auditoría de eventos recibidos
- Soporte para idempotencia (evitar procesar duplicados)
- Procesamiento asíncrono posterior
"""
import json
import hashlib
import logging
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class DgiiCallbackRequest(models.Model):
    """Almacena requests de callbacks DGII para procesamiento asíncrono."""

    _name = "dgii.callback.request"
    _description = "Request de Callback DGII"
    _order = "create_date desc, id desc"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    # =========================================================================
    # Identificación
    # =========================================================================
    name = fields.Char(
        string="Referencia",
        compute="_compute_name",
        store=True,
        index=True
    )

    # Clave de idempotencia para evitar duplicados
    idempotency_key = fields.Char(
        string="Clave Idempotencia",
        index=True,
        help="Hash único del request para detectar duplicados"
    )

    # =========================================================================
    # Tipo de Callback
    # =========================================================================
    callback_type = fields.Selection([
        ('recepcion', 'Recepción e-CF'),
        ('aprobacion_comercial', 'Aprobación Comercial'),
        ('autenticacion_semilla', 'Autenticación - Semilla'),
        ('autenticacion_validacion', 'Autenticación - Validación'),
    ], string="Tipo de Callback", required=True, index=True, tracking=True)

    # =========================================================================
    # Datos del Request HTTP
    # =========================================================================
    request_method = fields.Char(string="Método HTTP", default="POST")
    request_path = fields.Char(string="Path", help="Ruta del endpoint llamado")
    request_query_string = fields.Text(string="Query String")

    # Headers (almacenados como JSON)
    request_headers_raw = fields.Text(
        string="Headers (Raw)",
        help="Headers HTTP del request en formato JSON"
    )
    request_headers_display = fields.Text(
        string="Headers",
        compute="_compute_headers_display"
    )

    # Body del request
    request_body_raw = fields.Text(
        string="Body (Raw)",
        help="Contenido raw del request body"
    )
    request_body_display = fields.Text(
        string="Body",
        compute="_compute_body_display"
    )
    content_type = fields.Char(string="Content-Type")
    content_length = fields.Integer(string="Content-Length")

    # IP y User Agent
    remote_ip = fields.Char(string="IP Remota", index=True)
    user_agent = fields.Char(string="User Agent")

    # Timestamp de recepción
    received_at = fields.Datetime(
        string="Fecha/Hora Recepción",
        default=fields.Datetime.now,
        index=True
    )

    # =========================================================================
    # Datos Extraídos del Request
    # =========================================================================
    # Datos comunes extraídos del XML/JSON
    rnc_emisor = fields.Char(string="RNC Emisor", index=True)
    rnc_receptor = fields.Char(string="RNC Receptor", index=True)
    encf = fields.Char(string="e-NCF", index=True)
    track_id = fields.Char(string="Track ID", index=True)
    fecha_emision = fields.Date(string="Fecha Emisión")
    monto_total = fields.Float(string="Monto Total", digits=(16, 2))

    # Para aprobación comercial
    estado_aprobacion = fields.Selection([
        ('aprobado', 'Aprobado'),
        ('rechazado', 'Rechazado'),
    ], string="Estado Aprobación")
    motivo_rechazo = fields.Text(string="Motivo Rechazo")

    # =========================================================================
    # Estado de Procesamiento
    # =========================================================================
    state = fields.Selection([
        ('received', 'Recibido'),
        ('queued', 'En Cola'),
        ('processing', 'Procesando'),
        ('processed', 'Procesado'),
        ('duplicate', 'Duplicado'),
        ('error', 'Error'),
    ], string="Estado", default='received', required=True, index=True, tracking=True)

    # Respuesta enviada al cliente
    response_status_code = fields.Integer(string="Código Respuesta HTTP")
    response_body = fields.Text(string="Respuesta Enviada")
    response_sent_at = fields.Datetime(string="Respuesta Enviada")

    # Procesamiento asíncrono
    job_uuid = fields.Char(string="UUID del Job", index=True)
    processed_at = fields.Datetime(string="Fecha Procesamiento")
    processing_time_ms = fields.Integer(string="Tiempo Proceso (ms)")

    # Errores
    error_message = fields.Text(string="Mensaje de Error")
    error_count = fields.Integer(string="Intentos Fallidos", default=0)

    # =========================================================================
    # Relaciones
    # =========================================================================
    # ID del registro en inbox de e-CF (si se procesa como documento entrante)
    # Usamos Integer en lugar de Many2one para evitar dependencia con l10n_do_e_cf_inbox
    ecf_inbox_id = fields.Integer(
        string="ID Documento Inbox",
        help="ID del registro de bandeja de entrada creado a partir de este callback"
    )

    # Relación con caso de prueba (si aplica)
    test_case_id = fields.Many2one(
        "ecf.test.case",
        string="Caso de Prueba",
        ondelete="set null"
    )

    # Duplicado original (si este es duplicado)
    original_request_id = fields.Many2one(
        "dgii.callback.request",
        string="Request Original",
        ondelete="set null",
        help="Si este request es duplicado, apunta al original"
    )
    duplicate_count = fields.Integer(
        string="# Duplicados",
        compute="_compute_duplicate_count"
    )

    # Compañía
    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        default=lambda self: self.env.company,
        required=True,
        index=True
    )

    # =========================================================================
    # Métodos Computados
    # =========================================================================

    @api.depends('callback_type', 'encf', 'track_id', 'create_date')
    def _compute_name(self):
        type_labels = {
            'recepcion': 'REC',
            'aprobacion_comercial': 'APR',
            'autenticacion_semilla': 'SEM',
            'autenticacion_validacion': 'VAL',
        }
        for record in self:
            parts = []
            if record.callback_type:
                parts.append(type_labels.get(record.callback_type, record.callback_type.upper()[:3]))
            if record.encf:
                parts.append(record.encf)
            elif record.track_id:
                parts.append(record.track_id[:20])
            if record.create_date:
                parts.append(record.create_date.strftime('%Y%m%d-%H%M%S'))
            record.name = "-".join(parts) if parts else f"CB-{record.id}"

    @api.depends('request_headers_raw')
    def _compute_headers_display(self):
        for record in self:
            if record.request_headers_raw:
                try:
                    headers = json.loads(record.request_headers_raw)
                    # Ocultar valores sensibles
                    safe_headers = {}
                    for k, v in headers.items():
                        k_lower = k.lower()
                        if any(x in k_lower for x in ['auth', 'token', 'password', 'key', 'secret', 'cookie']):
                            safe_headers[k] = '***HIDDEN***'
                        else:
                            safe_headers[k] = v
                    record.request_headers_display = json.dumps(safe_headers, indent=2, ensure_ascii=False)
                except Exception:
                    record.request_headers_display = record.request_headers_raw
            else:
                record.request_headers_display = ""

    @api.depends('request_body_raw', 'content_type')
    def _compute_body_display(self):
        for record in self:
            if not record.request_body_raw:
                record.request_body_display = ""
                continue

            body = record.request_body_raw
            content_type = (record.content_type or '').lower()

            # Intentar formatear según content-type
            if 'json' in content_type:
                try:
                    obj = json.loads(body)
                    record.request_body_display = json.dumps(obj, indent=2, ensure_ascii=False)
                    continue
                except Exception:
                    pass

            if 'xml' in content_type:
                try:
                    from lxml import etree
                    root = etree.fromstring(body.encode('utf-8'))
                    record.request_body_display = etree.tostring(
                        root, pretty_print=True, encoding='unicode'
                    )
                    continue
                except Exception:
                    pass

            # Si no se puede formatear, mostrar raw (truncado si es muy largo)
            if len(body) > 50000:
                record.request_body_display = body[:50000] + "\n...[TRUNCATED]..."
            else:
                record.request_body_display = body

    def _compute_duplicate_count(self):
        for record in self:
            record.duplicate_count = self.search_count([
                ('original_request_id', '=', record.id)
            ])

    # =========================================================================
    # Métodos de Creación y Gestión
    # =========================================================================

    @api.model
    def create_from_http_request(self, http_request, callback_type):
        """
        Crea un registro a partir de un request HTTP de Odoo.

        Args:
            http_request: request de odoo.http.request.httprequest
            callback_type: tipo de callback ('recepcion', 'aprobacion_comercial', etc.)

        Returns:
            dgii.callback.request: registro creado
        """
        # Extraer headers
        headers = {}
        for key, value in http_request.headers:
            headers[key] = value

        # Extraer body - manejar multipart/form-data
        content_type = headers.get('Content-Type', '')
        body = ""

        if 'multipart/form-data' in content_type:
            # DGII envía el XML como multipart/form-data
            # Intentar extraer de los files primero
            _logger.info("[DGII Callback] Detectado multipart/form-data, extrayendo archivos...")

            # Log de todos los files recibidos
            if http_request.files:
                for key, file_storage in http_request.files.items():
                    _logger.info("[DGII Callback] File encontrado: key=%s, filename=%s, content_type=%s",
                                key, file_storage.filename, file_storage.content_type)
                    # Leer el contenido del archivo
                    file_content = file_storage.read()
                    if isinstance(file_content, bytes):
                        try:
                            body = file_content.decode('utf-8')
                        except UnicodeDecodeError:
                            body = file_content.decode('latin-1')
                    else:
                        body = file_content
                    # Reset del stream por si se necesita leer de nuevo
                    file_storage.seek(0)
                    _logger.info("[DGII Callback] Contenido del file (primeros 1000): %s", body[:1000] if body else "EMPTY")
                    break  # Tomar solo el primer archivo

            # Si no hay files, intentar leer de form data
            if not body and http_request.form:
                _logger.info("[DGII Callback] No hay files, buscando en form data...")
                for key, value in http_request.form.items():
                    _logger.info("[DGII Callback] Form field: key=%s, value_len=%d", key, len(str(value)) if value else 0)
                    if value and len(str(value)) > len(body):
                        body = str(value)

            # Si aún no hay body, intentar leer raw data
            if not body:
                _logger.info("[DGII Callback] No hay form data, intentando raw data...")
                raw_data = http_request.get_data(as_text=True)
                if raw_data:
                    body = raw_data
                    _logger.info("[DGII Callback] Raw data length: %d", len(body))
        else:
            # Content-Type normal (application/xml, application/json, etc.)
            body = http_request.data
            if isinstance(body, bytes):
                try:
                    body = body.decode('utf-8')
                except UnicodeDecodeError:
                    body = body.decode('latin-1')

        # Generar clave de idempotencia
        idempotency_key = self._generate_idempotency_key(callback_type, body, headers)

        # Verificar si es duplicado
        existing = self.search([
            ('idempotency_key', '=', idempotency_key),
            ('state', 'not in', ['error'])  # Solo considerar exitosos o en proceso
        ], limit=1)

        is_duplicate = bool(existing)

        vals = {
            'callback_type': callback_type,
            'request_method': http_request.method,
            'request_path': http_request.path,
            'request_query_string': http_request.query_string.decode('utf-8') if http_request.query_string else '',
            'request_headers_raw': json.dumps(headers, ensure_ascii=False),
            'request_body_raw': body,
            'content_type': headers.get('Content-Type', ''),
            'content_length': int(headers.get('Content-Length', 0) or 0),
            'remote_ip': http_request.remote_addr,
            'user_agent': headers.get('User-Agent', ''),
            'received_at': fields.Datetime.now(),
            'idempotency_key': idempotency_key,
            'state': 'duplicate' if is_duplicate else 'received',
            'original_request_id': existing.id if is_duplicate else False,
        }

        record = self.create(vals)

        # Extraer datos del body si es posible
        record._extract_data_from_body()

        _logger.info(
            "[DGII Callback] Request creado: ID=%s, tipo=%s, duplicado=%s, IP=%s",
            record.id, callback_type, is_duplicate, record.remote_ip
        )

        return record

    def _generate_idempotency_key(self, callback_type, body, headers):
        """
        Genera una clave única para detectar duplicados.

        La clave se basa en:
        - Tipo de callback
        - Contenido del body (hash)
        - Headers relevantes (Authorization si existe)
        """
        key_parts = [callback_type]

        # Hash del body
        if body:
            body_hash = hashlib.sha256(body.encode('utf-8') if isinstance(body, str) else body).hexdigest()[:32]
            key_parts.append(body_hash)

        # Incluir Authorization header si existe (indica mismo emisor)
        auth_header = headers.get('Authorization', headers.get('authorization', ''))
        if auth_header:
            auth_hash = hashlib.md5(auth_header.encode()).hexdigest()[:8]
            key_parts.append(auth_hash)

        return ":".join(key_parts)

    def _extract_data_from_body(self):
        """Extrae datos relevantes del body del request."""
        self.ensure_one()

        if not self.request_body_raw:
            return

        body = self.request_body_raw
        content_type = (self.content_type or '').lower()

        extracted = {}

        # Intentar parsear como XML
        if 'xml' in content_type or body.strip().startswith('<?xml') or body.strip().startswith('<'):
            extracted = self._extract_from_xml(body)
        # Intentar parsear como JSON
        elif 'json' in content_type or body.strip().startswith('{'):
            extracted = self._extract_from_json(body)

        if extracted:
            self.write(extracted)

    def _extract_from_xml(self, xml_string):
        """Extrae datos de un XML."""
        try:
            from lxml import etree
            root = etree.fromstring(xml_string.encode('utf-8'))

            def find_text(tag_names):
                """Busca el texto de un tag por múltiples nombres."""
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

            extracted = {}

            # Datos comunes
            rnc_emisor = find_text(['RNCEmisor', 'RncEmisor', 'rnc_emisor'])
            if rnc_emisor:
                extracted['rnc_emisor'] = rnc_emisor

            rnc_receptor = find_text(['RNCComprador', 'RncComprador', 'RNCReceptor', 'rnc_receptor'])
            if rnc_receptor:
                extracted['rnc_receptor'] = rnc_receptor

            encf = find_text(['eNCF', 'ENCF', 'encf', 'NumeroNCF', 'NCF'])
            if encf:
                extracted['encf'] = encf

            track_id = find_text(['TrackId', 'TrackID', 'trackId', 'track_id'])
            if track_id:
                extracted['track_id'] = track_id

            fecha = find_text(['FechaEmision', 'fechaEmision', 'Fecha'])
            if fecha:
                try:
                    # DGII puede enviar DD-MM-YYYY o YYYY-MM-DD
                    fecha_str = fecha[:10]
                    if '-' in fecha_str:
                        parts = fecha_str.split('-')
                        if len(parts) == 3:
                            # Si el primer segmento tiene 4 dígitos, es YYYY-MM-DD
                            if len(parts[0]) == 4:
                                extracted['fecha_emision'] = fecha_str
                            # Si el primer segmento tiene 2 dígitos, es DD-MM-YYYY
                            elif len(parts[0]) == 2:
                                # Convertir DD-MM-YYYY a YYYY-MM-DD
                                extracted['fecha_emision'] = f"{parts[2]}-{parts[1]}-{parts[0]}"
                except Exception:
                    pass

            monto = find_text(['MontoTotal', 'montoTotal', 'Total'])
            if monto:
                try:
                    extracted['monto_total'] = float(monto.replace(',', ''))
                except Exception:
                    pass

            # Para aprobación comercial
            estado = find_text(['EstadoAprobacion', 'Estado', 'estado'])
            if estado:
                estado_lower = estado.lower()
                if 'aprob' in estado_lower:
                    extracted['estado_aprobacion'] = 'aprobado'
                elif 'rechaz' in estado_lower:
                    extracted['estado_aprobacion'] = 'rechazado'

            motivo = find_text(['MotivoRechazo', 'Motivo', 'motivoRechazo'])
            if motivo:
                extracted['motivo_rechazo'] = motivo

            return extracted

        except Exception as e:
            _logger.warning("[DGII Callback] Error extrayendo datos de XML: %s", e)
            return {}

    def _extract_from_json(self, json_string):
        """Extrae datos de un JSON."""
        try:
            data = json.loads(json_string)

            def find_value(keys):
                """Busca un valor en el dict usando múltiples claves."""
                for key in keys if isinstance(keys, list) else [keys]:
                    if key in data:
                        return data[key]
                    # Buscar en subestructuras
                    for subkey in ['ECF', 'ecf', 'data', 'Encabezado', 'Emisor', 'Comprador']:
                        if subkey in data and isinstance(data[subkey], dict):
                            if key in data[subkey]:
                                return data[subkey][key]
                return None

            extracted = {}

            rnc_emisor = find_value(['RNCEmisor', 'rncEmisor', 'rnc_emisor'])
            if rnc_emisor:
                extracted['rnc_emisor'] = str(rnc_emisor)

            rnc_receptor = find_value(['RNCComprador', 'rncComprador', 'RNCReceptor'])
            if rnc_receptor:
                extracted['rnc_receptor'] = str(rnc_receptor)

            encf = find_value(['eNCF', 'encf', 'ENCF', 'ncf'])
            if encf:
                extracted['encf'] = str(encf)

            track_id = find_value(['trackId', 'TrackId', 'track_id'])
            if track_id:
                extracted['track_id'] = str(track_id)

            monto = find_value(['MontoTotal', 'montoTotal', 'total'])
            if monto:
                try:
                    extracted['monto_total'] = float(monto)
                except Exception:
                    pass

            return extracted

        except Exception as e:
            _logger.warning("[DGII Callback] Error extrayendo datos de JSON: %s", e)
            return {}

    # =========================================================================
    # Procesamiento Asíncrono
    # =========================================================================

    def queue_for_processing(self):
        """Encola el request para procesamiento asíncrono."""
        self.ensure_one()

        if self.state not in ['received']:
            _logger.warning(
                "[DGII Callback] Request %s no está en estado 'received', estado actual: %s",
                self.id, self.state
            )
            return False

        # Marcar como encolado
        self.write({'state': 'queued'})

        # Intentar usar queue_job si está disponible
        try:
            # Verificar si el modelo queue.job existe
            if 'queue.job' in self.env:
                self.with_delay(
                    channel='root.dgii_callbacks',
                    description=f"Procesar callback DGII: {self.name}"
                ).process_callback()
                _logger.info("[DGII Callback] Request %s encolado con queue_job", self.id)
            else:
                # Procesar síncronamente si no hay queue_job
                self.process_callback()
        except Exception as e:
            _logger.warning(
                "[DGII Callback] queue_job no disponible, procesando síncronamente: %s", e
            )
            self.process_callback()

        return True

    def process_callback(self):
        """
        Procesa el callback según su tipo.
        Este método es llamado por el job asíncrono.
        """
        self.ensure_one()

        start_time = datetime.now()
        _logger.info("[DGII Callback] Procesando request %s, tipo=%s", self.id, self.callback_type)

        try:
            self.write({'state': 'processing'})

            # Procesar según tipo
            if self.callback_type == 'recepcion':
                result = self._process_recepcion()
            elif self.callback_type == 'aprobacion_comercial':
                result = self._process_aprobacion_comercial()
            elif self.callback_type in ['autenticacion_semilla', 'autenticacion_validacion']:
                result = self._process_autenticacion()
            else:
                result = {'success': False, 'error': f"Tipo de callback no soportado: {self.callback_type}"}

            # Calcular tiempo de procesamiento
            processing_time = int((datetime.now() - start_time).total_seconds() * 1000)

            if result.get('success'):
                self.write({
                    'state': 'processed',
                    'processed_at': fields.Datetime.now(),
                    'processing_time_ms': processing_time,
                })
                _logger.info(
                    "[DGII Callback] Request %s procesado exitosamente en %dms",
                    self.id, processing_time
                )
            else:
                self.write({
                    'state': 'error',
                    'error_message': result.get('error', 'Error desconocido'),
                    'error_count': self.error_count + 1,
                    'processing_time_ms': processing_time,
                })
                _logger.error(
                    "[DGII Callback] Error procesando request %s: %s",
                    self.id, result.get('error')
                )

            return result

        except Exception as e:
            _logger.exception("[DGII Callback] Excepción procesando request %s", self.id)
            self.write({
                'state': 'error',
                'error_message': str(e),
                'error_count': self.error_count + 1,
            })
            return {'success': False, 'error': str(e)}

    def _process_recepcion(self):
        """Procesa un callback de recepción de e-CF."""
        self.ensure_one()

        # Verificar si existe modelo e.cf.inbox
        if 'e.cf.inbox' not in self.env:
            _logger.info("[DGII Callback] Modelo e.cf.inbox no disponible, solo registrando")
            return {'success': True, 'message': 'Registrado sin crear inbox'}

        # Verificar datos mínimos
        if not self.encf and not self.request_body_raw:
            return {'success': False, 'error': 'No hay datos suficientes para crear inbox'}

        try:
            # Buscar si ya existe un documento con este e-NCF
            existing = self.env['e.cf.inbox'].search([
                ('e_ncf', '=', self.encf)
            ], limit=1) if self.encf else None

            if existing:
                self.write({'ecf_inbox_id': existing.id})
                return {'success': True, 'message': 'Documento ya existía en inbox', 'inbox_id': existing.id}

            # Crear registro en inbox
            inbox_vals = {
                'name': f"Callback DGII - {self.encf or self.track_id or 'Sin ID'}",
                'supplier_vat': self.rnc_emisor,
                'e_ncf': self.encf,
                'issue_date': self.fecha_emision,
                'total_amount': self.monto_total,
                'state': 'pending',
            }

            # Si hay XML, crear attachment
            if self.request_body_raw and 'xml' in (self.content_type or '').lower():
                import base64
                attachment = self.env['ir.attachment'].create({
                    'name': f"{self.encf or 'ecf'}_recibido.xml",
                    'type': 'binary',
                    'datas': base64.b64encode(self.request_body_raw.encode('utf-8')),
                    'mimetype': 'application/xml',
                })
                inbox_vals['xml_attachment_id'] = attachment.id

            inbox = self.env['e.cf.inbox'].create(inbox_vals)
            self.write({'ecf_inbox_id': inbox.id})

            _logger.info(
                "[DGII Callback] Inbox creado: ID=%s, e-NCF=%s",
                inbox.id, self.encf
            )

            return {'success': True, 'inbox_id': inbox.id}

        except Exception as e:
            return {'success': False, 'error': f"Error creando inbox: {str(e)}"}

    def _process_aprobacion_comercial(self):
        """Procesa un callback de aprobación comercial."""
        self.ensure_one()

        # Buscar el documento relacionado
        if 'e.cf.inbox' not in self.env:
            return {'success': True, 'message': 'Registrado sin actualizar inbox'}

        # Buscar por track_id o encf
        domain = []
        if self.track_id:
            domain = [('track_id', '=', self.track_id)]
        elif self.encf:
            domain = [('e_ncf', '=', self.encf)]
        else:
            return {'success': False, 'error': 'No hay track_id ni e-NCF para buscar documento'}

        inbox = self.env['e.cf.inbox'].search(domain, limit=1)

        if not inbox:
            return {'success': False, 'error': f"Documento no encontrado con {domain}"}

        # Actualizar estado
        new_state = 'accepted' if self.estado_aprobacion == 'aprobado' else 'rejected'
        inbox.write({
            'state': new_state,
            'commercial_approval_sent': True,
            'dgii_response': self.request_body_raw,
        })

        self.write({'ecf_inbox_id': inbox.id})

        return {'success': True, 'inbox_id': inbox.id, 'new_state': new_state}

    def _process_autenticacion(self):
        """Procesa callbacks de autenticación (solo logging)."""
        # Los callbacks de autenticación solo se registran, no requieren procesamiento adicional
        return {'success': True, 'message': 'Autenticación registrada'}

    # =========================================================================
    # Acciones
    # =========================================================================

    def action_reprocess(self):
        """Reprocesa un callback que falló."""
        self.ensure_one()
        if self.state not in ['error', 'received']:
            raise UserError(_("Solo se pueden reprocesar callbacks en estado 'Error' o 'Recibido'."))

        self.write({
            'state': 'received',
            'error_message': False,
        })
        return self.queue_for_processing()

    def action_mark_duplicate(self):
        """Marca manualmente como duplicado."""
        self.ensure_one()
        self.write({'state': 'duplicate'})
        return True

    def action_view_inbox(self):
        """Abre el documento inbox relacionado."""
        self.ensure_one()
        if not self.ecf_inbox_id:
            raise UserError(_("No hay documento inbox relacionado."))

        if 'e.cf.inbox' not in self.env:
            raise UserError(_("El módulo de bandeja de entrada (e.cf.inbox) no está instalado."))

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'e.cf.inbox',
            'res_id': self.ecf_inbox_id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_download_body(self):
        """Descarga el body del request."""
        self.ensure_one()
        if not self.request_body_raw:
            raise UserError(_("No hay body para descargar."))

        import base64

        # Determinar extensión
        ext = 'txt'
        mimetype = 'text/plain'
        if 'xml' in (self.content_type or '').lower():
            ext = 'xml'
            mimetype = 'application/xml'
        elif 'json' in (self.content_type or '').lower():
            ext = 'json'
            mimetype = 'application/json'

        filename = f"callback_{self.callback_type}_{self.id}.{ext}"

        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(self.request_body_raw.encode('utf-8')),
            'mimetype': mimetype,
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'new',
        }

    # =========================================================================
    # Limpieza y Mantenimiento
    # =========================================================================

    @api.model
    def cleanup_old_records(self, days=90):
        """Elimina registros antiguos (llamar desde cron)."""
        cutoff_date = fields.Datetime.now() - timedelta(days=days)

        # Mantener registros con errores más tiempo
        old_records = self.search([
            ('create_date', '<', cutoff_date),
            ('state', 'in', ['processed', 'duplicate']),
        ])

        count = len(old_records)
        old_records.unlink()

        _logger.info("[DGII Callback] Limpieza: %d registros eliminados (>%d días)", count, days)
        return count

    @api.model
    def get_statistics(self, days=7):
        """Retorna estadísticas de callbacks."""
        from_date = fields.Datetime.now() - timedelta(days=days)

        domain = [('create_date', '>=', from_date)]

        stats = {
            'total': self.search_count(domain),
            'by_type': {},
            'by_state': {},
            'duplicates': self.search_count(domain + [('state', '=', 'duplicate')]),
            'errors': self.search_count(domain + [('state', '=', 'error')]),
        }

        # Estadísticas por tipo
        for cb_type in ['recepcion', 'aprobacion_comercial', 'autenticacion_semilla', 'autenticacion_validacion']:
            stats['by_type'][cb_type] = self.search_count(domain + [('callback_type', '=', cb_type)])

        # Estadísticas por estado
        for state in ['received', 'queued', 'processing', 'processed', 'duplicate', 'error']:
            stats['by_state'][state] = self.search_count(domain + [('state', '=', state)])

        return stats
