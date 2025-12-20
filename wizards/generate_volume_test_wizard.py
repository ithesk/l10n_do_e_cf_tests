import json
import logging
import uuid
from datetime import datetime
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class GenerateVolumeTestWizard(models.TransientModel):
    _name = "generate.volume.test.wizard"
    _description = "Wizard para Generar Casos de Volumen"

    test_set_id = fields.Many2one(
        "ecf.test.set",
        string="Set de Pruebas",
        required=True,
        readonly=True
    )

    template_case_id = fields.Many2one(
        "ecf.test.case",
        string="Caso Plantilla",
        domain="[('test_set_id', '=', test_set_id), ('payload_json', '!=', False)]",
        help="Seleccione un caso existente para usar como plantilla"
    )

    # Secuencia manual
    sequence_start = fields.Integer(
        string="Secuencia Inicial",
        required=True,
        default=1,
        help="Número de secuencia inicial (ej: 88)"
    )

    sequence_end = fields.Integer(
        string="Secuencia Final",
        required=True,
        default=10,
        help="Número de secuencia final (ej: 90)"
    )

    quantity = fields.Integer(
        string="Cantidad",
        compute="_compute_quantity",
        help="Número de casos que se generarán"
    )

    # Opciones
    auto_send = fields.Boolean(
        string="Enviar Automáticamente",
        default=False,
        help="Si está activado, los casos generados se enviarán automáticamente a la API"
    )

    @api.depends('sequence_start', 'sequence_end')
    def _compute_quantity(self):
        for wizard in self:
            if wizard.sequence_end >= wizard.sequence_start:
                wizard.quantity = wizard.sequence_end - wizard.sequence_start + 1
            else:
                wizard.quantity = 0

    def _generate_encf(self, tipo_ecf, sequence):
        """
        Genera el eNCF con el formato correcto:
        E + TipoeCF (2 dígitos) + Secuencia (10 dígitos con ceros)
        Ejemplo: E310000000088
        """
        tipo_str = str(tipo_ecf).zfill(2)
        seq_str = str(sequence).zfill(10)
        return f"E{tipo_str}{seq_str}"

    def action_generate(self):
        """Genera los casos de volumen basados en la plantilla"""
        self.ensure_one()

        if not self.template_case_id:
            raise UserError(_("Debe seleccionar un caso plantilla."))

        if self.sequence_start <= 0:
            raise UserError(_("La secuencia inicial debe ser mayor a 0."))

        if self.sequence_end < self.sequence_start:
            raise UserError(_("La secuencia final debe ser mayor o igual a la inicial."))

        if self.quantity <= 0:
            raise UserError(_("La cantidad debe ser mayor a 0."))

        if self.quantity > 10000:
            raise UserError(_("No se pueden generar más de 10,000 casos a la vez."))

        template = self.template_case_id

        # Parsear JSON de la plantilla
        try:
            template_json = json.loads(template.payload_json)
        except json.JSONDecodeError as e:
            raise UserError(_("El JSON de la plantilla no es válido: %s") % str(e))

        # Obtener tipo de e-CF de la plantilla
        tipo_ecf = template.tipo_ecf
        if not tipo_ecf:
            # Intentar obtenerlo del JSON
            tipo_ecf = str(template_json.get("ECF", {}).get("Encabezado", {}).get("IdDoc", {}).get("TipoeCF", ""))

        if not tipo_ecf:
            raise UserError(_("No se pudo determinar el tipo de e-CF de la plantilla."))

        # Generar lista de secuencias
        sequences = list(range(self.sequence_start, self.sequence_end + 1))

        # Generar casos
        id_lote = str(uuid.uuid4())
        created_cases = self.env['ecf.test.case']
        current_time = datetime.now().strftime("%d-%m-%Y %H:%M:%S")

        for seq in sequences:
            # Clonar el JSON y modificar el eNCF
            case_json = json.loads(json.dumps(template_json))  # Deep copy

            # Generar nuevo eNCF
            new_encf = self._generate_encf(tipo_ecf, seq)

            # Actualizar eNCF en el JSON
            if "ECF" in case_json and "Encabezado" in case_json["ECF"]:
                if "IdDoc" in case_json["ECF"]["Encabezado"]:
                    case_json["ECF"]["Encabezado"]["IdDoc"]["eNCF"] = new_encf

            # Actualizar FechaHoraFirma
            if "ECF" in case_json:
                case_json["ECF"]["FechaHoraFirma"] = current_time

            # Crear el caso
            case_vals = {
                'name': f"VOL-{tipo_ecf}-{seq:010d}",
                'test_set_id': self.test_set_id.id,
                'tipo_ecf': tipo_ecf,
                'is_volume_case': True,
                'template_case_id': template.id,
                'volume_sequence': seq,
                'id_lote': id_lote,
                'payload_json': json.dumps(case_json, indent=2, ensure_ascii=False),
                'state': 'payload_ready',
                'api_status': 'pending',
                # Copiar datos relevantes de la plantilla
                'receptor_rnc': template.receptor_rnc,
                'receptor_nombre': template.receptor_nombre,
                'monto_total': template.monto_total,
            }

            case = self.env['ecf.test.case'].create(case_vals)
            created_cases |= case

        # Actualizar estado del set si está en borrador
        if self.test_set_id.state == 'draft':
            self.test_set_id.write({'state': 'in_progress'})

        _logger.info(
            f"Generados {len(created_cases)} casos de volumen para set {self.test_set_id.name}, "
            f"secuencias {sequences[0]} a {sequences[-1]}"
        )

        # Enviar automáticamente si está habilitado
        if self.auto_send and created_cases:
            return self._send_generated_cases(created_cases)

        # Mostrar resultado
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Casos Generados'),
                'message': _(
                    "Se generaron %d casos de volumen.\n"
                    "Tipo: %s, eNCF: E%s%010d - E%s%010d"
                ) % (len(created_cases), tipo_ecf, tipo_ecf, sequences[0], tipo_ecf, sequences[-1]),
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.client',
                    'tag': 'soft_reload',
                }
            }
        }

    def _send_generated_cases(self, cases):
        """Envía los casos generados a la API"""
        sent = 0
        errors = 0

        for case in cases:
            try:
                case.action_send_to_api()
                if case.api_status == 'accepted':
                    sent += 1
                else:
                    errors += 1
            except Exception as e:
                _logger.error(f"Error enviando caso {case.name}: {str(e)}")
                errors += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Envío Completado'),
                'message': _(
                    "Casos generados: %d\n"
                    "Enviados exitosamente: %d\n"
                    "Con errores: %d"
                ) % (len(cases), sent, errors),
                'type': 'success' if errors == 0 else 'warning',
                'sticky': True,
                'next': {
                    'type': 'ir.actions.client',
                    'tag': 'soft_reload',
                }
            }
        }
