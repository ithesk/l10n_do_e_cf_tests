import logging
from lxml import etree
import os
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ECfConsumoResumen(models.Model):
    _name = "e.cf.consumo.resumen"
    _description = "Resumen de Facturas de Consumo < RD$250,000 (RFCE)"
    _order = "create_date desc"

    name = fields.Char(string="Nombre", required=True)
    company_id = fields.Many2one('res.company', string='Compañía', required=True, default=lambda self: self.env.company)

    # Período
    fecha_desde = fields.Date(string="Fecha Desde", required=True)
    fecha_hasta = fields.Date(string="Fecha Hasta", required=True)
    periodo = fields.Char(string="Período (YYYYMM)", compute="_compute_periodo", store=True)

    # Facturas incluidas
    invoice_ids = fields.Many2many(
        'account.move',
        'e_cf_resumen_invoice_rel',
        'resumen_id',
        'invoice_id',
        string="Facturas B02 < 250k",
        domain="[('move_type', '=', 'out_invoice'), ('state', '=', 'posted')]"
    )

    cantidad_comprobantes = fields.Integer(string="Cantidad de Comprobantes", compute="_compute_totals", store=True)

    # Totales calculados
    monto_gravado = fields.Float(string="Monto Gravado Total", digits=(16, 2), compute="_compute_totals", store=True)
    total_itbis = fields.Float(string="Total ITBIS", digits=(16, 2), compute="_compute_totals", store=True)
    monto_exento = fields.Float(string="Monto Exento", digits=(16, 2), compute="_compute_totals", store=True)
    monto_total = fields.Float(string="Monto Total", digits=(16, 2), compute="_compute_totals", store=True)

    # XML y envío
    xml_payload = fields.Text(string="XML RFCE")
    xml_file = fields.Binary(string="Archivo XML", attachment=True)
    xml_filename = fields.Char(string="Nombre Archivo XML")

    # Estado
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('generated', 'XML Generado'),
        ('sent', 'Enviado a DGII'),
        ('accepted', 'Aceptado'),
        ('rejected', 'Rechazado'),
        ('error', 'Error'),
    ], string="Estado", default='draft')

    track_id = fields.Char(string="TrackID DGII")
    dgii_response = fields.Text(string="Respuesta DGII")
    error_message = fields.Text(string="Mensaje de Error")

    @api.depends('fecha_desde')
    def _compute_periodo(self):
        for record in self:
            if record.fecha_desde:
                record.periodo = record.fecha_desde.strftime('%Y%m')
            else:
                record.periodo = False

    @api.depends('invoice_ids', 'invoice_ids.amount_total', 'invoice_ids.amount_tax')
    def _compute_totals(self):
        for record in self:
            invoices = record.invoice_ids.filtered(lambda inv: inv.state == 'posted')
            record.cantidad_comprobantes = len(invoices)
            record.monto_total = sum(invoices.mapped('amount_total'))
            record.total_itbis = sum(invoices.mapped('amount_tax'))
            record.monto_gravado = record.monto_total - record.total_itbis
            # Por ahora asumimos que no hay exentos, se puede calcular más adelante
            record.monto_exento = 0.0

    def action_generate_xml(self):
        """Genera el XML RFCE según el esquema DGII"""
        self.ensure_one()

        if not self.invoice_ids:
            raise UserError(_("Debe agregar al menos una factura al resumen."))

        if not self.company_id.vat:
            raise UserError(_("La compañía debe tener RNC configurado."))

        # Generar XML
        xml_string = self._build_rfce_xml()

        # Firmar XML si está configurado
        xml_string = self._sign_rfce_xml(xml_string)

        # Guardar XML
        self.write({
            'xml_payload': xml_string,
            'xml_file': xml_string.encode('utf-8'),
            'xml_filename': f'RFCE_{self.company_id.vat}_{self.periodo}.xml',
            'state': 'generated'
        })

        _logger.info(f"XML RFCE generado para resumen {self.name}")

        return True

    def _build_rfce_xml(self):
        """Construye el XML del Resumen de Facturas de Consumo"""
        # Namespace
        ns = "http://dgii.gov.do/ecf/resumen/v1.0"

        # Crear elemento raíz
        root = etree.Element("{%s}RFCE" % ns, nsmap={
            None: ns,
            'xsi': "http://www.w3.org/2001/XMLSchema-instance"
        })

        # Encabezado
        encabezado = etree.SubElement(root, "Encabezado")
        etree.SubElement(encabezado, "Version").text = "1.0"
        etree.SubElement(encabezado, "RNCEmisor").text = self.company_id.vat or ''
        etree.SubElement(encabezado, "Periodo").text = self.periodo or ''
        etree.SubElement(encabezado, "FechaDesde").text = self.fecha_desde.strftime('%Y-%m-%d') if self.fecha_desde else ''
        etree.SubElement(encabezado, "FechaHasta").text = self.fecha_hasta.strftime('%Y-%m-%d') if self.fecha_hasta else ''
        etree.SubElement(encabezado, "CantidadComprobantes").text = str(self.cantidad_comprobantes)

        # Totales
        totales = etree.SubElement(root, "Totales")
        etree.SubElement(totales, "MontoGravadoTotal").text = f"{self.monto_gravado:.2f}"
        etree.SubElement(totales, "TotalITBIS").text = f"{self.total_itbis:.2f}"
        etree.SubElement(totales, "MontoExento").text = f"{self.monto_exento:.2f}"
        etree.SubElement(totales, "MontoTotal").text = f"{self.monto_total:.2f}"

        # Detalles (opcional - según especificación DGII)
        # Por ahora solo incluimos el resumen, no el detalle de cada factura

        xml_string = etree.tostring(
            root,
            encoding='UTF-8',
            xml_declaration=True,
            pretty_print=True
        ).decode('utf-8')

        return xml_string

    def _sign_rfce_xml(self, xml_string):
        """Firma el XML RFCE con el certificado digital"""
        # Usar el mismo método de firma que e.cf.document
        try:
            ecf_doc_obj = self.env['e.cf.document']
            if hasattr(ecf_doc_obj, '_sign_xml'):
                # Crear un registro temporal para usar el método de firma
                temp_doc = ecf_doc_obj.new({})
                return temp_doc._sign_xml(xml_string)
            else:
                _logger.warning("Método de firma no disponible para RFCE")
                return xml_string
        except Exception as e:
            _logger.error(f"Error al firmar XML RFCE: {e}")
            return xml_string

    def action_send_to_dgii(self):
        """Envía el resumen RFCE a DGII"""
        self.ensure_one()

        if not self.xml_payload:
            raise UserError(_("Debe generar el XML primero."))

        if self.state not in ('generated', 'error'):
            raise UserError(_("El resumen ya fue enviado o está en proceso."))

        # Obtener servicio DGII
        dgii_client = self.env['e.cf.config'].get_dgii_client()

        try:
            # Enviar RFCE
            response = dgii_client.send_rfce(self.xml_payload)

            if response.get('success'):
                self.write({
                    'state': 'sent',
                    'track_id': response.get('track_id'),
                    'dgii_response': str(response)
                })
                _logger.info(f"RFCE enviado exitosamente. TrackID: {response.get('track_id')}")
            else:
                self.write({
                    'state': 'error',
                    'error_message': response.get('error', 'Error desconocido'),
                    'dgii_response': str(response)
                })
                raise UserError(_("Error al enviar RFCE: %s") % response.get('error'))

        except Exception as e:
            _logger.error(f"Error al enviar RFCE a DGII: {e}")
            self.write({
                'state': 'error',
                'error_message': str(e)
            })
            raise UserError(_("Error al enviar RFCE a DGII: %s") % str(e))

        return True

    def action_check_status(self):
        """Consulta el estado del resumen en DGII"""
        self.ensure_one()

        if not self.track_id:
            raise UserError(_("No hay TrackID para consultar."))

        dgii_client = self.env['e.cf.config'].get_dgii_client()

        try:
            response = dgii_client.check_status(self.track_id)

            status = response.get('estado', '').upper()

            if status == 'ACEPTADO':
                self.write({
                    'state': 'accepted',
                    'dgii_response': str(response)
                })
            elif status == 'RECHAZADO':
                self.write({
                    'state': 'rejected',
                    'dgii_response': str(response),
                    'error_message': response.get('mensaje', 'Rechazado por DGII')
                })
            else:
                self.write({
                    'dgii_response': str(response)
                })

            _logger.info(f"Estado RFCE consultado: {status}")

        except Exception as e:
            _logger.error(f"Error al consultar estado RFCE: {e}")
            raise UserError(_("Error al consultar estado: %s") % str(e))

        return True

    def action_export_xml_facturas(self):
        """Exporta los XML de las facturas individuales para carga manual en DGII"""
        self.ensure_one()

        if self.state != 'accepted':
            raise UserError(_("Solo puede exportar XML cuando el resumen esté ACEPTADO por DGII."))

        if not self.invoice_ids:
            raise UserError(_("No hay facturas para exportar."))

        # Generar ZIP con todos los XML
        import zipfile
        from io import BytesIO

        zip_buffer = BytesIO()

        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for invoice in self.invoice_ids:
                # Buscar el documento e-CF
                ecf_doc = self.env['e.cf.document'].search([
                    ('move_id', '=', invoice.id)
                ], limit=1)

                if ecf_doc and ecf_doc.xml_payload:
                    filename = f"{invoice.name.replace('/', '_')}.xml"
                    zip_file.writestr(filename, ecf_doc.xml_payload)

        zip_buffer.seek(0)

        # Crear attachment
        attachment = self.env['ir.attachment'].create({
            'name': f'XML_Facturas_B02_{self.periodo}.zip',
            'type': 'binary',
            'datas': zip_buffer.read(),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/zip'
        })

        _logger.info(f"XML de facturas exportados para resumen {self.name}")

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'new',
        }
