# Syllabus PDF assets

The files the syllabus "Plan & Price" PDFs are drawn with (sales.pdf), kept
with the sales app so a PDF never depends on what fonts the server happens to
have. This is not a static directory: nothing here is served over HTTP. The PDF
renderer reads these files directly, and only these.

The design follows the Eduport Plus reference PDFs (Figma exports): their
sizes and colours were measured from them, and the font identified as
Manrope by rendering it beside them.

| File | Used for | Source |
| --- | --- | --- |
| `syllabus.css` | The stylesheet of the PDF's template (`sales/templates/sales/pdf/`) | Written for this app, after the reference PDFs |
| `logo.png` | The Eduport Plus logo, top right of every page (882 × 178 px) | A copy of `reports/pdf_assets/logo.png` (same SHA-256) |
| `grid.svg` | The 22.4pt grid tile of the yellow border | Written for this app |
| `starburst.svg` | The red "Offer Price" badge | Written for this app |
| `check.svg` | The inclusions' green ticks | Written for this app |
| `fonts/Manrope-Regular.ttf`, `-Medium`, `-SemiBold`, `-Bold` | Every text of the PDF | [googlefonts/manrope](https://github.com/googlefonts/manrope/tree/468c0dbe38efa331b80bfe9448256abe27be44c3/fonts/ttf) at `468c0db`, `fonts/ttf/` |

Manrope is under the SIL Open Font License 1.1, which allows bundling it with
this software; its licence (`fonts/Manrope-OFL.txt`, from the same commit)
must stay with it. Manrope has no "↔": DejaVu, installed by the Dockerfile,
draws that one.

SHA-256, as downloaded:

```
d23d6eedf51dd495138aa1a83588027d4a63549cdfcc2fa5e0d8e84e09cf4cb1  fonts/Manrope-Regular.ttf
502ee33a6e140ad6ef10ef8b762a8e5cf01f33316f318800795725f4cfd539d9  fonts/Manrope-Medium.ttf
f43edb46a08e1538413ea2383ef01ed93cdab191a2c57d2489d9590985858cf7  fonts/Manrope-SemiBold.ttf
484d10f0683e9e9f588de978f70cd3ad17cb3522bc0ca6efc4491c83429d323c  fonts/Manrope-Bold.ttf
58172e0c0fac2cda8a37b348164bb55e44b0e69051e557e92b1d3f6910141f7b  fonts/Manrope-OFL.txt
84d9483fc34cd5b157cab73335aaf0f2ce6fd6783d1d298934c7c59ad1b5a7c9  logo.png
```
