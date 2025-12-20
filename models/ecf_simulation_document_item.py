# -*- coding: utf-8 -*-

from odoo import api, fields, models


class EcfSimulationDocumentItem(models.Model):
    _name = "ecf.simulation.document.item"
    _description = "Línea de Item para Simulación e-CF"
    _order = "sequence, id"

    document_id = fields.Many2one(
        "ecf.simulation.document",
        string="Documento",
        required=True,
        ondelete="cascade"
    )
    sequence = fields.Integer(string="Secuencia", default=10)
    numero_linea = fields.Integer(string="# Línea", compute="_compute_numero_linea", store=True)

    # Datos del Item
    nombre_item = fields.Char(string="Nombre del Item", required=True)
    descripcion_item = fields.Char(string="Descripcion")
    cantidad_item = fields.Float(string="Cantidad", default=1.0, digits=(16, 2))
    unidad_medida = fields.Char(
        string="Unidad de Medida",
        default="43",
        help="Codigo DGII de unidad de medida. Ejemplos: 43=Unidad, 23=Kilogramo, 55=Servicio, 47=Litro, 31=Libra"
    )
    precio_unitario_item = fields.Float(string="Precio Unitario", digits=(16, 2))
    descuento_monto = fields.Float(string="Descuento", digits=(16, 2), default=0.0)

    # Indicadores DGII
    indicador_facturacion = fields.Selection([
        ('1', '1 - Gravado 18%'),
        ('2', '2 - Gravado 16%'),
        ('3', '3 - Gravado 0%'),
        ('4', '4 - Exento'),
        ('5', '5 - Gravado 13%'),
    ], string="Indicador Facturación", default='1')

    indicador_bien_servicio = fields.Selection([
        ('1', '1 - Bien'),
        ('2', '2 - Servicio'),
    ], string="Bien/Servicio", default='2')

    # Campos para tipos especiales (41, 47 - Retenciones)
    indicador_agente_retencion = fields.Selection([
        ('1', '1 - Agente de Retención'),
        ('2', '2 - Agente de Percepción'),
    ], string="Indicador Agente Ret/Perc")
    monto_itbis_retenido = fields.Float(string="ITBIS Retenido", digits=(16, 2))
    monto_isr_retenido = fields.Float(string="ISR Retenido", digits=(16, 2))

    # Campos calculados
    monto_item = fields.Float(
        string="Monto Item",
        compute="_compute_monto_item",
        store=True,
        digits=(16, 2)
    )
    itbis_item = fields.Float(
        string="ITBIS Item",
        compute="_compute_itbis_item",
        store=True,
        digits=(16, 2)
    )
    es_gravado = fields.Boolean(
        string="Gravado",
        compute="_compute_es_gravado",
        store=True
    )

    @api.depends('document_id.item_ids', 'document_id.item_ids.sequence')
    def _compute_numero_linea(self):
        for item in self:
            if item.document_id and item.document_id.item_ids:
                items_sorted = item.document_id.item_ids.sorted(key=lambda r: (r.sequence, r.id))
                for idx, it in enumerate(items_sorted, start=1):
                    if it.id == item.id:
                        item.numero_linea = idx
                        break
                else:
                    item.numero_linea = 1
            else:
                item.numero_linea = 1

    @api.depends('cantidad_item', 'precio_unitario_item', 'descuento_monto')
    def _compute_monto_item(self):
        for item in self:
            subtotal = item.cantidad_item * item.precio_unitario_item
            item.monto_item = subtotal - item.descuento_monto

    @api.depends('indicador_facturacion')
    def _compute_es_gravado(self):
        for item in self:
            item.es_gravado = item.indicador_facturacion != '4'

    @api.depends('monto_item', 'indicador_facturacion', 'descuento_monto')
    def _compute_itbis_item(self):
        for item in self:
            base_gravable = item.monto_item
            if item.indicador_facturacion == '1':
                item.itbis_item = round(base_gravable * 0.18, 2)
            elif item.indicador_facturacion == '2':
                item.itbis_item = round(base_gravable * 0.16, 2)
            elif item.indicador_facturacion == '5':
                item.itbis_item = round(base_gravable * 0.13, 2)
            else:
                item.itbis_item = 0.0
