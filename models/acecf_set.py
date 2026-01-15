# -*- coding: utf-8 -*-

import base64
import io
import json
import logging
import zipfile

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AcecfSet(models.Model):
    _name = "acecf.set"
    _description = "Set de Aprobaciones Comerciales e-CF"
    _order = "create_date desc"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Nombre del Set", required=True, tracking=True)
    description = fields.Text(string="Descripcion")

    # Casos de aprobacion comercial
    acecf_case_ids = fields.One2many(
        'acecf.case',
        'acecf_set_id',
        string="Casos ACECF"
    )

    # Estadisticas
    total_cases = fields.Integer(string="Total de Casos", compute="_compute_stats")
    cases_pending = fields.Integer(string="Pendientes", compute="_compute_stats")
    cases_ready = fields.Integer(string="Payload Listo", compute="_compute_stats")
    cases_sent = fields.Integer(string="Enviados", compute="_compute_stats")
    cases_accepted = fields.Integer(string="Aceptados", compute="_compute_stats")
    cases_rejected = fields.Integer(string="Rechazados", compute="_compute_stats")
    cases_error = fields.Integer(string="Con Error", compute="_compute_stats")

    # Estado
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('in_progress', 'En Progreso'),
        ('completed', 'Completado'),
    ], string="Estado", default='draft', tracking=True)

    @api.depends('acecf_case_ids', 'acecf_case_ids.state')
    def _compute_stats(self):
        for record in self:
            cases = record.acecf_case_ids

            record.total_cases = len(cases)
            record.cases_pending = len(cases.filtered(lambda c: c.state == 'draft'))
            record.cases_ready = len(cases.filtered(lambda c: c.state == 'payload_ready'))
            record.cases_sent = len(cases.filtered(lambda c: c.state == 'sent'))
            record.cases_accepted = len(cases.filtered(lambda c: c.state == 'accepted'))
            record.cases_rejected = len(cases.filtered(lambda c: c.state == 'rejected'))
            record.cases_error = len(cases.filtered(lambda c: c.state == 'error'))

    def action_send_all(self):
        """Envia todos los casos con payload listo usando endpoint ACECF"""
        self.ensure_one()

        cases_to_send = self.acecf_case_ids.filtered(lambda c: c.state == 'payload_ready')

        if not cases_to_send:
            raise UserError(_("No hay casos con payload listo para enviar."))

        # Obtener el proveedor de API por defecto
        provider = self.env['ecf.api.provider'].get_default_provider()

        if not provider:
            raise UserError(_(
                "No hay proveedor de API configurado. "
                "Configure uno en e-CF Tests > Proveedores de API."
            ))

        _logger.info(f"Enviando {len(cases_to_send)} casos ACECF via {provider.name}")

        ok = 0
        for case in cases_to_send:
            try:
                doc = json.loads(case.payload_json)

                # Usar metodo especifico para ACECF
                success, resp_data, track_id, error_msg, raw_response, signed_xml = provider.send_acecf(
                    doc,
                    origin='acecf_set',
                    acecf_case_id=case.id
                )

                resp_text = json.dumps(resp_data, ensure_ascii=False) if isinstance(resp_data, dict) else str(resp_data or error_msg)

                if success:
                    ok += 1
                    case.mark_sent(resp_text, track_id=track_id, accepted=True, rejected=False, raw_response=raw_response)
                    _logger.info(f"ACECF enviado: {case.name} - eNCF {case.encf} - ACEPTADO")
                else:
                    case.mark_sent(resp_text, track_id=track_id, accepted=False, rejected=True, raw_response=raw_response)
                    _logger.info(f"ACECF enviado: {case.name} - eNCF {case.encf} - RECHAZADO: {error_msg}")

            except Exception as e:
                error_msg = f"Error al enviar: {str(e)}"
                _logger.error(f"ACECF {case.name}: {error_msg}", exc_info=True)
                case.mark_error(error_msg)

        self.write({'state': 'completed'})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Envio Completado'),
                'message': _(f'{ok}/{len(cases_to_send)} casos enviados exitosamente'),
                'type': 'success' if ok == len(cases_to_send) else 'warning',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.client',
                    'tag': 'soft_reload',
                }
            }
        }

    def action_resend_failed(self):
        """Reenvia casos que fallaron o fueron rechazados"""
        self.ensure_one()

        failed_cases = self.acecf_case_ids.filtered(lambda c: c.state in ('error', 'rejected'))

        if not failed_cases:
            raise UserError(_("No hay casos fallidos o rechazados para reenviar."))

        # Resetear estado para reenvio
        failed_cases.write({
            'state': 'payload_ready',
            'api_status': 'pending',
            'error_message': False,
        })

        return self.action_send_all()

    def action_download_all_json(self):
        """Descarga todos los JSONs del set como un archivo ZIP"""
        self.ensure_one()

        cases_with_json = self.acecf_case_ids.filtered(lambda c: c.payload_json)

        if not cases_with_json:
            raise UserError(_("No hay JSONs generados en este set."))

        # Crear ZIP en memoria
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for case in cases_with_json:
                try:
                    data = json.loads(case.payload_json)
                    json_content = json.dumps(data, indent=2, ensure_ascii=False)
                except Exception:
                    json_content = case.payload_json

                filename = f"acecf_{case.encf or case.id}.json"
                zip_file.writestr(filename, json_content.encode('utf-8'))

        zip_buffer.seek(0)

        # Crear attachment
        zip_filename = f"acecf_{self.name.replace(' ', '_')}_{self.id}.zip"
        attachment = self.env['ir.attachment'].create({
            'name': zip_filename,
            'type': 'binary',
            'datas': base64.b64encode(zip_buffer.read()),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/zip',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }
