import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class EcfTestSet(models.Model):
    _name = "ecf.test.set"
    _description = "Set de Pruebas DGII"
    _order = "create_date desc"

    name = fields.Char(string="Nombre del Set", required=True)
    description = fields.Text(string="Descripción")

    # Estadísticas de casos de volumen
    volume_cases_generated = fields.Integer(
        string="Casos Volumen",
        compute="_compute_volume_stats",
        help="Cantidad de casos generados para pruebas de volumen"
    )

    @api.depends('ecf_case_ids', 'ecf_case_ids.is_volume_case')
    def _compute_volume_stats(self):
        for record in self:
            record.volume_cases_generated = len(
                record.ecf_case_ids.filtered(lambda c: c.is_volume_case)
            )

    def action_generate_volume_cases(self):
        """Abre wizard para generar casos de volumen"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Generar Casos de Volumen',
            'res_model': 'generate.volume.test.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_test_set_id': self.id,
            },
        }

    # Casos de prueba
    ecf_case_ids = fields.One2many('ecf.test.case', 'test_set_id', string="Casos e-CF")
    rfce_case_ids = fields.One2many('ecf.test.rfce.case', 'test_set_id', string="Casos RFCE")

    # Estadísticas
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
        ('certified', 'Certificado'),
    ], string="Estado", default='draft')

    certification_date = fields.Datetime(string="Fecha de Certificación")
    certification_notes = fields.Text(string="Notas de Certificación")

    @api.depends('ecf_case_ids', 'ecf_case_ids.state', 'rfce_case_ids', 'rfce_case_ids.state')
    def _compute_stats(self):
        for record in self:
            ecf_cases = record.ecf_case_ids
            rfce_cases = record.rfce_case_ids  # Conservado por compatibilidad, no se usa en pipeline actual.

            record.total_cases = len(ecf_cases) + len(rfce_cases)

            ecf_pending = ecf_cases.filtered(lambda c: c.state == 'draft')
            ecf_ready = ecf_cases.filtered(lambda c: c.state == 'payload_ready')
            ecf_sent = ecf_cases.filtered(lambda c: c.state == 'sent')
            ecf_accepted = ecf_cases.filtered(lambda c: c.state == 'accepted')
            ecf_rejected = ecf_cases.filtered(lambda c: c.state == 'rejected')
            ecf_error = ecf_cases.filtered(lambda c: c.state == 'error')

            record.cases_pending = len(ecf_pending)
            record.cases_ready = len(ecf_ready)
            record.cases_sent = len(ecf_sent)
            record.cases_accepted = len(ecf_accepted)
            record.cases_rejected = len(ecf_rejected)
            record.cases_error = len(ecf_error)

    def action_run_all_tests(self):
        """Deprecado: el flujo ahora es Excel -> JSON -> API interna desde el wizard."""
        raise UserError(_("Use el asistente de importación para generar y enviar JSON a la API interna."))

    def action_send_all_to_dgii(self):
        """Deprecado: el envío se realiza vía API interna, no a DGII directamente."""
        raise UserError(_("El envío masivo DGII fue removido. Use el wizard actualizado."))

    def action_check_all_status(self):
        """Deprecado: la consulta de estados DGII ya no aplica a este módulo."""
        raise UserError(_("La consulta de estados DGII fue removida. Revise las respuestas de la API interna."))

    def action_send_by_type(self):
        """Abre wizard para enviar casos por tipo de e-CF"""
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'name': 'Enviar por Tipo de e-CF',
            'res_model': 'send.ecf.by.type.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_test_set_id': self.id,
            },
        }

    def action_resend_failed(self):
        """Reenvía casos que fallaron o fueron rechazados"""
        self.ensure_one()

        failed_cases = self.ecf_case_ids.filtered(lambda c: c.state in ('error', 'rejected'))

        if not failed_cases:
            raise UserError(_("No hay casos fallidos o rechazados para reenviar."))

        return {
            'type': 'ir.actions.act_window',
            'name': 'Reenviar Casos Fallidos',
            'res_model': 'send.ecf.by.type.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_test_set_id': self.id,
                'default_only_failed': True,
            },
        }

    def action_open_simulator(self):
        """Abre el simulador de documentos e-CF"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Simulador de Documentos e-CF',
            'res_model': 'ecf.simulation.document',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_test_set_id': self.id,
            },
        }

    def action_download_all_json(self):
        """Descarga todos los JSONs del set como un archivo ZIP"""
        import base64
        import io
        import json
        import zipfile

        self.ensure_one()

        cases_with_json = self.ecf_case_ids.filtered(lambda c: c.payload_json)

        if not cases_with_json:
            raise UserError(_("No hay JSONs generados en este set de pruebas."))

        # Crear ZIP en memoria
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for case in cases_with_json:
                try:
                    data = json.loads(case.payload_json)
                    json_content = json.dumps(data, indent=2, ensure_ascii=False)
                except Exception:
                    json_content = case.payload_json

                # Nombre del archivo
                tipo = case.tipo_ecf or "XX"
                encf = ""
                try:
                    data = json.loads(case.payload_json)
                    encf = data.get("ECF", {}).get("Encabezado", {}).get("IdDoc", {}).get("eNCF", "")
                except Exception:
                    pass

                filename = f"ecf_{tipo}_{encf or case.id}.json"
                zip_file.writestr(filename, json_content.encode('utf-8'))

        zip_buffer.seek(0)

        # Crear attachment
        zip_filename = f"jsons_{self.name.replace(' ', '_')}_{self.id}.zip"
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
