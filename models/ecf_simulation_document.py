# -*- coding: utf-8 -*-

import json
import logging
import hashlib
import uuid
from datetime import datetime

import requests
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class EcfSimulationDocument(models.Model):
    _name = "ecf.simulation.document"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Simulador de Documentos e-CF DGII"
    _order = "create_date desc"

    # ========================================================================
    # Campos Principales
    # ========================================================================
    name = fields.Char(
        string="Nombre del Documento",
        required=True,
        default=lambda self: f"Simulación {datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    test_set_id = fields.Many2one(
        "ecf.test.set",
        string="Set de Pruebas",
        help="Opcional: Agregar este caso a un set de pruebas existente"
    )

    # Tipo de Documento
    tipo_ecf = fields.Selection([
        ('31', '31 - Factura de Crédito Fiscal'),
        ('32', '32 - Factura de Consumo'),
        ('33', '33 - Nota de Débito'),
        ('34', '34 - Nota de Crédito'),
        ('41', '41 - Compras'),
        ('43', '43 - Gastos Menores'),
        ('44', '44 - Regímenes Especiales'),
        ('45', '45 - Gubernamental'),
        ('46', '46 - Exportaciones'),
        ('47', '47 - Pagos al Exterior'),
    ], string="Tipo e-CF", required=True, default='31')

    # ========================================================================
    # Generación de eNCF
    # ========================================================================
    encf_mode = fields.Selection([
        ('auto', 'Automático'),
        ('manual', 'Manual'),
    ], string="Modo eNCF", default='auto', required=True)

    encf_manual = fields.Char(
        string="eNCF Manual",
        help="Ingrese el eNCF completo (ej: E310000000001)"
    )
    encf_generated = fields.Char(
        string="eNCF Generado",
        compute="_compute_encf_generated",
        help="eNCF generado automáticamente"
    )
    encf_sequence_counter = fields.Integer(
        string="Contador Secuencia",
        default=1,
        help="Contador interno para secuencia de eNCF"
    )
    fecha_vencimiento_secuencia = fields.Date(
        string="Fecha Vencimiento Secuencia",
        default=lambda self: fields.Date.to_date('2025-12-31')
    )

    # ========================================================================
    # Datos del Emisor (auto-llenados desde company)
    # ========================================================================
    rnc_emisor = fields.Char(string="RNC Emisor")
    razon_social_emisor = fields.Char(string="Razón Social Emisor")
    nombre_comercial = fields.Char(string="Nombre Comercial")
    direccion_emisor = fields.Char(string="Dirección Emisor")
    municipio_emisor = fields.Char(string="Municipio", default="010100")
    provincia_emisor = fields.Char(string="Provincia", default="010000")
    telefono_emisor = fields.Char(string="Teléfono Emisor")
    correo_emisor = fields.Char(string="Correo Emisor")
    website_emisor = fields.Char(string="Website")

    # ========================================================================
    # Datos del Comprador/Receptor
    # ========================================================================
    receptor_rnc = fields.Char(string="RNC/Cedula Comprador")
    receptor_nombre = fields.Char(string="Razon Social Comprador")
    receptor_direccion = fields.Char(string="Direccion Comprador")
    receptor_municipio = fields.Char(
        string="Municipio Comprador",
        help="Codigo DGII del municipio (ej: 010100 para Distrito Nacional)"
    )
    receptor_provincia = fields.Char(
        string="Provincia Comprador",
        help="Codigo DGII de la provincia (ej: 010000 para Distrito Nacional)"
    )
    receptor_correo = fields.Char(string="Correo Comprador")
    identificador_extranjero = fields.Char(
        string="Identificador Extranjero",
        help="Para tipos 45, 46, 47"
    )

    # ========================================================================
    # Datos del Comprobante
    # ========================================================================
    fecha_emision = fields.Date(
        string="Fecha de Emisión",
        default=fields.Date.context_today
    )
    tipo_ingreso = fields.Selection([
        ('01', '01 - Ingresos por Operaciones'),
        ('02', '02 - Ingresos Financieros'),
        ('03', '03 - Ingresos Extraordinarios'),
        ('04', '04 - Ingresos por Arrendamiento'),
        ('05', '05 - Ingresos Venta Activos'),
        ('06', '06 - Otros Ingresos'),
    ], string="Tipo de Ingresos", default='01')

    tipo_pago = fields.Selection([
        ('1', '1 - Contado'),
        ('2', '2 - Crédito'),
        ('3', '3 - Gratuito'),
    ], string="Tipo de Pago", default='1')

    moneda = fields.Char(string="Moneda", default="DOP")

    # Formas de Pago
    forma_pago_1 = fields.Selection([
        ('1', '1 - Efectivo'),
        ('2', '2 - Cheque/Transferencia'),
        ('3', '3 - Tarjeta Débito/Crédito'),
        ('4', '4 - Venta a Crédito'),
        ('5', '5 - Bonos o Certificados'),
        ('6', '6 - Permuta'),
        ('7', '7 - Nota de Crédito'),
        ('8', '8 - Otras Formas'),
    ], string="Forma de Pago", default='1')
    monto_pago_1 = fields.Float(string="Monto Pago", digits=(16, 2))

    # ========================================================================
    # Items / Líneas
    # ========================================================================
    item_ids = fields.One2many(
        "ecf.simulation.document.item",
        "document_id",
        string="Items / Líneas"
    )

    # ========================================================================
    # Totales (calculados)
    # ========================================================================
    monto_gravado_total = fields.Float(
        string="Monto Gravado Total",
        compute="_compute_totales",
        store=True,
        digits=(16, 2)
    )
    monto_gravado_i1 = fields.Float(
        string="Monto Gravado 18%",
        compute="_compute_totales",
        store=True,
        digits=(16, 2)
    )
    monto_gravado_i2 = fields.Float(
        string="Monto Gravado 16%",
        compute="_compute_totales",
        store=True,
        digits=(16, 2)
    )
    monto_gravado_i3 = fields.Float(
        string="Monto Gravado 0%",
        compute="_compute_totales",
        store=True,
        digits=(16, 2)
    )
    monto_exento = fields.Float(
        string="Monto Exento",
        compute="_compute_totales",
        store=True,
        digits=(16, 2)
    )
    total_itbis = fields.Float(
        string="Total ITBIS",
        compute="_compute_totales",
        store=True,
        digits=(16, 2)
    )
    total_itbis1 = fields.Float(
        string="ITBIS 18%",
        compute="_compute_totales",
        store=True,
        digits=(16, 2)
    )
    total_itbis2 = fields.Float(
        string="ITBIS 16%",
        compute="_compute_totales",
        store=True,
        digits=(16, 2)
    )
    total_itbis3 = fields.Float(
        string="ITBIS 0%",
        compute="_compute_totales",
        store=True,
        digits=(16, 2)
    )
    monto_total = fields.Float(
        string="Monto Total",
        compute="_compute_totales",
        store=True,
        digits=(16, 2)
    )

    # ========================================================================
    # Para NC/ND (tipos 33, 34)
    # ========================================================================
    ncf_modificado = fields.Char(
        string="eNCF Modificado",
        help="eNCF del documento que se modifica"
    )
    fecha_ncf_modificado = fields.Date(string="Fecha NCF Modificado")
    codigo_modificacion = fields.Selection([
        ('01', '01 - Anulación'),
        ('02', '02 - Corrección'),
        ('03', '03 - Devolución'),
        ('04', '04 - Descuento'),
        ('05', '05 - Bonificación'),
    ], string="Código Modificación")
    indicador_nota_credito = fields.Selection([
        ('1', '1 - Anula NCF'),
        ('2', '2 - Corrige NCF'),
    ], string="Indicador NC", default='1')

    # ========================================================================
    # Campos para Retenciones (tipos 41, 47)
    # ========================================================================
    total_itbis_retenido = fields.Float(string="Total ITBIS Retenido", digits=(16, 2))
    total_isr_retencion = fields.Float(string="Total ISR Retenido", digits=(16, 2))

    # ========================================================================
    # Campos para Transporte (tipos 32>=250k, 44, 45, 46, 47)
    # ========================================================================
    conductor = fields.Char(string="Conductor")
    documento_transporte = fields.Char(string="Documento Transporte")
    placa = fields.Char(string="Placa")
    ruta_transporte = fields.Char(string="Ruta Transporte")
    pais_destino = fields.Char(string="País Destino", help="Para tipo 47")
    pais_origen = fields.Char(string="País Origen", help="Para exportaciones")

    # ========================================================================
    # Campos para Otra Moneda (tipo 45)
    # ========================================================================
    tipo_moneda_otra = fields.Char(string="Tipo Moneda Otra", default="USD")
    tipo_cambio = fields.Float(string="Tipo de Cambio", digits=(16, 4))
    monto_total_otra_moneda = fields.Float(string="Monto Total Otra Moneda", digits=(16, 2))

    # ========================================================================
    # Proveedor de API
    # ========================================================================
    api_provider_id = fields.Many2one(
        "ecf.api.provider",
        string="Proveedor API",
        domain=[('active', '=', True)],
        help="Seleccione el proveedor de API para enviar el documento. "
             "Si no selecciona ninguno, se usará el proveedor por defecto."
    )

    # ========================================================================
    # JSON y Resultado
    # ========================================================================
    json_preview = fields.Text(
        string="JSON Preview",
        help="Vista previa del JSON que se enviará"
    )
    api_response = fields.Text(
        string="Respuesta API (JSON)"
    )
    api_response_raw = fields.Text(
        string="Respuesta API Completa",
        help="Respuesta completa sin procesar de la API"
    )
    signed_xml = fields.Text(
        string="XML Firmado",
        help="XML firmado devuelto por la API (si aplica)"
    )
    signed_xml_filename = fields.Char(
        string="Nombre archivo XML",
        compute="_compute_signed_xml_filename"
    )
    track_id = fields.Char(string="Track ID")
    qr_url = fields.Char(string="URL QR")
    security_code = fields.Char(string="Código Seguridad")
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('json_ready', 'JSON Listo'),
        ('sent', 'Enviado'),
        ('accepted', 'Aceptado'),
        ('rejected', 'Rechazado'),
        ('error', 'Error'),
    ], string="Estado", default='draft')
    error_message = fields.Text(string="Mensaje de Error")

    # Caso creado
    created_case_id = fields.Many2one(
        "ecf.test.case",
        string="Caso Creado"
    )

    # ========================================================================
    # Campos Computados Auxiliares
    # ========================================================================
    show_nc_nd_fields = fields.Boolean(
        compute="_compute_show_fields",
        string="Mostrar campos NC/ND"
    )
    show_extranjero_fields = fields.Boolean(
        compute="_compute_show_fields",
        string="Mostrar campos Extranjero"
    )
    show_retencion_fields = fields.Boolean(
        compute="_compute_show_fields",
        string="Mostrar campos Retención"
    )
    show_transporte_fields = fields.Boolean(
        compute="_compute_show_fields",
        string="Mostrar campos Transporte"
    )
    show_otra_moneda_fields = fields.Boolean(
        compute="_compute_show_fields",
        string="Mostrar campos Otra Moneda"
    )

    # ========================================================================
    # Métodos Computados
    # ========================================================================

    @api.depends('tipo_ecf')
    def _compute_show_fields(self):
        for doc in self:
            tipo = doc.tipo_ecf
            doc.show_nc_nd_fields = tipo in ('33', '34')
            doc.show_extranjero_fields = tipo in ('45', '46', '47')
            doc.show_retencion_fields = tipo in ('41', '47')
            doc.show_transporte_fields = tipo in ('44', '45', '46', '47')
            doc.show_otra_moneda_fields = tipo == '45'

    @api.depends('signed_xml')
    def _compute_signed_xml_filename(self):
        for doc in self:
            if doc.signed_xml:
                encf = doc._get_encf() if hasattr(doc, '_get_encf') else 'documento'
                doc.signed_xml_filename = f"{encf}_firmado.xml"
            else:
                doc.signed_xml_filename = False

    @api.depends('tipo_ecf', 'encf_sequence_counter')
    def _compute_encf_generated(self):
        for doc in self:
            if doc.tipo_ecf:
                doc.encf_generated = f"E{doc.tipo_ecf}{doc.encf_sequence_counter:010d}"
            else:
                doc.encf_generated = ""

    @api.depends('item_ids', 'item_ids.monto_item', 'item_ids.itbis_item', 'item_ids.indicador_facturacion')
    def _compute_totales(self):
        for doc in self:
            gravado_total = 0.0
            gravado_i1 = 0.0
            gravado_i2 = 0.0
            gravado_i3 = 0.0
            exento = 0.0
            itbis_total = 0.0
            itbis1 = 0.0
            itbis2 = 0.0
            itbis3 = 0.0

            for item in doc.item_ids:
                if item.indicador_facturacion == '1':
                    gravado_i1 += item.monto_item
                    itbis1 += item.itbis_item
                elif item.indicador_facturacion == '2':
                    gravado_i2 += item.monto_item
                    itbis2 += item.itbis_item
                elif item.indicador_facturacion == '3':
                    gravado_i3 += item.monto_item
                elif item.indicador_facturacion == '5':
                    gravado_i1 += item.monto_item
                    itbis1 += item.itbis_item
                elif item.indicador_facturacion == '4':
                    exento += item.monto_item

            gravado_total = gravado_i1 + gravado_i2 + gravado_i3
            itbis_total = itbis1 + itbis2 + itbis3

            doc.monto_gravado_total = gravado_total
            doc.monto_gravado_i1 = gravado_i1
            doc.monto_gravado_i2 = gravado_i2
            doc.monto_gravado_i3 = gravado_i3
            doc.monto_exento = exento
            doc.total_itbis = itbis_total
            doc.total_itbis1 = itbis1
            doc.total_itbis2 = itbis2
            doc.total_itbis3 = itbis3
            doc.monto_total = gravado_total + exento + itbis_total

    # ========================================================================
    # Métodos de Modelo
    # ========================================================================

    @api.model
    def default_get(self, fields_list):
        """Carga datos del emisor desde la compañía al abrir el formulario"""
        defaults = super().default_get(fields_list)
        company = self.env.company
        ICP = self.env['ir.config_parameter'].sudo()
        last_seq = int(ICP.get_param('l10n_do_e_cf_tests.simulation_sequence', '0'))

        # Datos del emisor desde la compañía
        if 'rnc_emisor' in fields_list and not defaults.get('rnc_emisor'):
            # Limpiar el VAT (quitar prefijo DO si existe)
            vat = company.vat or ''
            if vat.upper().startswith('DO'):
                vat = vat[2:]
            defaults['rnc_emisor'] = vat

        if 'razon_social_emisor' in fields_list and not defaults.get('razon_social_emisor'):
            defaults['razon_social_emisor'] = company.name or ''

        if 'nombre_comercial' in fields_list and not defaults.get('nombre_comercial'):
            defaults['nombre_comercial'] = company.name or ''

        if 'direccion_emisor' in fields_list and not defaults.get('direccion_emisor'):
            # Construir dirección completa
            parts = [company.street or '', company.street2 or '']
            defaults['direccion_emisor'] = ', '.join(filter(None, parts)) or ''

        if 'telefono_emisor' in fields_list and not defaults.get('telefono_emisor'):
            defaults['telefono_emisor'] = company.phone or ''

        if 'correo_emisor' in fields_list and not defaults.get('correo_emisor'):
            defaults['correo_emisor'] = company.email or ''

        if 'website_emisor' in fields_list and not defaults.get('website_emisor'):
            defaults['website_emisor'] = company.website or ''

        if 'encf_sequence_counter' in fields_list and not defaults.get('encf_sequence_counter'):
            defaults['encf_sequence_counter'] = last_seq + 1

        # Municipio y Provincia desde los campos de la compañía si existen
        if 'municipio_emisor' in fields_list and not defaults.get('municipio_emisor'):
            # Intentar obtener de campos personalizados o usar default
            municipio = getattr(company, 'l10n_do_municipality_code', None) or '010100'
            defaults['municipio_emisor'] = municipio

        if 'provincia_emisor' in fields_list and not defaults.get('provincia_emisor'):
            provincia = getattr(company, 'l10n_do_province_code', None) or '010000'
            defaults['provincia_emisor'] = provincia

        return defaults

    @api.model_create_multi
    def create(self, vals_list):
        """Asegura que se incremente la secuencia al crear"""
        ICP = self.env['ir.config_parameter'].sudo()

        for vals in vals_list:
            if not vals.get('encf_sequence_counter'):
                last_seq = int(ICP.get_param('l10n_do_e_cf_tests.simulation_sequence', '0'))
                vals['encf_sequence_counter'] = last_seq + 1

        return super().create(vals_list)

    @api.onchange('tipo_ecf')
    def _onchange_tipo_ecf(self):
        """Actualiza nombre del caso cuando cambia el tipo"""
        if self.tipo_ecf:
            tipo_names = dict(self._fields['tipo_ecf'].selection)
            self.name = f"Simulación {tipo_names.get(self.tipo_ecf, self.tipo_ecf)} - {datetime.now().strftime('%H%M%S')}"

    @api.onchange('monto_total')
    def _onchange_monto_total(self):
        """Actualiza monto de pago cuando cambia el total"""
        if self.monto_total:
            self.monto_pago_1 = self.monto_total

    # ========================================================================
    # Generación de eNCF
    # ========================================================================

    def _get_encf(self):
        """Retorna el eNCF según el modo seleccionado"""
        self.ensure_one()
        if self.encf_mode == 'manual':
            if not self.encf_manual:
                raise UserError(_("Debe ingresar el eNCF en modo manual."))
            return self.encf_manual
        else:
            return self.encf_generated

    def _increment_sequence(self):
        """Incrementa el contador de secuencia y lo guarda"""
        ICP = self.env['ir.config_parameter'].sudo()
        current = int(ICP.get_param('l10n_do_e_cf_tests.simulation_sequence', '0'))
        ICP.set_param('l10n_do_e_cf_tests.simulation_sequence', str(current + 1))

    # ========================================================================
    # Construcción del Row para ecf_builder
    # ========================================================================

    def _format_telefono(self, telefono):
        """Formatea telefono al formato DGII: XXX-XXX-XXXX"""
        if not telefono:
            return ''
        # Eliminar todo excepto digitos
        digits = ''.join(c for c in telefono if c.isdigit())
        # Si tiene 10 digitos, formatear como XXX-XXX-XXXX
        if len(digits) == 10:
            return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
        # Si tiene 11 digitos y empieza con 1, formatear como X-XXX-XXX-XXXX
        elif len(digits) == 11 and digits[0] == '1':
            return f"{digits[0]}-{digits[1:4]}-{digits[4:7]}-{digits[7:]}"
        # Devolver como esta si ya tiene guiones o formato diferente
        return telefono

    def _format_decimal(self, value, decimals=2):
        """Formatea un valor numerico con decimales fijos"""
        if value is None:
            return None
        return f"{float(value):.{decimals}f}"

    def _build_excel_row_raw(self):
        """
        Construye un diccionario compatible con ecf_builder.build_ecf_json()
        IMPORTANTE: El formato debe ser EXACTAMENTE igual al que produce el Excel import
        para que el builder genere JSON válidos aceptados por DGII.
        """
        self.ensure_one()

        encf = self._get_encf()
        fecha_emision_str = self.fecha_emision.strftime('%d-%m-%Y') if self.fecha_emision else datetime.now().strftime('%d-%m-%Y')
        fecha_venc_str = self.fecha_vencimiento_secuencia.strftime('%d-%m-%Y') if self.fecha_vencimiento_secuencia else '31-12-2025'

        # Determinar IndicadorMontoGravado según ejemplos válidos DGII:
        # 0 = Montos incluyen ITBIS (tipos 32, 41)
        # 1 = Montos NO incluyen ITBIS (tipos 31, 33, 34, 44, 45, 46, 47)
        # Tipo 43: NO tiene IndicadorMontoGravado
        indicador_monto_gravado = '1'
        if self.tipo_ecf in ('32', '41'):
            indicador_monto_gravado = '0'

        row = {
            'Version': '1.0',
            'TipoeCF': self.tipo_ecf,
            'eNCF': encf,
            'ENCF': encf,
            'FechaVencimientoSecuencia': fecha_venc_str,
        }

        # IndicadorMontoGravado - NO para tipo 43
        if self.tipo_ecf != '43':
            row['IndicadorMontoGravado'] = indicador_monto_gravado

        # TipoIngresos y TipoPago - NO para tipos 41, 43
        if self.tipo_ecf not in ('41', '43'):
            row['TipoIngresos'] = self.tipo_ingreso or '01'
        if self.tipo_ecf != '43':
            row['TipoPago'] = self.tipo_pago or '1'

        # Emisor - campos que siempre van
        row['RNCEmisor'] = self.rnc_emisor or ''
        row['RazonSocialEmisor'] = self.razon_social_emisor or ''
        if self.nombre_comercial:
            row['NombreComercial'] = self.nombre_comercial
        row['DireccionEmisor'] = self.direccion_emisor or ''
        row['Municipio'] = self.municipio_emisor or '010100'
        row['Provincia'] = self.provincia_emisor or '010000'
        if self.correo_emisor:
            row['CorreoEmisor'] = self.correo_emisor
        if self.website_emisor:
            row['WebSite'] = self.website_emisor
        row['FechaEmision'] = fecha_emision_str

        # Comprador - NO para tipo 43 (Gastos Menores)
        if self.tipo_ecf != '43':
            if self.receptor_rnc:
                row['RNCComprador'] = self.receptor_rnc
            if self.receptor_nombre:
                row['RazonSocialComprador'] = self.receptor_nombre
            if self.receptor_correo:
                row['CorreoComprador'] = self.receptor_correo
            if self.receptor_direccion:
                row['DireccionComprador'] = self.receptor_direccion
            if self.receptor_municipio:
                row['MunicipioComprador'] = self.receptor_municipio
            if self.receptor_provincia:
                row['ProvinciaComprador'] = self.receptor_provincia

        # Telefono con formato DGII (XXX-XXX-XXXX)
        if self.telefono_emisor:
            row['TelefonoEmisor[1]'] = self._format_telefono(self.telefono_emisor)

        # TablaFormasPago según los ejemplos válidos DGII:
        # - Tipo 32 con monto >= 250,000 (con Transporte)
        # - Tipo 33 (Nota Débito)
        # - Tipo 41 (Compras) - SIEMPRE incluye TablaFormasPago
        # - NO para tipo 31, 34, 43, 44, 45, 46, 47 básicos
        incluir_formas_pago = False
        if self.tipo_ecf in ('33', '41'):
            incluir_formas_pago = True
        elif self.tipo_ecf == '32' and self.monto_total >= 250000:
            incluir_formas_pago = True

        if incluir_formas_pago and self.forma_pago_1:
            row['FormaPago[1]'] = self.forma_pago_1
            # Para tipo 41, el monto de pago es el total menos las retenciones
            if self.tipo_ecf == '41':
                monto_pago = (self.monto_total or 0) - (self.total_itbis_retenido or 0) - (self.total_isr_retencion or 0)
                row['MontoPago[1]'] = self._format_decimal(monto_pago if monto_pago > 0 else self.monto_total)
            else:
                row['MontoPago[1]'] = self._format_decimal(self.monto_pago_1 or self.monto_total)

        if self.tipo_ecf == '34':
            row['IndicadorNotaCredito'] = self.indicador_nota_credito or '1'

        if self.identificador_extranjero:
            row['IdentificadorExtranjero'] = self.identificador_extranjero

        # Items - IMPORTANTE: Usar el formato EXACTO del Excel DGII
        for idx, item in enumerate(self.item_ids.sorted(key=lambda r: r.sequence), start=1):
            # NumeroLinea como string (el builder usa to_int())
            row[f'NumeroLinea[{idx}]'] = str(idx)
            row[f'NombreItem[{idx}]'] = item.nombre_item or f'Item {idx}'
            if item.descripcion_item:
                row[f'DescripcionItem[{idx}]'] = item.descripcion_item

            # CantidadItem como string decimal (el Excel lo lee así)
            row[f'CantidadItem[{idx}]'] = self._format_decimal(item.cantidad_item or 1)

            # UnidadMedida debe ser codigo numerico DGII como string (ej: "43", "23", "55")
            unidad = str(item.unidad_medida or '43').strip()
            if not unidad.isdigit():
                # Mapeo común de texto a código
                unidad_map = {
                    'unidad': '43', 'und': '43', 'u': '43',
                    'servicio': '55', 'serv': '55', 's': '55',
                    'kilogramo': '23', 'kg': '23',
                    'litro': '47', 'lt': '47', 'l': '47',
                    'libra': '31', 'lb': '31',
                }
                unidad = unidad_map.get(unidad.lower(), '43')
            row[f'UnidadMedida[{idx}]'] = unidad

            # Precios y montos como string decimal
            row[f'PrecioUnitarioItem[{idx}]'] = self._format_decimal(item.precio_unitario_item or 0)
            row[f'MontoItem[{idx}]'] = self._format_decimal(item.monto_item or 0)

            # Indicadores como string (el builder usa to_int())
            row[f'IndicadorFacturacion[{idx}]'] = str(item.indicador_facturacion or '1')
            row[f'IndicadorBienoServicio[{idx}]'] = str(item.indicador_bien_servicio or '2')

            # NOTA: ItbisItem NO se incluye según ejemplos válidos DGII
            # El ITBIS se calcula en Totales, no por item

            # Descuento
            if item.descuento_monto:
                row[f'DescuentoMonto[{idx}]'] = self._format_decimal(item.descuento_monto)

            # Retenciones (tipos 41, 47)
            if item.indicador_agente_retencion:
                row[f'IndicadorAgenteRetencionoPercepcion[{idx}]'] = str(item.indicador_agente_retencion)
            if item.monto_itbis_retenido:
                row[f'MontoITBISRetenido[{idx}]'] = self._format_decimal(item.monto_itbis_retenido)
            if item.monto_isr_retenido:
                row[f'MontoISRRetenido[{idx}]'] = self._format_decimal(item.monto_isr_retenido)

        # Totales - usar formato con 2 decimales como string
        if self.monto_gravado_total:
            row['MontoGravadoTotal'] = self._format_decimal(self.monto_gravado_total)
        if self.monto_gravado_i1:
            row['MontoGravadoI1'] = self._format_decimal(self.monto_gravado_i1)
            row['ITBIS1'] = '18'  # Tasa ITBIS 18%
        if self.monto_gravado_i2:
            row['MontoGravadoI2'] = self._format_decimal(self.monto_gravado_i2)
            row['ITBIS2'] = '16'  # Tasa ITBIS 16%
        if self.monto_gravado_i3:
            row['MontoGravadoI3'] = self._format_decimal(self.monto_gravado_i3)
            row['ITBIS3'] = '0'  # Tasa ITBIS 0%
        if self.monto_exento:
            row['MontoExento'] = self._format_decimal(self.monto_exento)
        if self.total_itbis:
            row['TotalITBIS'] = self._format_decimal(self.total_itbis)
        if self.total_itbis1:
            row['TotalITBIS1'] = self._format_decimal(self.total_itbis1)
        if self.total_itbis2:
            row['TotalITBIS2'] = self._format_decimal(self.total_itbis2)
        if self.total_itbis3:
            row['TotalITBIS3'] = self._format_decimal(self.total_itbis3)

        row['MontoTotal'] = self._format_decimal(self.monto_total)
        row['ValorPagar'] = self._format_decimal(self.monto_total)

        # NC/ND (tipos 33, 34)
        if self.tipo_ecf in ('33', '34'):
            if self.ncf_modificado:
                row['NCFModificado'] = self.ncf_modificado
            if self.fecha_ncf_modificado:
                row['FechaNCFModificado'] = self.fecha_ncf_modificado.strftime('%d-%m-%Y')
            if self.codigo_modificacion:
                row['CodigoModificacion'] = self.codigo_modificacion

        # Retenciones totales (tipos 41, 47)
        if self.total_itbis_retenido:
            row['TotalITBISRetenido'] = self._format_decimal(self.total_itbis_retenido)
        if self.total_isr_retencion:
            row['TotalISRRetencion'] = self._format_decimal(self.total_isr_retencion)

        # Transporte (tipo 32 >= 250k, tipos 44, 45, 46, 47)
        if self.conductor:
            row['Conductor'] = self.conductor
        if self.documento_transporte:
            row['DocumentoTransporte'] = self.documento_transporte
        if self.placa:
            row['Placa'] = self.placa
        if self.ruta_transporte:
            row['RutaTransporte'] = self.ruta_transporte
        if self.pais_destino:
            row['PaisDestino'] = self.pais_destino
        if self.pais_origen:
            row['PaisOrigen'] = self.pais_origen

        # Otra Moneda (tipo 45)
        if self.tipo_ecf == '45' and self.tipo_moneda_otra:
            row['TipoMoneda'] = self.tipo_moneda_otra
            if self.tipo_cambio:
                row['TipoCambio'] = self._format_decimal(self.tipo_cambio, 4)
            if self.monto_total_otra_moneda:
                row['MontoTotalOtraMoneda'] = self._format_decimal(self.monto_total_otra_moneda)

        row['FechaHoraFirma'] = datetime.now().strftime('%d-%m-%Y %H:%M:%S')

        return row

    # ========================================================================
    # Acciones
    # ========================================================================

    def action_generate_json(self):
        """Genera el JSON y lo muestra en preview"""
        self.ensure_one()

        if not self.item_ids:
            raise UserError(_("Debe agregar al menos un item/línea."))

        from odoo.addons.l10n_do_e_cf_tests.models import ecf_builder

        try:
            row = self._build_excel_row_raw()
            ecf_json = ecf_builder.build_ecf_json(row)
            json_formatted = json.dumps(ecf_json, indent=2, ensure_ascii=False)

            self.write({
                'json_preview': json_formatted,
                'state': 'json_ready',
                'error_message': False,
            })

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('JSON Generado'),
                    'message': _('El JSON ha sido generado correctamente.'),
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
                }
            }

        except Exception as e:
            self.write({
                'error_message': str(e),
                'state': 'error',
            })
            raise UserError(_("Error al generar JSON: %s") % str(e))

    def action_generate_and_send(self):
        """Genera el JSON y lo envía a la API seleccionada"""
        self.ensure_one()

        if self.state != 'json_ready':
            self.action_generate_json()

        if not self.json_preview:
            raise UserError(_("No hay JSON para enviar. Primero genere el JSON."))

        # Obtener el proveedor de API
        _logger.info(f"[Simulador] api_provider_id en documento: {self.api_provider_id}")

        if self.api_provider_id:
            provider = self.api_provider_id
            _logger.info(f"[Simulador] Usando proveedor seleccionado: {provider.name}")
        else:
            provider = self.env['ecf.api.provider'].get_default_provider()
            _logger.info(f"[Simulador] Usando proveedor por defecto: {provider.name if provider else 'NINGUNO'}")

        if not provider:
            # Fallback a la configuración legacy de MSeller
            _logger.info(f"[Simulador] No hay proveedor, usando legacy MSeller")
            return self._send_via_legacy_mseller()

        try:
            doc = json.loads(self.json_preview)
        except json.JSONDecodeError as e:
            raise UserError(_("El JSON no es válido: %s") % str(e))

        _logger.info(f"[Simulador] ===== ENVIANDO via proveedor: {provider.name} ({provider.provider_type}) =====")

        # Enviar usando el proveedor (ahora devuelve 6 valores y registra en log)
        success, resp_data, track_id, error_msg, raw_response, signed_xml = provider.send_ecf(
            doc,
            rnc=self.rnc_emisor,
            encf=self._get_encf(),
            origin='simulation',
            simulation_doc_id=self.id
        )

        # Procesar respuesta
        resp_text = json.dumps(resp_data, indent=2, ensure_ascii=False) if resp_data else error_msg

        if success:
            if self.encf_mode == 'auto':
                self._increment_sequence()

            # Extraer datos adicionales de la respuesta
            qr_url = None
            security_code = None
            if isinstance(resp_data, dict):
                qr_url = self._find_in_response(resp_data, ['qrUrl', 'qr_url', 'QrUrl', 'qr', 'QR'])
                security_code = self._find_in_response(resp_data, ['codigoSeguridad', 'securityCode', 'codigo_seguridad'])

            self.write({
                'api_response': resp_text,
                'api_response_raw': raw_response,
                'signed_xml': signed_xml,
                'track_id': track_id,
                'qr_url': qr_url,
                'security_code': security_code,
                'error_message': False,
                'state': 'accepted',
            })

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Enviado Exitosamente'),
                    'message': _('Documento aceptado via %s. Track ID: %s') % (provider.name, track_id or 'N/A'),
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
                }
            }
        else:
            self.write({
                'api_response': resp_text,
                'api_response_raw': raw_response,
                'signed_xml': signed_xml,
                'track_id': track_id,
                'error_message': error_msg or "Error desconocido",
                'state': 'rejected',
            })

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Documento Rechazado'),
                    'message': _('Error via %s: %s') % (provider.name, error_msg or 'Ver respuesta'),
                    'type': 'warning',
                    'sticky': True,
                    'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
                }
            }

    def _send_via_legacy_mseller(self):
        """Fallback: Envía usando la configuración legacy de MSeller"""
        ICP = self.env['ir.config_parameter'].sudo()
        use_mseller = ICP.get_param('l10n_do_e_cf_tests.use_mseller', 'True') == 'True'

        if not use_mseller:
            raise UserError(_(
                "No hay proveedor de API configurado.\n"
                "Configure un proveedor en e-CF Tests > Proveedores de API,\n"
                "o habilite MSeller en Ajustes > e-CF Tests."
            ))

        host = ICP.get_param('l10n_do_e_cf_tests.mseller_host', 'https://ecf.api.mseller.app')
        env = ICP.get_param('l10n_do_e_cf_tests.mseller_env', 'TesteCF')
        email = ICP.get_param('l10n_do_e_cf_tests.mseller_email')
        password = ICP.get_param('l10n_do_e_cf_tests.mseller_password')
        api_key = ICP.get_param('l10n_do_e_cf_tests.mseller_api_key')
        timeout = int(ICP.get_param('l10n_do_e_cf_tests.mseller_timeout', '60'))

        if not all([email, password, api_key]):
            raise UserError(_("Faltan credenciales de MSeller. Configure en Ajustes > e-CF Tests."))

        try:
            doc = json.loads(self.json_preview)
        except json.JSONDecodeError as e:
            raise UserError(_("El JSON no es válido: %s") % str(e))

        try:
            # Login
            login_url = f"{host.rstrip('/')}/{env}/customer/authentication"
            login_resp = requests.post(
                login_url,
                json={"email": email, "password": password},
                timeout=timeout
            )

            if login_resp.status_code >= 400:
                error_msg = f"Error de login MSeller ({login_resp.status_code}): {login_resp.text[:500]}"
                self.write({
                    'api_response': error_msg,
                    'error_message': error_msg,
                    'state': 'error',
                })
                raise UserError(error_msg)

            login_data = login_resp.json()
            token = login_data.get("idToken") or login_data.get("token") or login_data.get("accessToken")

            if not token:
                error_msg = f"No se obtuvo token de MSeller: {json.dumps(login_data, ensure_ascii=False)[:500]}"
                self.write({
                    'api_response': error_msg,
                    'error_message': error_msg,
                    'state': 'error',
                })
                raise UserError(error_msg)

            # Enviar documento
            send_url = f"{host.rstrip('/')}/{env}/documentos-ecf"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "X-API-KEY": api_key,
            }

            send_resp = requests.post(
                send_url,
                headers=headers,
                json=doc,
                timeout=timeout
            )

            try:
                resp_data = send_resp.json()
                resp_text = json.dumps(resp_data, indent=2, ensure_ascii=False)
            except Exception:
                resp_data = {}
                resp_text = send_resp.text

            track_id = None
            qr_url = None
            security_code = None

            if isinstance(resp_data, dict):
                track_id = self._find_in_response(resp_data, ['trackId', 'TrackId', 'track_id'])
                qr_url = self._find_in_response(resp_data, ['qrUrl', 'qr_url', 'QrUrl', 'qr', 'QR'])
                security_code = self._find_in_response(resp_data, ['codigoSeguridad', 'securityCode', 'codigo_seguridad'])

            status_code = send_resp.status_code

            if 200 <= status_code < 300:
                if self.encf_mode == 'auto':
                    self._increment_sequence()

                self.write({
                    'api_response': resp_text,
                    'track_id': track_id,
                    'qr_url': qr_url,
                    'security_code': security_code,
                    'error_message': False,
                    'state': 'accepted',
                })

                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Enviado Exitosamente'),
                        'message': _('El documento fue aceptado. Track ID: %s') % (track_id or 'N/A'),
                        'type': 'success',
                        'sticky': False,
                        'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
                    }
                }
            else:
                self.write({
                    'api_response': resp_text,
                    'track_id': track_id,
                    'error_message': f"Error API ({status_code})",
                    'state': 'rejected',
                })

                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Documento Rechazado'),
                        'message': _('El documento fue rechazado. Revise la respuesta.'),
                        'type': 'warning',
                        'sticky': True,
                        'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
                    }
                }

        except requests.exceptions.Timeout:
            error_msg = f"Timeout después de {timeout} segundos"
            self.write({
                'api_response': error_msg,
                'error_message': error_msg,
                'state': 'error',
            })
            raise UserError(error_msg)

        except requests.exceptions.ConnectionError as e:
            error_msg = f"Error de conexión: {str(e)}"
            self.write({
                'api_response': error_msg,
                'error_message': error_msg,
                'state': 'error',
            })
            raise UserError(error_msg)

    def _find_in_response(self, data, keys):
        """Busca un valor en un dict usando múltiples nombres de clave posibles"""
        if not isinstance(data, dict):
            return None
        for key in keys:
            if key in data:
                return data[key]
        for subkey in ['data', 'result', 'response', 'documento']:
            if subkey in data and isinstance(data[subkey], dict):
                result = self._find_in_response(data[subkey], keys)
                if result:
                    return result
        return None

    def action_create_case(self):
        """Crea un ecf.test.case con los datos del documento"""
        self.ensure_one()

        if not self.json_preview:
            self.action_generate_json()

        if not self.test_set_id:
            test_set = self.env['ecf.test.set'].create({
                'name': f'Simulaciones {datetime.now().strftime("%Y-%m-%d")}',
                'description': 'Set creado automáticamente para simulaciones',
            })
        else:
            test_set = self.test_set_id

        try:
            doc = json.loads(self.json_preview)
            hash_input = hashlib.sha256(
                json.dumps(doc, sort_keys=True, ensure_ascii=False).encode('utf-8')
            ).hexdigest()
        except Exception:
            hash_input = ''

        state = 'draft'
        api_status = 'pending'
        if self.state == 'json_ready':
            state = 'payload_ready'
        elif self.state == 'accepted':
            state = 'accepted'
            api_status = 'accepted'
        elif self.state == 'rejected':
            state = 'rejected'
            api_status = 'rejected'
        elif self.state == 'sent':
            state = 'sent'
            api_status = 'sent'

        case_vals = {
            'test_set_id': test_set.id,
            'name': self.name,
            'tipo_ecf': self.tipo_ecf,
            'receptor_rnc': self.receptor_rnc,
            'receptor_nombre': self.receptor_nombre,
            'identificador_extranjero': self.identificador_extranjero,
            'fecha_comprobante': self.fecha_emision,
            'moneda': self.moneda,
            'tipo_ingreso': self.tipo_ingreso,
            'tipo_pago': self.tipo_pago,
            'monto_gravado_total': self.monto_gravado_total,
            'monto_gravado_i1': self.monto_gravado_i1,
            'monto_gravado_i2': self.monto_gravado_i2,
            'monto_gravado_i3': self.monto_gravado_i3,
            'monto_exento': self.monto_exento,
            'total_itbis': self.total_itbis,
            'total_itbis1': self.total_itbis1,
            'total_itbis2': self.total_itbis2,
            'total_itbis3': self.total_itbis3,
            'monto_total': self.monto_total,
            'monto_total_pagar': self.monto_total,
            'ncf_modificado': self.ncf_modificado,
            'razon_modificacion': self.codigo_modificacion,
            'cantidad_items': len(self.item_ids),
            'descripcion_item': self.item_ids[0].nombre_item if self.item_ids else '',
            'precio_unitario': self.item_ids[0].precio_unitario_item if self.item_ids else 0,
            'payload_json': self.json_preview,
            'hash_input': hash_input,
            'id_lote': str(uuid.uuid4()),
            'state': state,
            'api_status': api_status,
            'api_response': self.api_response,
            'track_id': self.track_id,
            'qr_url': self.qr_url,
            'security_code': self.security_code,
            'error_message': self.error_message,
        }

        case = self.env['ecf.test.case'].create(case_vals)
        self.created_case_id = case.id

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'ecf.test.case',
            'res_id': case.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_load_template(self):
        """Carga plantilla de datos según el tipo de e-CF seleccionado"""
        self.ensure_one()

        if not self.tipo_ecf:
            raise UserError(_("Seleccione primero el tipo de e-CF."))

        template_data = self._get_template_data(self.tipo_ecf)

        # Eliminar items existentes
        self.item_ids.unlink()

        # Actualizar campos del documento
        update_vals = {}
        for key, value in template_data.items():
            if key != 'items' and hasattr(self, key):
                update_vals[key] = value

        self.write(update_vals)

        # Crear items
        for item_data in template_data.get('items', []):
            self.env['ecf.simulation.document.item'].create({
                'document_id': self.id,
                **item_data
            })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Plantilla Cargada'),
                'message': _('Se cargaron los datos de ejemplo para tipo %s') % self.tipo_ecf,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }

    def _get_template_data(self, tipo_ecf):
        """Retorna datos de plantilla segun el tipo de e-CF"""
        # Datos base del comprador de prueba DGII
        comprador_base = {
            'receptor_rnc': '131880681',
            'receptor_nombre': 'DOCUMENTOS ELECTRONICOS DE 03',
            'receptor_direccion': 'CALLE JACINTO DE LA CONCHA FELIZ ESQUINA 27 DE FEBRERO',
            'receptor_municipio': '010100',
            'receptor_provincia': '010000',
            'receptor_correo': 'prueba@ejemplo.com',
        }

        templates = {
            '31': {
                **comprador_base,
                'tipo_ingreso': '01',
                'tipo_pago': '1',
                'items': [{
                    'nombre_item': 'Servicio de consultoria empresarial',
                    'cantidad_item': 1.0,
                    'precio_unitario_item': 10000.00,
                    'indicador_facturacion': '1',
                    'indicador_bien_servicio': '2',
                    'unidad_medida': '43',
                }]
            },
            '32': {
                'receptor_rnc': '131880681',
                'receptor_nombre': 'DOCUMENTOS ELECTRONICOS DE 03',
                'receptor_direccion': 'AVE. ISABEL AGUIAR NO. 269',
                'receptor_municipio': '010100',
                'receptor_provincia': '010000',
                'receptor_correo': 'prueba@ejemplo.com',
                'tipo_ingreso': '01',
                'tipo_pago': '1',
                'items': [{
                    'nombre_item': 'Producto de consumo general',
                    'cantidad_item': 2.0,
                    'precio_unitario_item': 250.00,
                    'indicador_facturacion': '1',
                    'indicador_bien_servicio': '1',
                    'unidad_medida': '23',
                }]
            },
            '33': {
                **comprador_base,
                'tipo_ingreso': '01',
                'tipo_pago': '1',
                'ncf_modificado': 'E320000000006',
                'fecha_ncf_modificado': '01-04-2020',
                'codigo_modificacion': '03',
                'items': [{
                    'nombre_item': 'Ajuste por diferencia de precio',
                    'cantidad_item': 1.0,
                    'precio_unitario_item': 500.00,
                    'indicador_facturacion': '4',
                    'indicador_bien_servicio': '2',
                    'unidad_medida': '43',
                }]
            },
            '34': {
                **comprador_base,
                'tipo_ingreso': '01',
                'tipo_pago': '1',
                'ncf_modificado': 'E310000000001',
                'codigo_modificacion': '03',
                'indicador_nota_credito': '1',
                'items': [{
                    'nombre_item': 'Devolucion de mercancia',
                    'cantidad_item': 1.0,
                    'precio_unitario_item': 1000.00,
                    'indicador_facturacion': '4',
                    'indicador_bien_servicio': '1',
                    'unidad_medida': '43',
                }]
            },
            '41': {
                **comprador_base,
                'tipo_pago': '1',
                'forma_pago_1': '1',  # Efectivo
                'total_itbis_retenido': 1800.00,
                'total_isr_retencion': 1000.00,
                'items': [{
                    'nombre_item': 'SERVICIO PUBLICIDAD',
                    'descripcion_item': 'Servicios de publicidad y marketing',
                    'cantidad_item': 1.0,
                    'precio_unitario_item': 10000.00,
                    'indicador_facturacion': '1',
                    'indicador_bien_servicio': '2',
                    'unidad_medida': '43',
                    'indicador_agente_retencion': '1',
                    'monto_itbis_retenido': 1800.00,
                    'monto_isr_retenido': 1000.00,
                }]
            },
            '43': {
                # Tipo 43 (Gastos Menores) NO tiene comprador ni TipoIngresos/TipoPago
                'receptor_rnc': '',
                'receptor_nombre': '',
                'items': [{
                    'nombre_item': 'Arreglo neumaticos',
                    'cantidad_item': 1.0,
                    'precio_unitario_item': 350.00,
                    'indicador_facturacion': '4',  # Exento
                    'indicador_bien_servicio': '2',  # Servicio
                    'unidad_medida': '43',
                }]
            },
            '44': {
                **comprador_base,
                'tipo_ingreso': '01',
                'tipo_pago': '1',
                'items': [{
                    'nombre_item': 'Venta a regimen especial',
                    'cantidad_item': 1.0,
                    'precio_unitario_item': 15000.00,
                    'indicador_facturacion': '4',
                    'indicador_bien_servicio': '1',
                    'unidad_medida': '43',
                }]
            },
            '45': {
                **comprador_base,
                'tipo_ingreso': '01',
                'tipo_pago': '2',
                'tipo_moneda_otra': 'USD',
                'tipo_cambio': 58.50,
                'items': [{
                    'nombre_item': 'Servicio al gobierno',
                    'cantidad_item': 1.0,
                    'precio_unitario_item': 50000.00,
                    'indicador_facturacion': '4',
                    'indicador_bien_servicio': '2',
                    'unidad_medida': '43',
                }]
            },
            '46': {
                'identificador_extranjero': 'US-123456789',
                'receptor_nombre': 'FOREIGN CLIENT INC',
                'tipo_ingreso': '01',
                'tipo_pago': '1',
                'pais_destino': 'US',
                'items': [{
                    'nombre_item': 'Producto de exportacion',
                    'cantidad_item': 100.0,
                    'precio_unitario_item': 25.00,
                    'indicador_facturacion': '4',
                    'indicador_bien_servicio': '1',
                    'unidad_medida': '43',
                }]
            },
            '47': {
                'identificador_extranjero': 'EU-987654321',
                'receptor_nombre': 'EUROPEAN SERVICES LTD',
                'tipo_ingreso': '01',
                'tipo_pago': '1',
                'pais_destino': 'ES',
                'total_isr_retencion': 500.00,
                'items': [{
                    'nombre_item': 'Pago por servicios al exterior',
                    'cantidad_item': 1.0,
                    'precio_unitario_item': 5000.00,
                    'indicador_facturacion': '4',
                    'indicador_bien_servicio': '2',
                    'unidad_medida': '43',
                    'monto_isr_retenido': 500.00,
                }]
            },
        }

        return templates.get(tipo_ecf, templates['31'])

    def action_print_invoice(self):
        """Genera la representación impresa del documento"""
        self.ensure_one()

        if not self.created_case_id:
            result = self.action_create_case()
            if self.created_case_id:
                return self.created_case_id.action_print_invoice()
            else:
                raise UserError(_("No se pudo crear el caso para imprimir."))

        return self.created_case_id.action_print_invoice()

    def action_reset_to_draft(self):
        """Resetea el documento a estado borrador"""
        self.ensure_one()
        self.write({
            'state': 'draft',
            'json_preview': False,
            'api_response': False,
            'api_response_raw': False,
            'signed_xml': False,
            'track_id': False,
            'qr_url': False,
            'security_code': False,
            'error_message': False,
        })

    def action_download_signed_xml(self):
        """Descarga el XML firmado como archivo"""
        self.ensure_one()
        if not self.signed_xml:
            raise UserError(_("No hay XML firmado disponible para descargar."))

        import base64
        encf = self._get_encf()
        filename = f"{encf}_firmado.xml"
        xml_content = self.signed_xml.encode('utf-8')
        b64_content = base64.b64encode(xml_content).decode('utf-8')

        # Crear attachment temporal
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': b64_content,
            'mimetype': 'application/xml',
            'res_model': self._name,
            'res_id': self.id,
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'new',
        }

    def action_copy_signed_xml(self):
        """Muestra notificación indicando que se puede copiar el XML del campo"""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Copiar XML'),
                'message': _('Seleccione el contenido del campo XML Firmado y use Ctrl+C para copiar.'),
                'type': 'info',
                'sticky': False,
            }
        }
