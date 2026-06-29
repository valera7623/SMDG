# DICOM Viewer

View DICOM medical images in the browser.

## Overview

The DICOM Viewer renders studies **without client-side decryption**. The server decrypts DICOM, renders frames to PNG and streams them to the browser.

## Open a study

1. Upload a DICOM file via **Files → Upload**.
2. In the list click **View DICOM** (👁️ icon).
3. `dicom-viewer.html` opens with tools.

Alternative: **OHIF-style** viewer at `/ohif-viewer`.

## Tools

| Tool | Description |
|------|-------------|
| **Window/Level** | Presets Bone, Lung, Brain, Abdomen, Liver + manual slider |
| **Zoom / Pan** | Scale and pan |
| **Invert** | Colour inversion |
| **Cine** | Multi-frame CT/MRI playback |
| **Measurements** | Ruler, angle, ROI (rectangle / ellipse) |
| **Export** | PNG screenshot with annotations |

## DICOMweb

For PACS / external viewer integration:

| Standard | Endpoint |
|----------|----------|
| QIDO-RS | `/qido-rs/studies` |
| WADO-RS | `/wado-rs/studies/{studyUID}/series/{seriesUID}/instances/{instanceUID}` |

## Caching

Metadata and PNG frames are cached in **Redis** (~2.25 h TTL) for faster repeat viewing.

## Security

- Render access via **view_token** (short-lived) or JWT.
- All views are audited: `dicom.view_initiated`, `dicom.streamed`.

## API

See [API — DICOM](../api/dicom.md).

Extended reference: [src/DICOM_VIEWER.md](../src/DICOM_VIEWER.md).
