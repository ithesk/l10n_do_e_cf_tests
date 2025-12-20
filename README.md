# Dominican Republic e-CF Certification Tests

[![Odoo Version](https://img.shields.io/badge/Odoo-19.0-blue.svg)](https://www.odoo.com)
[![License: LGPL-3](https://img.shields.io/badge/License-LGPL--3-green.svg)](https://www.gnu.org/licenses/lgpl-3.0)

## Overview

Complete test suite for DGII (Dirección General de Impuestos Internos) electronic invoice certification in the Dominican Republic. This module allows you to run the official DGII certification tests and manage e-CF (Comprobante Fiscal Electrónico) documents.

**[Versión en Español](#spanish-version)**

## Features

- **Import DGII Test Files**: Load official Excel test files from DGII
- **All e-CF Types Supported**: 31, 32, 33, 34, 41, 43, 44, 45, 46, 47
- **RFCE Support**: Automatic handling of Resumen Factura Consumo Electrónica for invoices < 250,000 DOP
- **Multiple API Providers**: MSeller, Local/Custom API integration
- **Signed XML Storage**: Store both RFCE and full ECF signed XMLs
- **QR Code Generation**: Automatic QR with DGII validation URL
- **PDF Invoice Reports**: Print invoices with QR codes
- **Document Simulation**: Test document generation before sending
- **Complete Logging**: Full API transaction history

## Supported e-CF Types

| Code | Type | Description |
|------|------|-------------|
| 31 | B01 | Factura de Crédito Fiscal Electrónica |
| 32 | B02 | Factura de Consumo Electrónica |
| 33 | B03 | Nota de Débito Electrónica |
| 34 | B04 | Nota de Crédito Electrónica |
| 41 | B11 | Comprobante de Regímenes Especiales |
| 43 | B13 | Comprobante de Exportaciones |
| 44 | B14 | Comprobante de Compras |
| 45 | B15 | Comprobante de Gastos Menores |
| 46 | B16 | Comprobante de Pagos al Exterior |
| 47 | B17 | Comprobante Gubernamental |

## Requirements

- Odoo 19.0
- `l10n_do_e_cf_core` module
- Python packages:
  ```bash
  pip install openpyxl requests qrcode
  ```

## Installation

1. Clone this repository to your Odoo addons folder:
   ```bash
   git clone https://github.com/your-repo/l10n_do_e_cf_tests.git
   ```

2. Install Python dependencies:
   ```bash
   pip install openpyxl requests qrcode
   ```

3. Update Odoo app list and install the module

## Configuration

### API Provider Setup

1. Go to **e-CF Tests > Configuration > API Providers**
2. Create or configure a provider:

#### For MSeller API:
- **Provider Type**: MSeller
- **Environment**: TesteCF / CerteCF / eCF
- **Credentials**: Email, Password, API Key

#### For Local/Custom API:
- **Provider Type**: Local API
- **Base URL**: Your API endpoint (e.g., `http://your-api.com/api/invoice/send`)
- **Summary URL**: For RFCE documents (e.g., `/api/invoice/send-summary-with-ecf`)
- **Authentication**: API Key or Bearer Token

### RFCE Configuration (Consumo < 250k)

For consumption invoices (type 32) under 250,000 DOP, the module automatically:
1. Detects the document type and amount
2. Sends to the summary endpoint
3. Stores both RFCE XML (sent to DGII) and full ECF XML (for records)

## Usage

### Importing Test Sets

1. Go to **e-CF Tests > Import Test Set**
2. Upload the official DGII Excel file
3. Name your test set
4. Choose whether to send immediately or just import

### Sending by Type (Recommended)

1. Open a Test Set
2. Click **"Send by Type"**
3. Select document type to send
4. Documents are sent in DGII-required order

### Document Simulation

1. Go to **e-CF Tests > Document Simulator**
2. Create a new simulation document
3. Add items, configure totals
4. Generate JSON and send to API

### Viewing Logs

- Go to **e-CF Tests > Transaction Logs**
- View request/response details
- Download signed XMLs
- Open DGII validation URL

## Module Structure

```
l10n_do_e_cf_tests/
├── __manifest__.py
├── README.md
├── models/
│   ├── ecf_api_provider.py      # API provider management
│   ├── ecf_api_log.py           # API transaction logging
│   ├── ecf_builder.py           # JSON e-CF construction
│   ├── ecf_test_case.py         # Individual test cases
│   ├── ecf_test_set.py          # Test set management
│   ├── ecf_simulation_document.py # Document simulator
│   └── res_config_settings.py   # Module settings
├── wizards/
│   ├── run_test_set_wizard.py   # Import and run tests
│   ├── send_ecf_by_type_wizard.py # Send by document type
│   └── generate_volume_test_wizard.py # Volume testing
├── views/
│   └── *.xml                    # UI views
├── reports/
│   ├── ecf_invoice_report.xml
│   └── ecf_invoice_template.xml
├── security/
│   └── ir.model.access.csv
└── static/
    └── src/css/
```

## API Response Format

The module expects API responses in this format:

```json
{
  "success": true,
  "data": {
    "codigo": 1,
    "estado": "Aceptado",
    "encf": "E320000000001",
    "signedEcfXml": "<?xml...>",
    "signedRfceXml": "<?xml...>",
    "qrCodeUrl": "https://ecf.dgii.gov.do/...",
    "ecfSecurityCode": "ABC123"
  }
}
```

---

<a name="spanish-version"></a>
# Versión en Español

## Descripción

Suite completa de pruebas para la certificación de facturación electrónica (e-CF) de la DGII en República Dominicana.

## Características

- **Importar archivos de prueba DGII**: Carga archivos Excel oficiales
- **Todos los tipos e-CF**: 31, 32, 33, 34, 41, 43, 44, 45, 46, 47
- **Soporte RFCE**: Manejo automático para facturas de consumo < 250,000 DOP
- **Múltiples proveedores API**: MSeller, API Local/Personalizada
- **Almacenamiento XML firmado**: Guarda XMLs RFCE y ECF
- **Generación de QR**: QR automático con URL de validación DGII
- **Reportes PDF**: Impresión de facturas con códigos QR
- **Simulador de documentos**: Prueba documentos antes de enviar
- **Logs completos**: Historial de transacciones API

## Instalación

1. Clonar el repositorio en la carpeta de addons de Odoo
2. Instalar dependencias Python:
   ```bash
   pip install openpyxl requests qrcode
   ```
3. Actualizar lista de aplicaciones e instalar el módulo

## Configuración

### Proveedor de API

1. Ir a **e-CF Tests > Configuración > Proveedores de API**
2. Configurar el proveedor (MSeller o API Local)
3. Guardar credenciales y URLs

### Para facturas de consumo < 250k (RFCE)

Configure el endpoint combinado que devuelve ambos XMLs:
- URL Resumen: `/api/invoice/send-summary-with-ecf`

## Uso

### Importar Set de Pruebas

1. Ir a **e-CF Tests > Importar Set de Pruebas**
2. Cargar archivo Excel de la DGII
3. Nombrar el set de pruebas
4. Importar

### Enviar por Tipo

1. Abrir un Set de Pruebas
2. Click en **"Enviar por Tipo"**
3. Seleccionar tipo de documento
4. Los documentos se envían en el orden requerido por la DGII

## Licencia

LGPL-3

## Autor

- **ITHesk** - [https://www.ithesk.com](https://www.ithesk.com)

## Contribuciones

Las contribuciones son bienvenidas. Por favor, abre un issue o pull request.
