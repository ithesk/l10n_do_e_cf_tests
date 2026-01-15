# -*- coding: utf-8 -*-

import json
import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AcecfCase(models.Model):
    _name = "acecf.case"
    _description = "Caso de Aprobacion Comercial e-CF (ACECF)"
    _order = "sequence, id"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # Control
    sequence = fields.Integer(string="Secuencia", default=10, index=True)
    name = fields.Char(string="Nombre del Caso", required=True)
    acecf_set_id = fields.Many2one(
        "acecf.set",
        string="Set de Aprobaciones",
        ondelete="cascade",
        required=True
    )
    fila_excel = fields.Integer(
        string="Fila en Excel",
        help="Numero de fila original en el archivo importado."
    )
    id_lote = fields.Char(string="ID de Lote", index=True, help="UUID generado por importacion.")

    # Datos del ACECF
    version = fields.Char(string="Version", default="1.0")
    rnc_emisor = fields.Char(string="RNC Emisor", index=True)
    encf = fields.Char(string="eNCF", index=True, required=True)
    fecha_emision = fields.Char(string="Fecha Emision")
    monto_total = fields.Float(string="Monto Total", digits=(16, 2))
    rnc_comprador = fields.Char(string="RNC Comprador", index=True)
    estado_aprobacion = fields.Selection([
        ('1', 'Aprobado'),
        ('2', 'Rechazado'),
    ], string="Estado Aprobacion", default='1')
    detalle_motivo_rechazo = fields.Text(string="Detalle Motivo Rechazo")
    fecha_hora_aprobacion = fields.Char(string="Fecha/Hora Aprobacion Comercial")

    # Payload y trazabilidad
    hash_input = fields.Char(string="Hash de Entrada", index=True)
    payload_json = fields.Text(string="Payload JSON")

    # Campos de respuesta API
    api_response = fields.Text(string="Respuesta API (JSON)")
    api_response_raw = fields.Text(string="Respuesta API Completa")
    track_id = fields.Char(string="TrackID DGII")
    error_message = fields.Text(string="Mensaje de Error")

    # Estado global del caso
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('payload_ready', 'Payload Listo'),
        ('sent', 'Enviado a API'),
        ('accepted', 'Aceptado'),
        ('rejected', 'Rechazado'),
        ('error', 'Error'),
    ], string="Estado", default='draft', tracking=True)

    api_status = fields.Selection([
        ('pending', 'Pendiente'),
        ('sent', 'Enviado'),
        ('accepted', 'Aceptado'),
        ('rejected', 'Rechazado'),
        ('error', 'Error'),
    ], string="Estado API", default='pending')

    # Relacion con logs de API
    api_log_ids = fields.One2many(
        "ecf.api.log",
        "acecf_case_id",
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
        """Accion para ver los logs de API relacionados"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Logs API - {self.name}',
            'res_model': 'ecf.api.log',
            'domain': [('acecf_case_id', '=', self.id)],
            'view_mode': 'list,form',
            'context': {'default_acecf_case_id': self.id},
        }

    def set_payload(self, payload_dict, hash_input, id_lote, fila_excel):
        """Guardar payload y trazabilidad en el caso."""
        self.write({
            'payload_json': json.dumps(payload_dict, indent=2, ensure_ascii=False),
            'hash_input': hash_input,
            'id_lote': id_lote,
            'fila_excel': fila_excel,
            'state': 'payload_ready',
            'api_status': 'pending',
        })

    def mark_sent(self, response_text, track_id=None, accepted=False, rejected=False, raw_response=None):
        """Actualizar estado despues de envio a la API."""
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

        if raw_response:
            vals['api_response_raw'] = raw_response

        self.write(vals)

    def mark_error(self, message):
        """Guardar error de procesamiento."""
        self.write({
            'error_message': message,
            'state': 'error',
            'api_status': 'error',
        })

    def action_send_to_api(self):
        """Envia el JSON actual a la API configurada usando endpoint ACECF"""
        self.ensure_one()

        if not self.payload_json:
            raise UserError(_("No hay JSON para enviar."))

        # Parsear el JSON actual
        try:
            doc = json.loads(self.payload_json)
        except json.JSONDecodeError as e:
            self.mark_error(f"JSON invalido: {str(e)}")
            raise UserError(_("El JSON no es valido: %s") % str(e))

        # Obtener el proveedor de API por defecto
        provider = self.env['ecf.api.provider'].get_default_provider()

        if not provider:
            raise UserError(_(
                "No hay proveedor de API configurado. "
                "Configure uno en e-CF Tests > Proveedores de API."
            ))

        _logger.info(f"[ACECF Case] Enviando caso {self.name} via proveedor: {provider.name}")

        # Enviar usando el metodo especifico para ACECF
        success, resp_data, track_id, error_msg, raw_response, signed_xml = provider.send_acecf(
            doc,
            origin='acecf_case',
            acecf_case_id=self.id
        )

        # Formatear respuesta
        resp_text = json.dumps(resp_data, indent=2, ensure_ascii=False) if resp_data else error_msg

        if success:
            self.write({
                'api_response': resp_text,
                'api_response_raw': raw_response,
                'track_id': track_id,
                'error_message': False,
                'state': 'accepted',
                'api_status': 'accepted',
            })
            return self._show_notification('success', f"Enviado exitosamente via {provider.name}")
        else:
            self.write({
                'api_response': resp_text,
                'api_response_raw': raw_response,
                'track_id': track_id,
                'error_message': error_msg,
                'state': 'rejected',
                'api_status': 'rejected',
            })
            return self._show_notification('warning', f"Error: {error_msg}")

    def _show_notification(self, notif_type, message):
        """Muestra notificacion y recarga la vista"""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Resultado del Envio'),
                'message': message,
                'type': notif_type,
                'sticky': notif_type == 'error',
                'next': {
                    'type': 'ir.actions.client',
                    'tag': 'soft_reload',
                }
            }
        }

    def action_download_json(self):
        """Descarga el JSON del caso como archivo"""
        import base64
        self.ensure_one()

        if not self.payload_json:
            raise UserError(_("No hay JSON generado para este caso."))

        try:
            data = json.loads(self.payload_json)
            json_content = json.dumps(data, indent=2, ensure_ascii=False)
        except Exception:
            json_content = self.payload_json

        filename = f"acecf_{self.encf or self.id}.json"

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

    @api.depends('payload_json')
    def _compute_payload_formatted(self):
        for case in self:
            if case.payload_json:
                try:
                    data = json.loads(case.payload_json)
                    case.payload_json_formatted = json.dumps(data, indent=2, ensure_ascii=False)
                except Exception:
                    case.payload_json_formatted = case.payload_json
            else:
                case.payload_json_formatted = ""

    payload_json_formatted = fields.Text(
        string="JSON Formateado",
        compute="_compute_payload_formatted"
    )
