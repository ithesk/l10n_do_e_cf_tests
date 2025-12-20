# -*- coding: utf-8 -*-

import json
import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SendEcfByTypeWizard(models.TransientModel):
    _name = "send.ecf.by.type.wizard"
    _description = "Enviar e-CF por Tipo"

    test_set_id = fields.Many2one('ecf.test.set', string="Set de Pruebas", required=True)

    filter_tipo_ecf = fields.Selection([
        ('all', 'Todos los tipos pendientes'),
        ('31', 'Tipo 31 - Factura Crédito Fiscal'),
        ('32', 'Tipo 32 - Factura Consumo'),
        ('33', 'Tipo 33 - Nota Débito'),
        ('34', 'Tipo 34 - Nota Crédito'),
        ('41', 'Tipo 41 - Compras'),
        ('43', 'Tipo 43 - Gastos Menores'),
        ('44', 'Tipo 44 - Regímenes Especiales'),
        ('45', 'Tipo 45 - Gubernamental'),
        ('46', 'Tipo 46 - Exportaciones'),
        ('47', 'Tipo 47 - Pagos al Exterior'),
    ], string="Tipo a Enviar", default='all', required=True)

    only_failed = fields.Boolean(string="Solo Reenviar Fallidos", default=False)

    # Estadísticas
    pending_count = fields.Integer(string="Casos Pendientes", compute="_compute_counts")
    ready_count = fields.Integer(string="Casos Listos", compute="_compute_counts")
    failed_count = fields.Integer(string="Casos Fallidos", compute="_compute_counts")

    @api.depends('test_set_id', 'filter_tipo_ecf', 'only_failed')
    def _compute_counts(self):
        for wizard in self:
            if not wizard.test_set_id:
                wizard.pending_count = 0
                wizard.ready_count = 0
                wizard.failed_count = 0
                continue

            cases = wizard.test_set_id.ecf_case_ids

            # Filtrar por tipo
            if wizard.filter_tipo_ecf and wizard.filter_tipo_ecf != 'all':
                cases = cases.filtered(lambda c: c.tipo_ecf == wizard.filter_tipo_ecf)

            # Contar por estado
            if wizard.only_failed:
                failed = cases.filtered(lambda c: c.state in ('error', 'rejected'))
                wizard.pending_count = 0
                wizard.ready_count = 0
                wizard.failed_count = len(failed)
            else:
                pending = cases.filtered(lambda c: c.state == 'draft')
                ready = cases.filtered(lambda c: c.state == 'payload_ready')
                failed = cases.filtered(lambda c: c.state in ('error', 'rejected'))

                wizard.pending_count = len(pending)
                wizard.ready_count = len(ready)
                wizard.failed_count = len(failed)

    def action_send(self):
        """Envía los casos seleccionados usando el sistema de proveedores de API"""
        self.ensure_one()

        # Obtener el proveedor de API por defecto
        provider = self.env['ecf.api.provider'].get_default_provider()

        if not provider:
            raise UserError(_(
                "No hay proveedor de API configurado.\n"
                "Configure uno en: e-CF Tests > Proveedores de API"
            ))

        # Obtener casos a enviar
        if self.only_failed:
            cases_to_send = self.test_set_id.ecf_case_ids.filtered(
                lambda c: c.state in ('error', 'rejected')
            )
        else:
            cases_to_send = self.test_set_id.ecf_case_ids.filtered(
                lambda c: c.state == 'payload_ready'
            )

        # Filtrar por tipo
        if self.filter_tipo_ecf and self.filter_tipo_ecf != 'all':
            cases_to_send = cases_to_send.filtered(lambda c: c.tipo_ecf == self.filter_tipo_ecf)

        if not cases_to_send:
            raise UserError(_("No hay casos para enviar con los filtros seleccionados."))

        _logger.info(f"Enviando {len(cases_to_send)} casos via proveedor: {provider.name} ({provider.provider_type})")

        # Ordenar casos según prioridad DGII
        wizard = self.env['run.test.set.wizard'].create({})  # Instancia temporal para usar métodos de ordenamiento
        cases_with_priority = []
        for case in cases_to_send:
            try:
                doc = json.loads(case.payload_json)
                priority = wizard._get_tipo_ecf_priority(doc)
                cases_with_priority.append((priority, case, doc))
            except Exception as e:
                _logger.error(f"Error al parsear payload del caso {case.id}: {e}")
                continue

        # Ordenar por prioridad
        cases_with_priority.sort(key=lambda x: x[0])

        # Enviar documentos
        ok = 0
        errors = []

        for priority, case, doc in cases_with_priority:
            tipo_ecf = doc["ECF"]["Encabezado"]["IdDoc"].get("TipoeCF", "??")
            encf = doc["ECF"]["Encabezado"]["IdDoc"].get("eNCF", "N/A")
            rnc = doc["ECF"]["Encabezado"]["Emisor"].get("RNCEmisor")

            try:
                # Enviar usando el proveedor (registra en log automáticamente)
                success, resp_data, track_id, error_msg, raw_response, signed_xml = provider.send_ecf(
                    doc, rnc=rnc, encf=encf,
                    origin='wizard',
                    test_case_id=case.id
                )

                resp_text = json.dumps(resp_data, ensure_ascii=False) if isinstance(resp_data, dict) else str(resp_data or error_msg)

                if success:
                    ok += 1
                    case.mark_sent(resp_text, track_id=track_id, accepted=True, rejected=False,
                                   raw_response=raw_response, signed_xml=signed_xml)
                    _logger.info(f"Enviado caso {case.id} - Tipo {tipo_ecf} - eNCF {encf} - ACEPTADO")
                else:
                    case.mark_sent(resp_text, track_id=track_id, accepted=False, rejected=True,
                                   raw_response=raw_response, signed_xml=signed_xml)
                    _logger.info(f"Enviado caso {case.id} - Tipo {tipo_ecf} - eNCF {encf} - RECHAZADO: {error_msg}")

            except Exception as e:
                error_msg = f"Error al enviar caso {case.id} ({encf}): {str(e)}"
                _logger.error(error_msg, exc_info=True)
                case.mark_error(str(e))
                errors.append(error_msg)

        # Mensaje de resultado
        msg = f"Enviados via {provider.name}: {ok}/{len(cases_with_priority)} casos aceptados"
        if errors:
            msg += f"\n\nErrores:\n" + "\n".join(errors[:5])  # Mostrar primeros 5 errores

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Resultado del Envío'),
                'message': msg,
                'type': 'success' if ok == len(cases_with_priority) else 'warning',
                'sticky': True,
            }
        }
