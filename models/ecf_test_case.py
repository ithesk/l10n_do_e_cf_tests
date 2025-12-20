import json
import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class EcfTestCase(models.Model):
    _name = "ecf.test.case"
    _description = "Caso de Prueba e-CF Individual"
    _order = "sequence, id"

    # Control
    sequence = fields.Integer(string="Secuencia", default=10, index=True)
    name = fields.Char(string="Nombre del Caso", required=True)
    test_set_id = fields.Many2one("ecf.test.set", string="Set de Pruebas", ondelete="cascade", required=True)
    fila_excel = fields.Integer(string="Fila en Excel", help="Número de fila original en el set de pruebas.")
    id_lote = fields.Char(string="ID de Lote", index=True, help="UUID generado por importación.")

    # Pruebas de Volumen
    is_volume_case = fields.Boolean(
        string="Caso de Volumen",
        default=False,
        help="Indica si este caso fue generado para pruebas de volumen"
    )
    template_case_id = fields.Many2one(
        "ecf.test.case",
        string="Caso Plantilla",
        help="Caso original usado como plantilla para generar este caso de volumen"
    )
    volume_sequence = fields.Integer(
        string="Secuencia Volumen",
        help="Número de secuencia asignado en pruebas de volumen"
    )

    # Tipo de Comprobante
    tipo_ecf = fields.Selection([
        ('31', 'B01 - Factura de Crédito Fiscal'),
        ('32', 'B02 - Factura de Consumo'),
        ('33', 'B03 - Nota de Débito'),
        ('34', 'B04 - Nota de Crédito'),
        ('41', 'B11 - Regímenes Especiales'),
        ('43', 'B13 - Exportaciones'),
        ('44', 'B14 - Remesas'),
        ('45', 'B15 - Zonas Francas'),
        ('46', 'B16 - Pagos al Exterior'),
        ('47', 'B17 - Gubernamental'),
    ], string="Tipo e-CF", required=True)

    # Datos del Receptor
    receptor_rnc = fields.Char(string="RNC/Cédula Receptor")
    receptor_nombre = fields.Char(string="Nombre Receptor")
    receptor_tipo_identificacion = fields.Selection([
        ('1', 'RNC'),
        ('2', 'Cédula'),
        ('3', 'Pasaporte'),
    ], string="Tipo Identificación", default='1')
    identificador_extranjero = fields.Char(string="Identificador Extranjero")

    # Datos del Comprobante
    fecha_comprobante = fields.Date(string="Fecha Comprobante")
    moneda = fields.Char(string="Moneda", default="DOP")
    tipo_ingreso = fields.Selection([
        ('01', 'Ingresos por Operaciones (No Financieros)'),
        ('02', 'Ingresos Financieros'),
        ('03', 'Ingresos Extraordinarios'),
        ('04', 'Ingresos por Arrendamiento'),
        ('05', 'Ingresos por Venta de Activos Depreciables'),
        ('06', 'Otros Ingresos'),
    ], string="Tipo de Ingresos")

    tipo_pago = fields.Selection([
        ('1', 'Contado'),
        ('2', 'Crédito'),
        ('3', 'Gratuito'),
    ], string="Tipo de Pago", default='1')

    fecha_vencimiento = fields.Date(string="Fecha de Vencimiento")

    # Montos
    monto_subtotal = fields.Float(string="Subtotal", digits=(16, 2))
    monto_descuento = fields.Float(string="Descuento", digits=(16, 2))
    monto_gravado_total = fields.Float(string="Monto Gravado Total", digits=(16, 2))
    monto_gravado_i1 = fields.Float(string="Monto Gravado ITBIS 1", digits=(16, 2))
    monto_gravado_i2 = fields.Float(string="Monto Gravado ITBIS 2", digits=(16, 2))
    monto_gravado_i3 = fields.Float(string="Monto Gravado ITBIS 3", digits=(16, 2))
    monto_exento = fields.Float(string="Monto Exento", digits=(16, 2))

    total_itbis = fields.Float(string="Total ITBIS", digits=(16, 2))
    total_itbis1 = fields.Float(string="ITBIS 1", digits=(16, 2))
    total_itbis2 = fields.Float(string="ITBIS 2", digits=(16, 2))
    total_itbis3 = fields.Float(string="ITBIS 3", digits=(16, 2))

    monto_total = fields.Float(string="Monto Total", digits=(16, 2))
    monto_total_pagar = fields.Float(string="Total a Pagar", digits=(16, 2))

    # Para NC/ND
    ncf_modificado = fields.Char(string="NCF Modificado")
    razon_modificacion = fields.Selection([
        ('01', 'Anulación'),
        ('02', 'Corrección'),
        ('03', 'Devolución'),
        ('04', 'Descuento'),
        ('05', 'Bonificación'),
    ], string="Razón de Modificación")

    # Items/Líneas (simplificado - se puede extender)
    cantidad_items = fields.Integer(string="Cantidad de Items", default=1)
    descripcion_item = fields.Char(string="Descripción Item")
    precio_unitario = fields.Float(string="Precio Unitario", digits=(16, 2))

    # Payload y trazabilidad
    hash_input = fields.Char(string="Hash de Entrada", index=True)
    payload_json = fields.Text(string="Payload JSON Canónico")
    # Campos de respuesta API - editables para pruebas de QR y otros valores
    api_response = fields.Text(string="Respuesta API (JSON)", help="Respuesta JSON parseada de la API.")
    api_response_raw = fields.Text(string="Respuesta API Completa", help="Respuesta completa sin procesar de la API.")
    signed_xml = fields.Text(string="XML Firmado", help="XML firmado devuelto por la API (si aplica).")
    api_status = fields.Selection([
        ('pending', 'Pendiente'),
        ('sent', 'Enviado'),
        ('accepted', 'Aceptado'),
        ('rejected', 'Rechazado'),
        ('error', 'Error'),
    ], string="Estado API", default='pending', help="Editable para pruebas.")

    # Estado global del caso
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('payload_ready', 'Payload Listo'),
        ('sent', 'Enviado a API'),
        ('accepted', 'Aceptado'),
        ('rejected', 'Rechazado'),
        ('error', 'Error'),
    ], string="Estado", default='draft', help="Editable para pruebas.")

    # Campos de respuesta DGII - editables para pruebas de generación de QR
    track_id = fields.Char(string="TrackID DGII", help="Editable para pruebas. ID de seguimiento devuelto por DGII.")
    qr_url = fields.Char(string="URL del QR", help="Editable para pruebas. URL o base64 del código QR.")
    security_code = fields.Char(string="Código de Seguridad", help="Editable para pruebas. Código de seguridad DGII.")
    dgii_response = fields.Text(string="Respuesta DGII", help="Editable para pruebas. Respuesta completa de DGII.")
    error_message = fields.Text(string="Mensaje de Error", help="Editable para pruebas.")
    expected_result = fields.Char(string="Resultado Esperado")
    actual_result = fields.Char(string="Resultado Obtenido", help="Editable para pruebas.")

    # Relación con logs de API
    api_log_ids = fields.One2many(
        "ecf.api.log",
        "test_case_id",
        string="Logs de API",
        help="Historial de llamadas a la API para este caso"
    )
    api_log_count = fields.Integer(
        string="# Logs",
        compute="_compute_api_log_count"
    )

    @api.depends('api_log_ids')
    def _compute_api_log_count(self):
        for case in self:
            case.api_log_count = len(case.api_log_ids)

    def action_view_api_logs(self):
        """Acción para ver los logs de API relacionados"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Logs API - {self.name}',
            'res_model': 'ecf.api.log',
            'domain': [('test_case_id', '=', self.id)],
            'view_mode': 'list,form',
            'context': {'default_test_case_id': self.id},
        }

    def action_create_invoice(self):
        """Deprecado: el flujo ahora es Excel -> JSON -> API, no crea facturas."""
        raise UserError(_("El flujo de facturas Odoo fue removido. Use el wizard de importación para enviar a la API interna."))

    def action_validate_invoice(self):
        """Deprecado: el flujo ahora es Excel -> JSON -> API, no valida facturas."""
        raise UserError(_("El flujo de facturas Odoo fue removido. Use el wizard de importación para enviar a la API interna."))

    def set_payload(self, payload_dict, hash_input, id_lote, fila_excel):
        """Guardar payload y trazabilidad en el caso."""
        # Guardar JSON formateado con indentación para fácil lectura/edición
        self.write({
            'payload_json': json.dumps(payload_dict, indent=2, ensure_ascii=False),
            'hash_input': hash_input,
            'id_lote': id_lote,
            'fila_excel': fila_excel,
            'state': 'payload_ready',
            'api_status': 'pending',
        })

    def mark_sent(self, response_text, track_id=None, accepted=False, rejected=False,
                  raw_response=None, signed_xml=None):
        """Actualizar estado después de envío a la API."""
        new_state = 'sent'
        api_status = 'sent'
        if accepted:
            new_state = 'accepted'
            api_status = 'accepted'
        elif rejected:
            new_state = 'rejected'
            api_status = 'rejected'

        vals = {
            'api_response': response_text,
            'track_id': track_id,
            'state': new_state,
            'api_status': api_status,
        }

        # Agregar campos opcionales si están presentes
        if raw_response:
            vals['api_response_raw'] = raw_response
        if signed_xml:
            vals['signed_xml'] = signed_xml

        self.write(vals)

    def mark_error(self, message):
        """Guardar error de procesamiento."""
        self.write({
            'error_message': message,
            'state': 'error',
            'api_status': 'error',
        })

    def action_download_signed_xml(self):
        """Descarga el XML firmado como archivo"""
        import base64
        self.ensure_one()
        if not self.signed_xml:
            raise UserError(_("No hay XML firmado disponible para descargar."))

        # Usar eNCF para el nombre del archivo
        encf = 'documento'
        if self.payload_json:
            try:
                doc = json.loads(self.payload_json)
                encf = doc.get('ECF', {}).get('Encabezado', {}).get('IdDoc', {}).get('eNCF', 'documento')
            except Exception:
                pass

        filename = f"{encf}_firmado.xml"
        xml_content = self.signed_xml.encode('utf-8')
        b64_content = base64.b64encode(xml_content).decode('utf-8')

        # Crear attachment temporal
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': b64_content,
            'mimetype': 'application/xml',
            'res_model': self._name,
            'res_id': self.id,
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'new',
        }

    # ========================================================================
    # Visualización de JSON
    # ========================================================================

    payload_json_formatted = fields.Text(
        string="JSON Formateado",
        compute="_compute_payload_json_formatted",
        help="JSON del e-CF formateado para fácil lectura"
    )

    json_validation_status = fields.Selection([
        ('valid', 'Válido'),
        ('invalid', 'Inválido'),
        ('empty', 'Sin JSON'),
    ], string="Estado JSON", compute="_compute_json_validation", store=False)

    json_validation_message = fields.Text(
        string="Validación JSON",
        compute="_compute_json_validation",
        help="Resultado de la validación del JSON"
    )

    @api.depends('payload_json')
    def _compute_payload_json_formatted(self):
        for case in self:
            if case.payload_json:
                try:
                    data = json.loads(case.payload_json)
                    case.payload_json_formatted = json.dumps(data, indent=2, ensure_ascii=False)
                except Exception:
                    case.payload_json_formatted = case.payload_json
            else:
                case.payload_json_formatted = ""

    @api.depends('payload_json')
    def _compute_json_validation(self):
        """Valida la estructura del JSON contra los requisitos DGII"""
        for case in self:
            if not case.payload_json:
                case.json_validation_status = 'empty'
                case.json_validation_message = "No hay JSON generado todavía."
                continue

            try:
                data = json.loads(case.payload_json)
                errors = []

                # Validar estructura básica
                if "ECF" not in data:
                    errors.append("Falta nodo raíz 'ECF'")
                else:
                    ecf = data["ECF"]

                    # Validar Encabezado
                    if "Encabezado" not in ecf:
                        errors.append("Falta 'Encabezado'")
                    else:
                        enc = ecf["Encabezado"]

                        # IdDoc
                        if "IdDoc" not in enc:
                            errors.append("Falta 'IdDoc' en Encabezado")
                        else:
                            iddoc = enc["IdDoc"]
                            if not iddoc.get("TipoeCF"):
                                errors.append("Falta 'TipoeCF' en IdDoc")
                            if not iddoc.get("eNCF"):
                                errors.append("Falta 'eNCF' en IdDoc")

                        # Emisor
                        if "Emisor" not in enc:
                            errors.append("Falta 'Emisor' en Encabezado")
                        else:
                            emisor = enc["Emisor"]
                            if not emisor.get("RNCEmisor"):
                                errors.append("Falta 'RNCEmisor' en Emisor")
                            if not emisor.get("FechaEmision"):
                                errors.append("Falta 'FechaEmision' en Emisor")

                        # Totales
                        if "Totales" not in enc:
                            errors.append("Falta 'Totales' en Encabezado")

                    # DetallesItems
                    if "DetallesItems" not in ecf:
                        errors.append("Falta 'DetallesItems'")
                    else:
                        items = ecf["DetallesItems"]
                        if "Item" not in items or not items["Item"]:
                            errors.append("No hay items en 'DetallesItems'")

                    # FechaHoraFirma
                    if not ecf.get("FechaHoraFirma"):
                        errors.append("Falta 'FechaHoraFirma'")

                if errors:
                    case.json_validation_status = 'invalid'
                    case.json_validation_message = "⚠️ Errores encontrados:\n• " + "\n• ".join(errors)
                else:
                    case.json_validation_status = 'valid'
                    case.json_validation_message = "✅ JSON válido. Estructura correcta para envío a DGII."

            except json.JSONDecodeError as e:
                case.json_validation_status = 'invalid'
                case.json_validation_message = f"❌ Error de sintaxis JSON: {str(e)}"
            except Exception as e:
                case.json_validation_status = 'invalid'
                case.json_validation_message = f"❌ Error al validar: {str(e)}"

    def action_download_json(self):
        """Descarga el JSON del caso como archivo"""
        import base64
        self.ensure_one()

        if not self.payload_json:
            raise UserError(_("No hay JSON generado para este caso."))

        # Formatear JSON
        try:
            data = json.loads(self.payload_json)
            json_content = json.dumps(data, indent=2, ensure_ascii=False)
        except Exception:
            json_content = self.payload_json

        # Crear nombre de archivo
        tipo = self.tipo_ecf or "XX"
        encf = ""
        try:
            data = json.loads(self.payload_json)
            encf = data.get("ECF", {}).get("Encabezado", {}).get("IdDoc", {}).get("eNCF", "")
        except Exception:
            pass

        filename = f"ecf_{tipo}_{encf or self.id}.json"

        # Crear attachment temporal y descargar
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(json_content.encode('utf-8')),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/json',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def action_copy_json_to_clipboard(self):
        """Copia el JSON al portapapeles (muestra notificación con el JSON)"""
        self.ensure_one()

        if not self.payload_json:
            raise UserError(_("No hay JSON generado para este caso."))

        # En Odoo web, no podemos copiar directamente al portapapeles,
        # pero podemos mostrar el JSON en una notificación para que el usuario lo copie
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('JSON del e-CF'),
                'message': _('Use Ctrl+C para copiar el JSON desde la pestaña "JSON Generado"'),
                'type': 'info',
                'sticky': False,
            }
        }

    def action_format_json(self):
        """Formatea el JSON con indentación para mejor lectura"""
        self.ensure_one()

        if not self.payload_json:
            raise UserError(_("No hay JSON para formatear."))

        try:
            # Parsear y re-formatear con indentación
            data = json.loads(self.payload_json)
            formatted = json.dumps(data, indent=2, ensure_ascii=False)
            self.write({'payload_json': formatted})

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('JSON Formateado'),
                    'message': _('El JSON ha sido formateado correctamente.'),
                    'type': 'success',
                    'sticky': False,
                }
            }
        except json.JSONDecodeError as e:
            raise UserError(_("Error al formatear JSON: %s") % str(e))

    def action_send_to_api(self):
        """Envía el JSON actual a la API configurada (usa el sistema de proveedores)"""
        self.ensure_one()

        if not self.payload_json:
            raise UserError(_("No hay JSON para enviar."))

        # Parsear el JSON actual
        try:
            doc = json.loads(self.payload_json)
        except json.JSONDecodeError as e:
            self.write({
                'error_message': f"JSON inválido: {str(e)}",
                'state': 'error',
                'api_status': 'error',
            })
            raise UserError(_("El JSON no es válido: %s") % str(e))

        # Obtener el proveedor de API por defecto
        provider = self.env['ecf.api.provider'].get_default_provider()

        if not provider:
            raise UserError(_("No hay proveedor de API configurado. Configure uno en e-CF Tests > Proveedores de API."))

        _logger.info(f"[Test Case] Enviando caso {self.name} via proveedor: {provider.name} ({provider.provider_type})")

        # Extraer RNC y eNCF del documento
        rnc = None
        encf = None
        if isinstance(doc, dict):
            ecf_data = doc.get('ECF', doc)
            encabezado = ecf_data.get('Encabezado', {})
            emisor = encabezado.get('Emisor', {})
            id_doc = encabezado.get('IdDoc', {})
            rnc = emisor.get('RNCEmisor')
            encf = id_doc.get('eNCF')

        # Enviar usando el proveedor (ahora devuelve 6 valores y registra en log)
        success, resp_data, track_id, error_msg, raw_response, signed_xml = provider.send_ecf(
            doc, rnc=rnc, encf=encf,
            origin='test_case',
            test_case_id=self.id
        )

        # Formatear respuesta
        resp_text = json.dumps(resp_data, indent=2, ensure_ascii=False) if resp_data else error_msg

        # Obtener la URL de validación DGII del log de API (ya calculada y probada)
        qr_url = None
        security_code = None

        # Buscar el log más reciente creado para este caso
        api_log = self.env['ecf.api.log'].search([
            ('test_case_id', '=', self.id)
        ], order='create_date desc', limit=1)

        if api_log and api_log.dgii_validation_url:
            qr_url = api_log.dgii_validation_url
            security_code = api_log.xml_security_code
            _logger.info(f"[Test Case] URL QR obtenida del log: {qr_url[:80] if qr_url else 'None'}...")
        else:
            _logger.info(f"[Test Case] No se encontró URL de validación en el log")

        if success:
            self.write({
                'api_response': resp_text,
                'api_response_raw': raw_response,
                'signed_xml': signed_xml,
                'track_id': track_id,
                'qr_url': qr_url,
                'security_code': security_code,
                'error_message': False,
                'state': 'accepted',
                'api_status': 'accepted',
            })
            return self._show_result_notification('success', f"✅ Enviado exitosamente via {provider.name}")
        else:
            self.write({
                'api_response': resp_text,
                'api_response_raw': raw_response,
                'signed_xml': signed_xml,
                'track_id': track_id,
                'error_message': error_msg,
                'state': 'rejected',
                'api_status': 'rejected',
            })
            return self._show_result_notification('warning', f"⚠️ Error: {error_msg}")

    def _show_result_notification(self, notif_type, message):
        """Muestra notificación y recarga la vista para mostrar cambios"""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Resultado del Envío'),
                'message': message,
                'type': notif_type,  # 'success', 'warning', 'error', 'info'
                'sticky': notif_type == 'error',
                'next': {
                    'type': 'ir.actions.client',
                    'tag': 'soft_reload',
                }
            }
        }

    def _extract_response_data(self, resp_data):
        """
        Extrae trackId, qrUrl y codigoSeguridad de la respuesta de la API.
        Busca en diferentes estructuras posibles de la respuesta.
        """
        track_id = None
        qr_url = None
        security_code = None

        if not isinstance(resp_data, dict):
            return track_id, qr_url, security_code

        # Función recursiva para buscar claves en estructuras anidadas
        def find_value(data, keys):
            """Busca un valor en un dict usando múltiples nombres de clave posibles"""
            if not isinstance(data, dict):
                return None
            for key in keys:
                if key in data:
                    return data[key]
            # Buscar en subestructuras comunes
            for subkey in ['data', 'result', 'response', 'documento', 'ecf', 'ECF']:
                if subkey in data and isinstance(data[subkey], dict):
                    result = find_value(data[subkey], keys)
                    if result:
                        return result
            return None

        # Buscar TrackId
        track_id = find_value(resp_data, [
            'trackId', 'TrackId', 'track_id', 'TRACKID',
            'trackID', 'id_seguimiento', 'idSeguimiento',
            'internalTrackId', 'internal_track_id'
        ])

        # Buscar QR URL o datos base64
        qr_url = find_value(resp_data, [
            'qrUrl', 'qr_url', 'QrUrl', 'qrURL', 'QRURL',
            'urlQr', 'url_qr', 'qrCode', 'qr_code', 'codigoQr',
            'qr', 'QR', 'qrImage', 'qr_image', 'imagenQr'
        ])

        # Buscar Código de Seguridad
        security_code = find_value(resp_data, [
            'codigoSeguridad', 'securityCode', 'codigo_seguridad',
            'CodigoSeguridad', 'CODIGO_SEGURIDAD', 'security_code',
            'codigoVerificacion', 'codigo_verificacion'
        ])

        # Log detallado para depuración
        _logger.info(f"[EXTRACT DEBUG] Respuesta API completa: {json.dumps(resp_data, ensure_ascii=False)[:1500]}")
        _logger.info(f"[EXTRACT DEBUG] track_id extraído: {track_id}")
        _logger.info(f"[EXTRACT DEBUG] qr_url extraído: {qr_url[:100] if qr_url else 'None'}...")
        _logger.info(f"[EXTRACT DEBUG] security_code extraído: {security_code}")

        return track_id, qr_url, security_code

    def get_qr_image_data(self):
        """
        Genera o retorna la imagen del QR para el reporte.
        Busca la URL de validación DGII del log de API asociado.
        Retorna una URL de datos base64 para usar en <img src="">.
        """
        self.ensure_one()

        _logger.info(f"[QR DEBUG] Caso ID={self.id}, track_id={self.track_id}, qr_url={self.qr_url[:100] if self.qr_url else 'None'}...")

        # Primero buscar en el log de API si no tenemos qr_url
        qr_value = self.qr_url
        if not qr_value:
            # Buscar el log más reciente con URL de validación
            api_log = self.env['ecf.api.log'].search([
                ('test_case_id', '=', self.id),
                ('dgii_validation_url', '!=', False)
            ], order='create_date desc', limit=1)

            if api_log and api_log.dgii_validation_url:
                qr_value = api_log.dgii_validation_url
                _logger.info(f"[QR DEBUG] URL obtenida del log de API: {qr_value[:80]}...")
                # Guardar para futuras consultas
                self.write({'qr_url': qr_value})

        # Si ya tenemos URL del QR, usarla
        if qr_value:
            qr_value = qr_value.strip()
            _logger.info(f"[QR DEBUG] qr_url encontrado, longitud={len(qr_value)}, primeros 50 chars: {qr_value[:50]}")

            # Si ya es data URI completa (imagen base64)
            if qr_value.startswith('data:'):
                _logger.info("[QR DEBUG] QR es data URI completa (imagen base64), retornando directo")
                return qr_value

            # Si parece ser base64 puro (sin prefijo data:) - es una IMAGEN
            # Base64 de imagen PNG/JPG típicamente es muy largo (>500 chars) y solo tiene A-Z, a-z, 0-9, +, /, =
            import re
            if len(qr_value) > 500 and re.match(r'^[A-Za-z0-9+/=]+$', qr_value):
                _logger.info("[QR DEBUG] QR parece ser imagen base64 pura, agregando prefijo data:image/png;base64,")
                return f"data:image/png;base64,{qr_value}"

            # Si es una URL (http/https) o cualquier otro texto, es el CONTENIDO del QR
            # Debemos GENERAR una imagen QR con este contenido
            _logger.info(f"[QR DEBUG] qr_url es contenido para QR (URL o texto), generando imagen QR...")
            try:
                import qrcode
                import io
                import base64

                qr = qrcode.QRCode(
                    version=1,
                    error_correction=qrcode.constants.ERROR_CORRECT_M,
                    box_size=10,
                    border=2,
                )
                qr.add_data(qr_value)
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")
                buffer = io.BytesIO()
                img.save(buffer, format='PNG')
                buffer.seek(0)
                img_base64 = base64.b64encode(buffer.read()).decode('utf-8')
                _logger.info(f"[QR DEBUG] Imagen QR generada exitosamente con contenido: {qr_value[:50]}...")
                return f"data:image/png;base64,{img_base64}"
            except ImportError as e:
                _logger.error(f"[QR DEBUG] Módulo qrcode no instalado: {str(e)}")
                return False
            except Exception as e:
                _logger.error(f"[QR DEBUG] Error generando QR desde qr_url: {str(e)}")
                return False

        # Si no hay QR pero tenemos trackId, generar QR localmente
        if self.track_id:
            _logger.info(f"[QR DEBUG] No hay qr_url, generando QR desde track_id: {self.track_id}")
            try:
                import qrcode
                import io
                import base64

                # Crear URL de verificación DGII
                verification_url = f"https://ecf.dgii.gov.do/consultas/ecf/{self.track_id}"
                _logger.info(f"[QR DEBUG] URL de verificación: {verification_url}")

                # Generar QR
                qr = qrcode.QRCode(
                    version=1,
                    error_correction=qrcode.constants.ERROR_CORRECT_M,
                    box_size=10,
                    border=2,
                )
                qr.add_data(verification_url)
                qr.make(fit=True)

                # Crear imagen
                img = qr.make_image(fill_color="black", back_color="white")

                # Convertir a base64
                buffer = io.BytesIO()
                img.save(buffer, format='PNG')
                buffer.seek(0)
                img_base64 = base64.b64encode(buffer.read()).decode('utf-8')

                _logger.info(f"[QR DEBUG] QR generado exitosamente, longitud base64: {len(img_base64)}")
                return f"data:image/png;base64,{img_base64}"

            except ImportError as e:
                _logger.warning(f"[QR DEBUG] Módulo qrcode no instalado: {str(e)}")
                return False
            except Exception as e:
                _logger.error(f"[QR DEBUG] Error generando QR: {str(e)}")
                return False

        _logger.info("[QR DEBUG] No hay qr_url ni track_id, retornando False")
        return False

    def action_use_as_template(self):
        """Abre wizard para generar casos de volumen usando este caso como plantilla"""
        self.ensure_one()

        if not self.payload_json:
            raise UserError(_("Este caso no tiene JSON generado. Primero genere el JSON."))

        return {
            'type': 'ir.actions.act_window',
            'name': 'Generar Casos de Volumen',
            'res_model': 'generate.volume.test.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_test_set_id': self.test_set_id.id,
                'default_template_case_id': self.id,
            },
        }

    # ========================================================================
    # Reporte PDF - Factura DGII
    # ========================================================================

    def get_ecf_data(self):
        """Obtiene los datos del e-CF parseados del JSON para el reporte"""
        self.ensure_one()
        if not self.payload_json:
            return {}

        try:
            data = json.loads(self.payload_json)
            ecf = data.get('ECF', {})
            encabezado = ecf.get('Encabezado', {})
            return {
                'ecf': ecf,
                'id_doc': encabezado.get('IdDoc', {}),
                'emisor': encabezado.get('Emisor', {}),
                'comprador': encabezado.get('Comprador', {}),
                'totales': encabezado.get('Totales', {}),
                'items': ecf.get('DetallesItems', {}).get('Item', []),
                'fecha_hora_firma': ecf.get('FechaHoraFirma', ''),
            }
        except Exception:
            return {}

    def get_tipo_ecf_name(self):
        """Retorna el nombre completo del tipo de e-CF"""
        tipos = {
            '31': 'Factura de Crédito Fiscal Electrónica',
            '32': 'Factura de Consumo Electrónica',
            '33': 'Nota de Débito Electrónica',
            '34': 'Nota de Crédito Electrónica',
            '41': 'Comprobante de Regímenes Especiales Electrónico',
            '43': 'Comprobante de Exportaciones Electrónico',
            '44': 'Comprobante de Compras Electrónico',
            '45': 'Comprobante de Gastos Menores Electrónico',
            '46': 'Comprobante de Pagos al Exterior Electrónico',
            '47': 'Comprobante para Gubernamental Electrónico',
        }
        return tipos.get(self.tipo_ecf, 'Comprobante Fiscal Electrónico')

    def get_qr_dgii_url(self):
        """
        Retorna la URL del QR para el reporte.
        Busca la URL de validación DGII del log de API si no está en el caso.
        La URL se codifica para usarse en /report/barcode/QR/
        """
        from urllib.parse import quote

        self.ensure_one()

        _logger.info(f"[QR DGII URL] Caso ID={self.id}, qr_url={self.qr_url[:100] if self.qr_url else 'None'}...")

        qr_url = self.qr_url

        # Si no hay qr_url, buscar en el log de API
        if not qr_url:
            api_log = self.env['ecf.api.log'].search([
                ('test_case_id', '=', self.id),
                ('dgii_validation_url', '!=', False)
            ], order='create_date desc', limit=1)

            if api_log and api_log.dgii_validation_url:
                qr_url = api_log.dgii_validation_url
                _logger.info(f"[QR DGII URL] URL obtenida del log: {qr_url[:80]}...")
                # Guardar para futuras consultas
                self.write({'qr_url': qr_url})

        if qr_url:
            encoded = quote(qr_url, safe='')
            _logger.info(f"[QR DGII URL] URL codificada (primeros 100): {encoded[:100]}...")
            return encoded

        _logger.info("[QR DGII URL] No hay qr_url ni en caso ni en log, retornando vacío")
        return ''

    def action_print_invoice(self):
        """Imprime el reporte de factura DGII"""
        self.ensure_one()
        if not self.payload_json:
            raise UserError(_("No hay JSON para generar la factura."))
        return self.env.ref('l10n_do_e_cf_tests.action_report_ecf_invoice').report_action(self)
