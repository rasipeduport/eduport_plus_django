# Report PDF assets

The files the report PDFs are drawn with (design F.2), kept with the reports
app so a PDF never depends on what fonts the server happens to have. This is
not a static directory: nothing here is served over HTTP. The PDF renderer
reads these files directly, and only these.

| File | Used for | Source |
| --- | --- | --- |
| `report.css` | The stylesheet both report templates share | Written for this app, after the two samples |
| `logo.png` | The Eduport Plus logo, top right (882 × 178 px) | The header image of the Demo report sample (`word/media/image2.png` in the .docx) |
| `fonts/Carlito-Regular.ttf`, `fonts/Carlito-Bold.ttf` | Body text and headings. Carlito has the letter widths of Calibri, the samples' font | [google/fonts](https://github.com/google/fonts/tree/6c1dbe27dcf7d817d4b62cec033ba77fa8e2a5ec/ofl/carlito) at `6c1dbe2`, `ofl/carlito/` |
| `fonts/Arimo-Bold.ttf` | The report titles. Arimo has the letter widths of Arial, the samples' title font | [googlefonts/Arimo](https://github.com/googlefonts/Arimo/tree/4a6255f269916ae7ad3fc2706b0935e7621396b8/fonts/ttf) at `4a6255f`, `fonts/ttf/` |

Both fonts are under the SIL Open Font License 1.1, which allows bundling them
with this software. Each licence sits beside its font (`fonts/Carlito-OFL.txt`,
`fonts/Arimo-OFL.txt`) and must stay with it.

SHA-256, as downloaded:

```
f6418f708baede9789daef5d458c0f53d2a888af9820e8062934e504fedc6595  fonts/Carlito-Regular.ttf
bb5d20f79b82599ec72983597437373a80f2d2085fa91fc144fd74e876a594db  fonts/Carlito-Bold.ttf
58402f82a7c332a700294988fe7554fbb0a63a8d27ccc1ee3bbc640311990a00  fonts/Carlito-OFL.txt
d7a8b187cf8444d4cfee102e8eae9e3043682fd5106d5d33ed677fe268a0e2ba  fonts/Arimo-Bold.ttf
c46fda6859efb80c0a3c1faa868908a3d2fcb26eb7fd9602d73bebeec21bca3a  fonts/Arimo-OFL.txt
84d9483fc34cd5b157cab73335aaf0f2ce6fd6783d1d298934c7c59ad1b5a7c9  logo.png
```
