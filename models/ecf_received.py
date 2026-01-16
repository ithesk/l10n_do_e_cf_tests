"""
Modelo para almacenar e-CF Recibidos (Comprobantes Fiscales de Proveedores).

Este modelo guarda los comprobantes fiscales electrónicos que recibimos de proveedores
a través de la DGII, con toda la información del documento para:
- Gestión de facturas de proveedores
- Trazabilidad fiscal
- Aprobación/Rechazo comercial
- Integración con contabilidad
"""
import json
import logging
import base64
from datetime import datetime

from lxml import etree
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class EcfReceived(models.Model):
    """Comprobante Fiscal Electrónico Recibido (e-CF de Proveedor)."""

    _name = "ecf.received"
    _description = "e-CF Recibido"
    _order = "fecha_recepcion desc, id desc"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    # =========================================================================
    # Identificación
    # =========================================================================
    name = fields.Char(
        string="Nombre",
        compute="_compute_name",
        store=True,
        index=True
    )

    # =========================================================================
    # Datos del Documento (IdDoc)
    # =========================================================================
    tipo_ecf = fields.Selection([
        ('31', 'Factura de Crédito Fiscal'),
        ('32', 'Factura de Consumo'),
        ('33', 'Nota de Débito'),
        ('34', 'Nota de Crédito'),
        ('41', 'Compras'),
        ('43', 'Gastos Menores'),
        ('44', 'Regímenes Especiales'),
        ('45', 'Gubernamental'),
        ('46', 'Exportación'),
        ('47', 'Pagos al Exterior'),
    ], string="Tipo e-CF", required=True, index=True, tracking=True)

    encf = fields.Char(
        string="e-NCF",
        required=True,
        index=True,
        tracking=True,
        help="Número de Comprobante Fiscal Electrónico"
    )

    fecha_vencimiento_secuencia = fields.Date(
        string="Venc. Secuencia",
        help="Fecha de vencimiento de la secuencia del e-NCF"
    )

    indicador_monto_gravado = fields.Selection([
        ('0', 'No aplica'),
        ('1', 'Aplica'),
    ], string="Ind. Monto Gravado", default='0')

    tipo_ingresos = fields.Selection([
        ('01', 'Ingresos por operaciones (No financieros)'),
        ('02', 'Ingresos Financieros'),
        ('03', 'Ingresos Extraordinarios'),
        ('04', 'Ingresos por Arrendamientos'),
        ('05', 'Ingresos por Venta de Activo Depreciable'),
        ('06', 'Otros Ingresos'),
    ], string="Tipo Ingresos", default='01')

    tipo_pago = fields.Selection([
        ('1', 'Contado'),
        ('2', 'Crédito'),
        ('3', 'Gratuito'),
    ], string="Tipo Pago", default='1')

    # =========================================================================
    # Datos del Emisor (Proveedor)
    # =========================================================================
    rnc_emisor = fields.Char(
        string="RNC Emisor",
        required=True,
        index=True,
        tracking=True,
        help="RNC o Cédula del emisor (proveedor)"
    )

    razon_social_emisor = fields.Char(
        string="Razón Social Emisor",
        help="Nombre o razón social del emisor"
    )

    nombre_comercial_emisor = fields.Char(
        string="Nombre Comercial",
        help="Nombre comercial del emisor"
    )

    direccion_emisor = fields.Text(string="Dirección Emisor")
    municipio_emisor = fields.Char(string="Municipio Emisor")
    provincia_emisor = fields.Char(string="Provincia Emisor")
    telefono_emisor = fields.Char(string="Teléfono Emisor")
    correo_emisor = fields.Char(string="Correo Emisor")
    website_emisor = fields.Char(string="Sitio Web Emisor")

    fecha_emision = fields.Date(
        string="Fecha Emisión",
        required=True,
        index=True,
        tracking=True
    )

    numero_factura_interna = fields.Char(
        string="# Factura Interna",
        help="Número de factura interna del emisor"
    )

    # =========================================================================
    # Datos del Comprador (Nosotros)
    # =========================================================================
    rnc_comprador = fields.Char(
        string="RNC Comprador",
        required=True,
        index=True,
        help="RNC del comprador (nuestra empresa)"
    )

    razon_social_comprador = fields.Char(
        string="Razón Social Comprador"
    )

    contacto_comprador = fields.Char(string="Contacto Comprador")
    correo_comprador = fields.Char(string="Correo Comprador")
    direccion_comprador = fields.Text(string="Dirección Comprador")

    # =========================================================================
    # Totales
    # =========================================================================
    monto_gravado_total = fields.Float(
        string="Monto Gravado Total",
        digits=(16, 2)
    )

    monto_gravado_i1 = fields.Float(
        string="Monto Gravado I1 (18%)",
        digits=(16, 2)
    )

    monto_gravado_i2 = fields.Float(
        string="Monto Gravado I2 (16%)",
        digits=(16, 2)
    )

    monto_gravado_i3 = fields.Float(
        string="Monto Gravado I3 (0%)",
        digits=(16, 2)
    )

    total_itbis = fields.Float(
        string="Total ITBIS",
        digits=(16, 2),
        tracking=True
    )

    total_itbis1 = fields.Float(
        string="Total ITBIS 18%",
        digits=(16, 2)
    )

    total_itbis2 = fields.Float(
        string="Total ITBIS 16%",
        digits=(16, 2)
    )

    monto_total = fields.Float(
        string="Monto Total",
        digits=(16, 2),
        required=True,
        tracking=True
    )

    monto_exento = fields.Float(
        string="Monto Exento",
        digits=(16, 2)
    )

    # =========================================================================
    # Firma Digital
    # =========================================================================
    fecha_hora_firma = fields.Datetime(
        string="Fecha/Hora Firma",
        help="Fecha y hora de la firma digital"
    )

    codigo_seguridad = fields.Char(
        string="Código Seguridad",
        size=6,
        help="Primeros 6 caracteres del SignatureValue"
    )

    signature_value = fields.Text(
        string="Signature Value",
        help="Valor de la firma digital (Base64)"
    )

    certificado = fields.Text(
        string="Certificado X509",
        help="Certificado digital usado para firmar"
    )

    # =========================================================================
    # XMLs
    # =========================================================================
    xml_original = fields.Text(
        string="XML Original",
        help="XML del e-CF tal como fue recibido de DGII"
    )

    xml_arecf = fields.Text(
        string="XML ARECF",
        help="XML del Acuse de Recibo firmado"
    )

    # =========================================================================
    # Estado y Procesamiento
    # =========================================================================
    state = fields.Selection([
        ('received', 'Recibido'),
        ('accepted', 'Aceptado'),
        ('rejected', 'Rechazado'),
        ('pending_approval', 'Pendiente Aprobación'),
        ('approved', 'Aprobado Comercialmente'),
        ('disputed', 'En Disputa'),
    ], string="Estado", default='received', required=True, index=True, tracking=True)

    arecf_status = fields.Selection([
        ('0', 'Aceptado'),
        ('1', 'Rechazado - Error especificación'),
        ('2', 'Rechazado - Error firma digital'),
        ('3', 'Rechazado - Envío duplicado'),
        ('4', 'Rechazado - RNC no corresponde'),
    ], string="Estado ARECF", help="Estado del Acuse de Recibo enviado a DGII")

    fecha_recepcion = fields.Datetime(
        string="Fecha Recepción",
        default=fields.Datetime.now,
        required=True,
        index=True
    )

    fecha_arecf = fields.Datetime(
        string="Fecha ARECF",
        help="Fecha en que se envió el Acuse de Recibo"
    )

    # =========================================================================
    # Líneas de Detalle
    # =========================================================================
    line_ids = fields.One2many(
        'ecf.received.line',
        'ecf_received_id',
        string="Líneas de Detalle"
    )

    # =========================================================================
    # Relaciones
    # =========================================================================
    callback_request_id = fields.Many2one(
        'dgii.callback.request',
        string="Callback Request",
        ondelete='set null',
        help="Request de callback que originó este documento"
    )

    api_log_id = fields.Many2one(
        'ecf.api.log',
        string="Log API",
        ondelete='set null',
        help="Log de la transacción con el microservicio"
    )

    partner_id = fields.Many2one(
        'res.partner',
        string="Proveedor",
        compute="_compute_partner_id",
        store=True,
        help="Proveedor relacionado (por RNC)"
    )

    company_id = fields.Many2one(
        'res.company',
        string="Compañía",
        default=lambda self: self.env.company,
        required=True,
        index=True
    )

    # =========================================================================
    # Campos Computados
    # =========================================================================
    line_count = fields.Integer(
        string="# Líneas",
        compute="_compute_line_count"
    )

    @api.depends('tipo_ecf', 'encf', 'rnc_emisor', 'fecha_emision')
    def _compute_name(self):
        tipo_labels = {
            '31': 'FCF',
            '32': 'FC',
            '33': 'ND',
            '34': 'NC',
            '41': 'COM',
            '43': 'GM',
            '44': 'RE',
            '45': 'GUB',
            '46': 'EXP',
            '47': 'PE',
        }
        for rec in self:
            parts = []
            if rec.tipo_ecf:
                parts.append(tipo_labels.get(rec.tipo_ecf, rec.tipo_ecf))
            if rec.encf:
                parts.append(rec.encf)
            if rec.rnc_emisor:
                parts.append(rec.rnc_emisor)
            rec.name = " - ".join(parts) if parts else f"ECF-{rec.id}"

    @api.depends('rnc_emisor')
    def _compute_partner_id(self):
        for rec in self:
            if rec.rnc_emisor:
                partner = self.env['res.partner'].search([
                    '|',
                    ('vat', '=', rec.rnc_emisor),
                    ('vat', '=', f'DO{rec.rnc_emisor}'),
                ], limit=1)
                rec.partner_id = partner.id if partner else False
            else:
                rec.partner_id = False

    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    # =========================================================================
    # Métodos de Creación desde XML
    # =========================================================================

    @api.model
    def create_from_xml(self, xml_string, callback_request_id=None, api_log_id=None):
        """
        Crea un registro de e-CF recibido a partir del XML.

        Args:
            xml_string: XML del e-CF como string
            callback_request_id: ID del dgii.callback.request (opcional)
            api_log_id: ID del ecf.api.log (opcional)

        Returns:
            ecf.received: Registro creado
        """
        try:
            # Parsear XML
            if isinstance(xml_string, str):
                xml_bytes = xml_string.encode('utf-8')
            else:
                xml_bytes = xml_string

            root = etree.fromstring(xml_bytes)

            # Extraer datos
            vals = self._extract_ecf_data(root, xml_string)

            # Agregar relaciones
            if callback_request_id:
                vals['callback_request_id'] = callback_request_id
            if api_log_id:
                vals['api_log_id'] = api_log_id

            vals['xml_original'] = xml_string

            # Verificar si ya existe (por e-NCF)
            existing = self.search([('encf', '=', vals.get('encf'))], limit=1)
            if existing:
                _logger.info("[ECF Received] Documento ya existe: %s", vals.get('encf'))
                # Actualizar con nuevos datos si es necesario
                existing.write({
                    'xml_original': xml_string,
                    'callback_request_id': callback_request_id,
                    'api_log_id': api_log_id,
                })
                return existing

            # Crear registro
            record = self.create(vals)

            # Crear líneas de detalle
            lines_data = self._extract_lines_data(root)
            for line_vals in lines_data:
                line_vals['ecf_received_id'] = record.id
                self.env['ecf.received.line'].create(line_vals)

            _logger.info(
                "[ECF Received] Documento creado: ID=%s, e-NCF=%s, RNC Emisor=%s",
                record.id, record.encf, record.rnc_emisor
            )

            return record

        except etree.XMLSyntaxError as e:
            _logger.error("[ECF Received] Error parseando XML: %s", e)
            raise UserError(_("Error parseando XML: %s") % str(e))
        except Exception as e:
            _logger.exception("[ECF Received] Error creando documento")
            raise UserError(_("Error creando documento: %s") % str(e))

    def _extract_ecf_data(self, root, xml_string):
        """Extrae datos del XML del e-CF."""
        def find_text(tag_names, default=''):
            """Busca el texto de un tag por múltiples nombres."""
            for tag in tag_names if isinstance(tag_names, list) else [tag_names]:
                for el in root.iter():
                    local_name = el.tag.split('}')[-1] if '}' in el.tag else el.tag
                    if local_name == tag and el.text:
                        return el.text.strip()
            return default

        def parse_date(date_str):
            """Convierte fecha DD-MM-YYYY o YYYY-MM-DD a date."""
            if not date_str:
                return False
            try:
                date_str = date_str[:10]
                if '-' in date_str:
                    parts = date_str.split('-')
                    if len(parts) == 3:
                        if len(parts[0]) == 4:
                            return date_str
                        elif len(parts[0]) == 2:
                            return f"{parts[2]}-{parts[1]}-{parts[0]}"
            except Exception:
                pass
            return False

        def parse_datetime(dt_str):
            """Convierte fecha/hora DD-MM-YYYY HH:MM:SS a datetime."""
            if not dt_str:
                return False
            try:
                # Formato: DD-MM-YYYY HH:MM:SS
                if ' ' in dt_str:
                    date_part, time_part = dt_str.split(' ', 1)
                    date_parts = date_part.split('-')
                    if len(date_parts) == 3 and len(date_parts[0]) == 2:
                        # DD-MM-YYYY
                        iso_date = f"{date_parts[2]}-{date_parts[1]}-{date_parts[0]}"
                        return f"{iso_date} {time_part}"
                return dt_str
            except Exception:
                pass
            return False

        def parse_float(value):
            """Convierte string a float."""
            if not value:
                return 0.0
            try:
                return float(value.replace(',', ''))
            except Exception:
                return 0.0

        # Extraer código de seguridad del SignatureValue
        signature_value = find_text(['SignatureValue'])
        codigo_seguridad = signature_value[:6] if signature_value else ''

        vals = {
            # IdDoc
            'tipo_ecf': find_text(['TipoeCF']),
            'encf': find_text(['eNCF', 'ENCF']),
            'fecha_vencimiento_secuencia': parse_date(find_text(['FechaVencimientoSecuencia'])),
            'indicador_monto_gravado': find_text(['IndicadorMontoGravado'], '0'),
            'tipo_ingresos': find_text(['TipoIngresos'], '01'),
            'tipo_pago': find_text(['TipoPago'], '1'),

            # Emisor
            'rnc_emisor': find_text(['RNCEmisor']),
            'razon_social_emisor': find_text(['RazonSocialEmisor']),
            'nombre_comercial_emisor': find_text(['NombreComercial']),
            'direccion_emisor': find_text(['DireccionEmisor']),
            'municipio_emisor': find_text(['Municipio']),
            'provincia_emisor': find_text(['Provincia']),
            'telefono_emisor': find_text(['TelefonoEmisor']),
            'correo_emisor': find_text(['CorreoEmisor']),
            'website_emisor': find_text(['WebSite']),
            'fecha_emision': parse_date(find_text(['FechaEmision'])),
            'numero_factura_interna': find_text(['NumeroFacturaInterna']),

            # Comprador
            'rnc_comprador': find_text(['RNCComprador']),
            'razon_social_comprador': find_text(['RazonSocialComprador']),
            'contacto_comprador': find_text(['ContactoComprador']),
            'correo_comprador': find_text(['CorreoComprador']),
            'direccion_comprador': find_text(['DireccionComprador']),

            # Totales
            'monto_gravado_total': parse_float(find_text(['MontoGravadoTotal'])),
            'monto_gravado_i1': parse_float(find_text(['MontoGravadoI1'])),
            'monto_gravado_i2': parse_float(find_text(['MontoGravadoI2'])),
            'monto_gravado_i3': parse_float(find_text(['MontoGravadoI3'])),
            'total_itbis': parse_float(find_text(['TotalITBIS'])),
            'total_itbis1': parse_float(find_text(['TotalITBIS1'])),
            'total_itbis2': parse_float(find_text(['TotalITBIS2'])),
            'monto_total': parse_float(find_text(['MontoTotal'])),
            'monto_exento': parse_float(find_text(['MontoExento'])),

            # Firma
            'fecha_hora_firma': parse_datetime(find_text(['FechaHoraFirma'])),
            'codigo_seguridad': codigo_seguridad,
            'signature_value': signature_value,
            'certificado': find_text(['X509Certificate']),

            # Estado inicial
            'state': 'received',
            'fecha_recepcion': fields.Datetime.now(),
        }

        return vals

    def _extract_lines_data(self, root):
        """Extrae las líneas de detalle del XML."""
        lines = []

        def parse_float(value):
            if not value:
                return 0.0
            try:
                return float(value.replace(',', ''))
            except Exception:
                return 0.0

        # Buscar items
        for item in root.iter():
            local_name = item.tag.split('}')[-1] if '}' in item.tag else item.tag
            if local_name == 'Item':
                line = {
                    'numero_linea': 0,
                    'nombre_item': '',
                    'cantidad': 0.0,
                    'precio_unitario': 0.0,
                    'monto': 0.0,
                }

                for child in item:
                    child_name = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                    text = (child.text or '').strip()

                    if child_name == 'NumeroLinea':
                        line['numero_linea'] = int(text) if text else 0
                    elif child_name == 'NombreItem':
                        line['nombre_item'] = text
                    elif child_name == 'IndicadorFacturacion':
                        line['indicador_facturacion'] = text
                    elif child_name == 'IndicadorBienoServicio':
                        line['indicador_bien_servicio'] = text
                    elif child_name == 'CantidadItem':
                        line['cantidad'] = parse_float(text)
                    elif child_name == 'UnidadMedida':
                        line['unidad_medida'] = text
                    elif child_name == 'PrecioUnitarioItem':
                        line['precio_unitario'] = parse_float(text)
                    elif child_name == 'MontoItem':
                        line['monto'] = parse_float(text)
                    elif child_name == 'DescuentoMonto':
                        line['descuento_monto'] = parse_float(text)

                if line['nombre_item']:
                    lines.append(line)

        return lines

    # =========================================================================
    # Actualización desde respuesta API
    # =========================================================================

    def update_from_api_response(self, response_data):
        """
        Actualiza el registro con la respuesta del microservicio.

        Args:
            response_data: dict con los datos de respuesta
                - arecfXmlSigned: XML del ARECF firmado
                - ecfInfo: dict con información del e-CF
                - arecfStatus: Estado del ARECF ("0" = Aceptado)
        """
        self.ensure_one()

        vals = {}

        # XML del ARECF firmado
        if response_data.get('arecfXmlSigned'):
            vals['xml_arecf'] = response_data['arecfXmlSigned']
            vals['fecha_arecf'] = fields.Datetime.now()

        # Estado del ARECF
        arecf_status = response_data.get('arecfStatus')
        if arecf_status is not None:
            vals['arecf_status'] = str(arecf_status)
            if str(arecf_status) == '0':
                vals['state'] = 'accepted'
            else:
                vals['state'] = 'rejected'

        # Información adicional del e-CF
        ecf_info = response_data.get('ecfInfo', {})
        if ecf_info:
            # Actualizar campos si vienen en ecfInfo
            if ecf_info.get('montoTotal'):
                try:
                    vals['monto_total'] = float(ecf_info['montoTotal'])
                except Exception:
                    pass
            if ecf_info.get('totalITBIS'):
                try:
                    vals['total_itbis'] = float(ecf_info['totalITBIS'])
                except Exception:
                    pass

        if vals:
            self.write(vals)
            _logger.info(
                "[ECF Received] Documento actualizado desde API: ID=%s, e-NCF=%s, estado=%s",
                self.id, self.encf, vals.get('state', self.state)
            )

    # =========================================================================
    # Acciones
    # =========================================================================

    def action_view_xml(self):
        """Abre una vista del XML original."""
        self.ensure_one()
        if not self.xml_original:
            raise UserError(_("No hay XML disponible."))

        return {
            'type': 'ir.actions.act_window',
            'name': f'XML - {self.encf}',
            'res_model': 'ecf.received',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': {'show_xml': True},
        }

    def action_download_xml(self):
        """Descarga el XML original."""
        self.ensure_one()
        if not self.xml_original:
            raise UserError(_("No hay XML disponible."))

        filename = f"{self.encf or 'ecf'}_{self.id}.xml"
        content = self.xml_original.encode('utf-8')
        b64_content = base64.b64encode(content).decode('utf-8')

        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': b64_content,
            'mimetype': 'application/xml',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'new',
        }

    def action_download_arecf(self):
        """Descarga el XML del ARECF."""
        self.ensure_one()
        if not self.xml_arecf:
            raise UserError(_("No hay ARECF disponible."))

        filename = f"ARECF_{self.encf or 'ecf'}_{self.id}.xml"
        content = self.xml_arecf.encode('utf-8')
        b64_content = base64.b64encode(content).decode('utf-8')

        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': b64_content,
            'mimetype': 'application/xml',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'new',
        }

    def action_approve(self):
        """Aprueba comercialmente el documento."""
        self.ensure_one()
        if self.state not in ['received', 'accepted', 'pending_approval']:
            raise UserError(_("Solo se pueden aprobar documentos recibidos o aceptados."))

        self.write({'state': 'approved'})
        return True

    def action_reject(self):
        """Rechaza comercialmente el documento."""
        self.ensure_one()
        if self.state not in ['received', 'accepted', 'pending_approval']:
            raise UserError(_("Solo se pueden rechazar documentos recibidos o aceptados."))

        self.write({'state': 'disputed'})
        return True


class EcfReceivedLine(models.Model):
    """Línea de detalle de e-CF Recibido."""

    _name = "ecf.received.line"
    _description = "Línea de e-CF Recibido"
    _order = "numero_linea"

    ecf_received_id = fields.Many2one(
        'ecf.received',
        string="e-CF Recibido",
        required=True,
        ondelete='cascade',
        index=True
    )

    numero_linea = fields.Integer(string="# Línea", default=1)

    nombre_item = fields.Char(string="Descripción", required=True)

    indicador_facturacion = fields.Selection([
        ('1', 'Gravado 18%'),
        ('2', 'Gravado 16%'),
        ('3', 'Exento'),
        ('4', 'Gravado 0%'),
        ('5', 'No Facturable'),
    ], string="Ind. Facturación", default='1')

    indicador_bien_servicio = fields.Selection([
        ('1', 'Bien'),
        ('2', 'Servicio'),
    ], string="Bien/Servicio", default='1')

    cantidad = fields.Float(string="Cantidad", digits=(16, 2), default=1.0)

    unidad_medida = fields.Char(string="Unidad Medida")

    precio_unitario = fields.Float(
        string="Precio Unitario",
        digits=(16, 4)
    )

    descuento_monto = fields.Float(
        string="Descuento",
        digits=(16, 2),
        default=0.0
    )

    monto = fields.Float(
        string="Monto",
        digits=(16, 2)
    )

    subtotal = fields.Float(
        string="Subtotal",
        compute="_compute_subtotal",
        digits=(16, 2)
    )

    @api.depends('cantidad', 'precio_unitario', 'descuento_monto')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = (line.cantidad * line.precio_unitario) - line.descuento_monto
