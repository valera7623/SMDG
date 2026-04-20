# DICOM Viewer

> **Translation status:** English stub. The authoritative version is
> [`docs/locales/ru/DICOM_VIEWER.md`](../locales/ru/DICOM_VIEWER.md).

## Overview

SMDG bundles a server-side DICOM renderer plus an OHIF-style web viewer.
The viewer is enabled when `dicom_viewer_enabled=true` in settings (the
`russia`, `intl`, `single` and `saas` deployment profiles all enable it
by default — see [FEATURES.md](FEATURES.md)).

## Capabilities

- Server rendering: `pydicom` + `numpy` + `PIL` → PNG.
- Multi-frame CT/MRI with a `Cine` playback mode.
- Window/Level presets: **Bone**, **Lung**, **Brain**, **Abdomen**,
  **Liver** plus a custom slider.
- Measurements: ruler, angle, rectangular ROI and elliptical ROI.
- Annotations exported as PNG or a full screenshot.
- Zoom, pan, invert, reset controls.
- DICOMweb: QIDO-RS (query) and WADO-RS (retrieve).
- Redis cache for metadata and rendered PNG frames.
- Keyboard shortcuts (localised via the i18n runtime).

## URLs

- `/dicom-viewer` — SMDG viewer.
- `/ohif-viewer` — OHIF-style viewer wrapping SMDG's DICOMweb endpoints.
- `/qido-rs/studies` — QIDO-RS query.
- `/wado-rs/studies/{studyUID}/series/{seriesUID}/instances/{instanceUID}` —
  WADO-RS retrieve.

## Workflow

1. Upload a DICOM file via `/api/upload`.
2. Metadata is extracted and persisted.
3. The client opens `/dicom-viewer?file=<id>` or the OHIF viewer.
4. The server streams PNG frames on demand; the client draws
   measurements over the canvas.
5. The user exports an annotated PNG if needed.

## Localisation

All UI strings in the viewer use the shared `window.I18N` runtime and
`static/locales/<lang>.js`. Presets and tool names use the namespaces
`dicom.*` (see the translation files).

Refer to the Russian source document for the full feature matrix and
screenshots.
