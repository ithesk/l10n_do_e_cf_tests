{
    "name": "Dominican Republic e-CF Certification Tests",
    "version": "19.0.1.3.0",
    "summary": "DGII e-CF Certification Test Suite for Dominican Republic",
    "description": """
Dominican Republic e-CF Certification Tests
============================================

Complete test suite for DGII (Dirección General de Impuestos Internos)
electronic invoice certification in the Dominican Republic.

Features
--------
* Import DGII official Excel test files
* Automatic JSON e-CF generation following DGII specifications
* Support for all e-CF types (31, 32, 33, 34, 41, 43, 44, 45, 46, 47)
* MSeller API integration
* Custom/Local API integration
* RFCE (Resumen Factura Consumo Electrónica) support for invoices < 250k
* Signed XML storage and validation
* QR code generation with DGII validation URL
* PDF invoice report generation
* Complete API transaction logging
* Document simulation for testing

Supported e-CF Types
--------------------
* 31 - Factura de Crédito Fiscal Electrónica
* 32 - Factura de Consumo Electrónica (includes RFCE for < 250k)
* 33 - Nota de Débito Electrónica
* 34 - Nota de Crédito Electrónica
* 41 - Comprobante de Regímenes Especiales
* 43 - Comprobante de Exportaciones
* 44 - Comprobante de Compras
* 45 - Comprobante de Gastos Menores
* 46 - Comprobante de Pagos al Exterior
* 47 - Comprobante Gubernamental

Requirements
------------
* Python packages: openpyxl, requests, qrcode
* Odoo 19.0
* Odoo account module

Author: ITHesk
Website: https://www.ithesk.com
    """,
    "category": "Accounting/Localizations",
    "author": "ITHesk,",
    "website": "https://www.ithesk.com",
    "license": "LGPL-3",
    "depends": ["account", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "data/ecf_api_provider_data.xml",
        "reports/ecf_invoice_report.xml",
        "reports/ecf_invoice_template.xml",
        "views/res_config_settings_views.xml",
        "views/ecf_api_provider_views.xml",
        "views/ecf_api_log_views.xml",
        "views/ecf_test_case_views.xml",
        "views/ecf_test_rfce_case_views.xml",
        "views/ecf_test_set_views.xml",
        "views/e_cf_consumo_resumen_views.xml",
        "views/ecf_simulation_document_views.xml",
        "wizards/run_test_set_wizard_view.xml",
        "wizards/send_ecf_by_type_wizard_view.xml",
        "wizards/generate_volume_test_wizard_view.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "l10n_do_e_cf_tests/static/src/css/json_editor.css",
        ],
    },
    "external_dependencies": {
        "python": ["openpyxl", "requests", "qrcode"],
    },
    "images": ["static/description/banner.png"],
    "installable": True,
    "application": True,
    "auto_install": False,
}
