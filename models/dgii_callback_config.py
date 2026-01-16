"""
Configuración de URLs y parámetros de callbacks DGII por ambiente.

Este modelo permite configurar:
- URLs de endpoints por ambiente (prueba/producción)
- Parámetros de seguridad (rate limiting, IPs permitidas)
- Configuración de procesamiento asíncrono
"""
import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# URLs por defecto de DGII
DGII_URLS = {
    'precert': {
        'base': 'https://ecf.dgii.gov.do/testecf',
        'recepcion': 'https://ecf.dgii.gov.do/testecf/fe/recepcion/api/ecf',
        'aprobacion': 'https://ecf.dgii.gov.do/testecf/fe/aprobacioncomercial/api/ecf',
        'semilla': 'https://ecf.dgii.gov.do/testecf/fe/autenticacion/api/semilla',
        'validacion': 'https://ecf.dgii.gov.do/testecf/fe/autenticacion/api/validacioncertificado',
    },
    'prod': {
        'base': 'https://ecf.dgii.gov.do',
        'recepcion': 'https://ecf.dgii.gov.do/fe/recepcion/api/ecf',
        'aprobacion': 'https://ecf.dgii.gov.do/fe/aprobacioncomercial/api/ecf',
        'semilla': 'https://ecf.dgii.gov.do/fe/autenticacion/api/semilla',
        'validacion': 'https://ecf.dgii.gov.do/fe/autenticacion/api/validacioncertificado',
    },
}


class DgiiCallbackConfig(models.Model):
    """Configuración de callbacks DGII por ambiente."""

    _name = "dgii.callback.config"
    _description = "Configuración de Callbacks DGII"
    _order = "sequence, id"

    name = fields.Char(string="Nombre", required=True)
    sequence = fields.Integer(string="Secuencia", default=10)
    active = fields.Boolean(string="Activo", default=True)

    # =========================================================================
    # Ambiente
    # =========================================================================
    environment = fields.Selection([
        ('local', 'Local (Desarrollo)'),
        ('precert', 'Pre-certificación DGII'),
        ('prod', 'Producción DGII'),
    ], string="Ambiente", required=True, default='local')

    is_default = fields.Boolean(
        string="Configuración Por Defecto",
        help="Marcar como configuración por defecto para este ambiente"
    )

    # =========================================================================
    # URLs de Endpoints (para recibir callbacks - nuestra URL)
    # =========================================================================
    base_url = fields.Char(
        string="URL Base",
        help="URL base de nuestra instalación Odoo (ej: https://mi-empresa.odoo.com)"
    )

    # Endpoints que exponemos para recibir callbacks
    endpoint_recepcion = fields.Char(
        string="Endpoint Recepción",
        default="/fe/recepcion/api/ecf",
        help="Ruta para recibir e-CF de la DGII"
    )
    endpoint_aprobacion = fields.Char(
        string="Endpoint Aprobación",
        default="/fe/aprobacioncomercial/api/ecf",
        help="Ruta para recibir aprobaciones comerciales"
    )
    endpoint_semilla = fields.Char(
        string="Endpoint Semilla",
        default="/fe/autenticacion/api/semilla",
        help="Ruta para servir semillas de autenticación"
    )
    endpoint_validacion = fields.Char(
        string="Endpoint Validación",
        default="/fe/autenticacion/api/validacioncertificado",
        help="Ruta para validar certificados"
    )

    # URLs completas computadas
    url_recepcion_full = fields.Char(
        string="URL Recepción Completa",
        compute="_compute_full_urls",
        store=True
    )
    url_aprobacion_full = fields.Char(
        string="URL Aprobación Completa",
        compute="_compute_full_urls",
        store=True
    )
    url_semilla_full = fields.Char(
        string="URL Semilla Completa",
        compute="_compute_full_urls",
        store=True
    )
    url_validacion_full = fields.Char(
        string="URL Validación Completa",
        compute="_compute_full_urls",
        store=True
    )

    # =========================================================================
    # URLs de DGII (para enviar a DGII)
    # =========================================================================
    dgii_url_recepcion = fields.Char(
        string="DGII URL Recepción",
        help="URL de DGII para enviar e-CF"
    )
    dgii_url_aprobacion = fields.Char(
        string="DGII URL Aprobación",
        help="URL de DGII para enviar aprobaciones"
    )
    dgii_url_semilla = fields.Char(
        string="DGII URL Semilla",
        help="URL de DGII para obtener semilla"
    )
    dgii_url_validacion = fields.Char(
        string="DGII URL Validación",
        help="URL de DGII para validar certificado"
    )

    # =========================================================================
    # Configuración del Microservicio API (firma y envío)
    # =========================================================================
    api_base_url = fields.Char(
        string="API Base URL",
        default="http://localhost:3000/api",
        help="URL base del microservicio API (ej: https://tu-api.com/api)"
    )
    api_key = fields.Char(
        string="API Key",
        help="Clave de API para autenticación con el microservicio (header x-api-key)"
    )
    api_environment = fields.Selection([
        ('test', 'Test'),
        ('cert', 'Certificación'),
        ('prod', 'Producción'),
    ], string="API Environment", default='cert',
        help="Ambiente a usar en las llamadas al microservicio"
    )
    company_rnc = fields.Char(
        string="RNC Compañía",
        help="RNC de la compañía para usar en las aprobaciones comerciales"
    )

    # =========================================================================
    # Seguridad
    # =========================================================================
    # Rate Limiting
    enable_rate_limit = fields.Boolean(
        string="Habilitar Rate Limiting",
        default=True,
        help="Limitar número de requests por IP/minuto"
    )
    rate_limit_requests = fields.Integer(
        string="Máx. Requests/Minuto",
        default=60,
        help="Máximo número de requests permitidos por minuto por IP"
    )
    rate_limit_burst = fields.Integer(
        string="Burst Permitido",
        default=10,
        help="Número de requests adicionales permitidos en ráfaga"
    )

    # IPs Permitidas
    enable_ip_whitelist = fields.Boolean(
        string="Habilitar Whitelist de IPs",
        default=False,
        help="Solo permitir requests desde IPs específicas"
    )
    allowed_ips = fields.Text(
        string="IPs Permitidas",
        help="Lista de IPs o rangos CIDR permitidos (una por línea)\n"
             "Ejemplo:\n192.168.1.100\n10.0.0.0/8\n2001:db8::/32"
    )

    # IPs de DGII conocidas
    dgii_ips = fields.Text(
        string="IPs de DGII",
        help="IPs conocidas de servidores DGII (una por línea)"
    )

    # Verificación de certificados
    verify_client_cert = fields.Boolean(
        string="Verificar Certificado Cliente",
        default=False,
        help="Requerir certificado digital del cliente"
    )

    # Verificación de firma XML
    verify_xml_signature = fields.Boolean(
        string="Verificar Firma XML",
        default=True,
        help="Verificar firma digital de XMLs recibidos"
    )

    # =========================================================================
    # Procesamiento
    # =========================================================================
    async_processing = fields.Boolean(
        string="Procesamiento Asíncrono",
        default=True,
        help="Procesar callbacks en background usando queue_job"
    )
    queue_channel = fields.Char(
        string="Canal de Cola",
        default="root.dgii_callbacks",
        help="Canal de queue_job para procesar callbacks"
    )

    # Tiempos
    response_timeout = fields.Integer(
        string="Timeout Respuesta (s)",
        default=30,
        help="Tiempo máximo para responder al callback antes de timeout"
    )
    processing_timeout = fields.Integer(
        string="Timeout Procesamiento (s)",
        default=300,
        help="Tiempo máximo para procesar un callback en background"
    )

    # Reintentos
    max_retries = fields.Integer(
        string="Máx. Reintentos",
        default=3,
        help="Número máximo de reintentos para callbacks fallidos"
    )
    retry_delay = fields.Integer(
        string="Delay entre Reintentos (s)",
        default=60,
        help="Segundos de espera entre reintentos"
    )

    # =========================================================================
    # Logging
    # =========================================================================
    log_level = fields.Selection([
        ('minimal', 'Mínimo (solo errores)'),
        ('normal', 'Normal (errores + exitosos)'),
        ('verbose', 'Detallado (todo)'),
        ('debug', 'Debug (incluye payloads)'),
    ], string="Nivel de Log", default='normal')

    log_retention_days = fields.Integer(
        string="Retención de Logs (días)",
        default=90,
        help="Días a mantener registros de callbacks"
    )

    # =========================================================================
    # Compañía
    # =========================================================================
    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        default=lambda self: self.env.company,
        required=True
    )

    # =========================================================================
    # Métodos Computados
    # =========================================================================

    @api.depends('base_url', 'endpoint_recepcion', 'endpoint_aprobacion',
                 'endpoint_semilla', 'endpoint_validacion')
    def _compute_full_urls(self):
        for config in self:
            base = (config.base_url or '').rstrip('/')

            config.url_recepcion_full = f"{base}{config.endpoint_recepcion}" if base else config.endpoint_recepcion
            config.url_aprobacion_full = f"{base}{config.endpoint_aprobacion}" if base else config.endpoint_aprobacion
            config.url_semilla_full = f"{base}{config.endpoint_semilla}" if base else config.endpoint_semilla
            config.url_validacion_full = f"{base}{config.endpoint_validacion}" if base else config.endpoint_validacion

    # =========================================================================
    # Constraints
    # =========================================================================

    @api.constrains('is_default', 'environment', 'company_id')
    def _check_unique_default(self):
        """Solo puede haber una configuración por defecto por ambiente y compañía."""
        for config in self:
            if config.is_default:
                existing = self.search([
                    ('id', '!=', config.id),
                    ('is_default', '=', True),
                    ('environment', '=', config.environment),
                    ('company_id', '=', config.company_id.id),
                ])
                if existing:
                    raise ValidationError(_(
                        "Ya existe una configuración por defecto para el ambiente '%s' "
                        "en la compañía '%s': %s"
                    ) % (config.environment, config.company_id.name, existing.name))

    @api.constrains('rate_limit_requests', 'rate_limit_burst')
    def _check_rate_limits(self):
        for config in self:
            if config.enable_rate_limit:
                if config.rate_limit_requests < 1:
                    raise ValidationError(_("El límite de requests debe ser al menos 1."))
                if config.rate_limit_burst < 0:
                    raise ValidationError(_("El burst no puede ser negativo."))

    # =========================================================================
    # Métodos de Clase
    # =========================================================================

    @api.model
    def get_config(self, environment=None, company=None):
        """
        Obtiene la configuración activa para un ambiente.

        Args:
            environment: 'local', 'precert' o 'prod'. Si es None, usa la por defecto.
            company: res.company record. Si es None, usa la compañía actual.

        Returns:
            dgii.callback.config record o False si no existe.
        """
        company = company or self.env.company

        domain = [
            ('active', '=', True),
            ('company_id', '=', company.id),
        ]

        if environment:
            domain.append(('environment', '=', environment))
            # Buscar primero la por defecto del ambiente
            config = self.search(domain + [('is_default', '=', True)], limit=1)
            if config:
                return config
            # Si no hay default, buscar cualquiera del ambiente
            return self.search(domain, limit=1)
        else:
            # Buscar la configuración por defecto (cualquier ambiente)
            config = self.search(domain + [('is_default', '=', True)], limit=1)
            if config:
                return config
            # Si no hay default, buscar cualquiera
            return self.search(domain, limit=1)

    @api.model
    def get_or_create_config(self, environment='local'):
        """
        Obtiene o crea una configuración para un ambiente.
        """
        config = self.get_config(environment=environment)
        if config:
            return config

        # Crear configuración por defecto
        vals = {
            'name': f"Configuración {environment.upper()}",
            'environment': environment,
            'is_default': True,
        }

        # Precargar URLs de DGII según ambiente
        if environment in DGII_URLS:
            dgii_urls = DGII_URLS[environment]
            vals.update({
                'dgii_url_recepcion': dgii_urls['recepcion'],
                'dgii_url_aprobacion': dgii_urls['aprobacion'],
                'dgii_url_semilla': dgii_urls['semilla'],
                'dgii_url_validacion': dgii_urls['validacion'],
            })

        return self.create(vals)

    # =========================================================================
    # Métodos de Seguridad
    # =========================================================================

    def is_ip_allowed(self, ip_address):
        """
        Verifica si una IP está permitida.

        Args:
            ip_address: string con la IP a verificar

        Returns:
            bool: True si la IP está permitida
        """
        self.ensure_one()

        if not self.enable_ip_whitelist:
            return True

        if not self.allowed_ips:
            return True

        import ipaddress

        try:
            client_ip = ipaddress.ip_address(ip_address)
        except ValueError:
            _logger.warning("[DGII Config] IP inválida: %s", ip_address)
            return False

        # Parsear lista de IPs/rangos permitidos
        allowed_list = [line.strip() for line in self.allowed_ips.split('\n') if line.strip()]

        for allowed in allowed_list:
            try:
                # Intentar como red/rango
                if '/' in allowed:
                    network = ipaddress.ip_network(allowed, strict=False)
                    if client_ip in network:
                        return True
                else:
                    # IP individual
                    if client_ip == ipaddress.ip_address(allowed):
                        return True
            except ValueError:
                _logger.warning("[DGII Config] Entrada IP inválida en whitelist: %s", allowed)
                continue

        return False

    def check_rate_limit(self, ip_address, cache=None):
        """
        Verifica si se excedió el rate limit para una IP.

        Args:
            ip_address: IP del cliente
            cache: dict opcional para mantener contadores en memoria

        Returns:
            tuple: (allowed: bool, remaining: int, reset_time: datetime)
        """
        self.ensure_one()

        if not self.enable_rate_limit:
            return True, self.rate_limit_requests, None

        from datetime import datetime, timedelta

        # Usar cache simple si se proporciona
        if cache is None:
            # Consultar base de datos para conteo reciente
            from_time = datetime.now() - timedelta(minutes=1)
            count = self.env['dgii.callback.request'].search_count([
                ('remote_ip', '=', ip_address),
                ('create_date', '>=', from_time),
            ])
        else:
            # Usar cache en memoria
            key = f"rate:{ip_address}"
            now = datetime.now()
            if key not in cache:
                cache[key] = {'count': 0, 'reset_at': now + timedelta(minutes=1)}
            elif cache[key]['reset_at'] <= now:
                cache[key] = {'count': 0, 'reset_at': now + timedelta(minutes=1)}

            count = cache[key]['count']
            cache[key]['count'] += 1

        max_allowed = self.rate_limit_requests + self.rate_limit_burst
        remaining = max(0, max_allowed - count)
        allowed = count < max_allowed

        return allowed, remaining, datetime.now() + timedelta(minutes=1)

    # =========================================================================
    # Acciones
    # =========================================================================

    def action_set_as_default(self):
        """Establece esta configuración como la por defecto para su ambiente."""
        self.ensure_one()

        # Quitar default de otras del mismo ambiente/compañía
        self.search([
            ('id', '!=', self.id),
            ('environment', '=', self.environment),
            ('company_id', '=', self.company_id.id),
            ('is_default', '=', True),
        ]).write({'is_default': False})

        self.write({'is_default': True})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Configuración Actualizada'),
                'message': _("'%s' es ahora la configuración por defecto para %s.") % (
                    self.name, dict(self._fields['environment'].selection).get(self.environment)
                ),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_load_dgii_urls(self):
        """Carga las URLs oficiales de DGII según el ambiente."""
        self.ensure_one()

        if self.environment not in DGII_URLS:
            raise UserError(_("No hay URLs predefinidas para el ambiente '%s'.") % self.environment)

        dgii_urls = DGII_URLS[self.environment]
        self.write({
            'dgii_url_recepcion': dgii_urls['recepcion'],
            'dgii_url_aprobacion': dgii_urls['aprobacion'],
            'dgii_url_semilla': dgii_urls['semilla'],
            'dgii_url_validacion': dgii_urls['validacion'],
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('URLs Cargadas'),
                'message': _("URLs de DGII cargadas para ambiente %s.") % self.environment,
                'type': 'success',
                'sticky': False,
            }
        }

    def action_test_endpoints(self):
        """Prueba que los endpoints estén accesibles."""
        self.ensure_one()

        import requests

        results = []
        endpoints = [
            ('Recepción', self.url_recepcion_full),
            ('Aprobación', self.url_aprobacion_full),
            ('Semilla', self.url_semilla_full),
            ('Validación', self.url_validacion_full),
        ]

        for name, url in endpoints:
            if not url:
                results.append(f"⚠️ {name}: No configurado")
                continue

            try:
                # Solo verificar que responde (OPTIONS o HEAD)
                resp = requests.options(url, timeout=5)
                if resp.status_code < 500:
                    results.append(f"✅ {name}: OK ({resp.status_code})")
                else:
                    results.append(f"❌ {name}: Error {resp.status_code}")
            except requests.exceptions.ConnectionError:
                results.append(f"❌ {name}: No se puede conectar")
            except requests.exceptions.Timeout:
                results.append(f"⚠️ {name}: Timeout")
            except Exception as e:
                results.append(f"❌ {name}: {str(e)[:50]}")

        message = "\n".join(results)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Resultado de Prueba'),
                'message': message,
                'type': 'info',
                'sticky': True,
            }
        }

    def action_view_callbacks(self):
        """Ver callbacks recibidos con esta configuración."""
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'name': _('Callbacks DGII'),
            'res_model': 'dgii.callback.request',
            'view_mode': 'list,form',
            'domain': [('company_id', '=', self.company_id.id)],
            'context': {'default_company_id': self.company_id.id},
        }

    # =========================================================================
    # Utilidades
    # =========================================================================

    def get_endpoint_info(self):
        """Retorna información de endpoints para mostrar en documentación."""
        self.ensure_one()

        return {
            'recepcion': {
                'method': 'POST',
                'url': self.url_recepcion_full,
                'content_type': 'application/xml',
                'description': 'Recepción de e-CF desde DGII',
            },
            'aprobacion': {
                'method': 'POST',
                'url': self.url_aprobacion_full,
                'content_type': 'application/xml',
                'description': 'Aprobación/Rechazo comercial de e-CF',
            },
            'semilla': {
                'method': 'GET',
                'url': self.url_semilla_full,
                'content_type': 'application/xml',
                'description': 'Obtener semilla de autenticación',
            },
            'validacion': {
                'method': 'POST',
                'url': self.url_validacion_full,
                'content_type': 'application/xml',
                'description': 'Validar certificado con semilla firmada',
            },
        }
