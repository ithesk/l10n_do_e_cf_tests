from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ========================================================================
    # Configuración de MSeller API (API Externa Principal)
    # ========================================================================
    mseller_host = fields.Char(
        string="MSeller Host",
        help="URL base de MSeller API (ej: https://ecf.api.mseller.app)",
        config_parameter='l10n_do_e_cf_tests.mseller_host',
        default='https://ecf.api.mseller.app'
    )

    mseller_env = fields.Selection([
        ('TesteCF', 'Pruebas (TesteCF)'),
        ('CerteCF', 'Certificación (CerteCF)'),
        ('eCF', 'Producción (eCF)'),
    ], string="Ambiente MSeller",
        help="Ambiente de MSeller para envío de e-CF",
        config_parameter='l10n_do_e_cf_tests.mseller_env',
        default='TesteCF'
    )

    mseller_email = fields.Char(
        string="MSeller Email",
        help="Email para autenticación en MSeller API",
        config_parameter='l10n_do_e_cf_tests.mseller_email'
    )

    mseller_password = fields.Char(
        string="MSeller Password",
        help="Contraseña para autenticación en MSeller API",
        config_parameter='l10n_do_e_cf_tests.mseller_password'
    )

    mseller_api_key = fields.Char(
        string="MSeller API Key",
        help="API Key (X-API-KEY) para MSeller",
        config_parameter='l10n_do_e_cf_tests.mseller_api_key'
    )

    mseller_timeout = fields.Integer(
        string="Timeout MSeller (segundos)",
        help="Tiempo máximo de espera para respuesta de MSeller API",
        config_parameter='l10n_do_e_cf_tests.mseller_timeout',
        default=60
    )

    # ========================================================================
    # Configuración de API Interna (Opcional, compatibilidad hacia atrás)
    # ========================================================================
    ecf_test_api_url = fields.Char(
        string="URL API Interna (Opcional)",
        help="URL del endpoint de API interna alternativa para envío de e-CF",
        config_parameter='l10n_do_e_cf_tests.api_url'
    )

    ecf_test_api_token = fields.Char(
        string="Token API Interna",
        help="Token de autenticación Bearer para la API interna",
        config_parameter='l10n_do_e_cf_tests.api_token'
    )

    ecf_test_api_timeout = fields.Integer(
        string="Timeout API Interna (segundos)",
        help="Tiempo máximo de espera para respuesta de la API interna",
        config_parameter='l10n_do_e_cf_tests.api_timeout',
        default=30
    )

    # ========================================================================
    # Configuración General
    # ========================================================================
    ecf_test_use_mseller = fields.Boolean(
        string="Usar MSeller API",
        help="Si está activado, se usará MSeller API. Si no, se usará la API interna configurada arriba.",
        config_parameter='l10n_do_e_cf_tests.use_mseller',
        default=True
    )

    ecf_test_enable_debug_log = fields.Boolean(
        string="Habilitar Log Detallado",
        help="Guardar request/response completo de cada llamada a la API",
        config_parameter='l10n_do_e_cf_tests.enable_debug_log',
        default=True
    )
