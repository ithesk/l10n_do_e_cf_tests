import logging
import json
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class EcfTestRfceCase(models.Model):
    _name = "ecf.test.rfce.case"
    _description = "Caso de Prueba RFCE (Resumen Factura Consumo)"
    _order = "sequence, id"

    # Control
    sequence = fields.Integer(string="Secuencia", default=10, index=True)
    name = fields.Char(string="Nombre del Caso", required=True)
    test_set_id = fields.Many2one("ecf.test.set", string="Set de Pruebas", ondelete="cascade", required=True)
    fila_excel = fields.Integer(string="Fila en Excel")
    id_lote = fields.Char(string="ID de Lote", index=True)
    hash_input = fields.Char(string="Hash de Entrada", index=True)
    payload_json = fields.Text(string="Payload JSON (referencia)")
    caso_prueba = fields.Char(string="Caso de Prueba")
    version = fields.Char(string="Versión")
    encf = fields.Char(string="ENCF")
    codigo_seguridad_ecf = fields.Char(string="Código Seguridad e-CF")

    # Datos del Resumen
    fecha_desde = fields.Date(string="Fecha Desde", required=True)
    fecha_hasta = fields.Date(string="Fecha Hasta", required=True)
    periodo = fields.Char(string="Período (YYYYMM)")

    # Totales del Resumen
    cantidad_comprobantes = fields.Integer(string="Cantidad de Comprobantes")
    monto_total = fields.Float(string="Monto Total", digits=(16, 2))
    monto_gravado = fields.Float(string="Monto Gravado", digits=(16, 2))
    total_itbis = fields.Float(string="Total ITBIS", digits=(16, 2))
    monto_exento = fields.Float(string="Monto Exento", digits=(16, 2))
    monto_no_facturable = fields.Float(string="Monto No Facturable", digits=(16, 2))
    monto_periodo = fields.Char(string="Monto/Período (según Excel)")
    tipo_ingreso = fields.Char(string="Tipo de Ingreso")
    tipo_pago = fields.Char(string="Tipo de Pago")

    # Facturas incluidas en el resumen
    invoice_ids = fields.Many2many(
        'account.move',
        'ecf_rfce_case_invoice_rel',
        'rfce_case_id',
        'invoice_id',
        string="Facturas B02 < 250k"
    )

    # Resumen generado
    resumen_id = fields.Many2one("e.cf.consumo.resumen", string="Resumen Generado", readonly=True)

    # Estado
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('invoices_created', 'Facturas Creadas'),
        ('resumen_generated', 'Resumen Generado'),
        ('sent', 'Enviado a DGII'),
        ('accepted', 'Aceptado'),
        ('rejected', 'Rechazado'),
        ('error', 'Error'),
    ], string="Estado", default='draft', readonly=True)

    track_id = fields.Char(string="TrackID DGII", readonly=True)
    dgii_response = fields.Text(string="Respuesta DGII", readonly=True)
    error_message = fields.Text(string="Mensaje de Error", readonly=True)
    expected_result = fields.Char(string="Resultado Esperado")
    actual_result = fields.Char(string="Resultado Obtenido", readonly=True)
    api_status = fields.Selection([
        ('pending', 'Pendiente'),
        ('ready', 'Payload Listo'),
    ], string="Estado API", default='pending', readonly=True)

    def set_payload(self, payload_dict, hash_input, id_lote, fila_excel):
        """Guardar payload de referencia para RFCE (sin envío)."""
        self.write({
            'payload_json': json.dumps(payload_dict, ensure_ascii=False),
            'hash_input': hash_input,
            'id_lote': id_lote,
            'fila_excel': fila_excel,
            'api_status': 'ready',
        })

    def action_create_invoices(self):
        """Crea las facturas B02 < 250k para el resumen"""
        self.ensure_one()

        if self.invoice_ids:
            raise UserError(_("Ya existen facturas creadas para este caso."))

        # Aquí se crearían las facturas según el detalle del Excel
        # Por ahora creamos facturas de ejemplo

        _logger.info(f"Creando facturas B02 < 250k para resumen {self.name}")

        self.write({'state': 'invoices_created'})

        return True

    def action_generate_resumen(self):
        """Genera el resumen RFCE"""
        self.ensure_one()

        if not self.invoice_ids:
            raise UserError(_("Debe crear las facturas primero."))

        if self.resumen_id:
            raise UserError(_("Ya existe un resumen generado para este caso."))

        # Crear el resumen
        resumen = self.env['e.cf.consumo.resumen'].create({
            'name': f'Resumen {self.periodo or self.name}',
            'fecha_desde': self.fecha_desde,
            'fecha_hasta': self.fecha_hasta,
            'invoice_ids': [(6, 0, self.invoice_ids.ids)],
        })

        self.write({
            'resumen_id': resumen.id,
            'state': 'resumen_generated'
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'e.cf.consumo.resumen',
            'res_id': resumen.id,
            'view_mode': 'form',
            'target': 'current',
        }
