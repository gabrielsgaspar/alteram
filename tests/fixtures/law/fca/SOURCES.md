# Sources for the FCA Handbook fixtures

Contains public sector information licensed under the Open Government Licence v3.0. Source: FCA Handbook, Financial Conduct Authority (handbook.fca.org.uk).

Downloaded under the FCA's written consent to automated download and private storage (docs/SETUP_LOG.md, 2026-11-04). Each `.html` file is the rendered HTML of one Handbook section page: the page's DOM after its rules appeared, saved unmodified by `scripts/fca_save.py` (headless Chromium via Playwright, run with `uv run --with playwright`). Claude Code ran the script from its sandbox on 2026-11-05, at Gabriel's request, with `ALTERAM_HTTP_CONTACT` in the User-Agent. Each `.json` file is the script's sidecar for the page: requested and final URL, page title, time saved, seconds until the rules appeared, the first rule header, the dates the page shows, and the sha256 of the `.html` file.

Used by the FCA parser tests (M3 step 19). Do not edit these files: change the hashes and the entry here if a page is ever saved again.

| File | URL | Saved (UTC) | sha256 of `.html` | sha256 of `.json` | Purpose |
| --- | --- | --- | --- | --- | --- |
| `DISP-2.8.html`, `DISP-2.8.json` | https://handbook.fca.org.uk/handbook/disp2/disp2s8 | 2026-11-05T19:16:26Z | `5831f3dd727c0c1a7201ebd38e088023e29508bb075c2233eb9cba6d39ceadf5` | `a3486e8162efdb9475c4e5f05b6d5c4ccad7e6606b50213e2fad4b8cb30ef825` | DISP 2.8 (time limits): 12 provisions (7 R, 5 G), sub-headings, and a `[deleted]` sub-paragraph in DISP 2.8.5R. Last updated 13/01/2018. |
| `CONC-7.3.html`, `CONC-7.3.json` | https://handbook.fca.org.uk/handbook/conc7/conc7s3 | 2026-11-05T19:16:29Z | `8f1c75bc694b2e75ed1ca313ad18e99766725a3ccea1413f263ed35e9ebb88bb` | `6cf1a876c7bf2898d8ab1bf072ab2e75e67ca8ce34a024bf44ff4ae40f41978d` | CONC 7.3 (arrears and default): 38 provisions (13 R, 25 G), including CONC 7.3.5 (G) next to CONC 7.3.5G (R). Last updated 26/06/2026. |
| `CONC-5.2A.html`, `CONC-5.2A.json` | https://handbook.fca.org.uk/handbook/conc5/conc5s6 | 2026-11-05T20:26:10Z | `2171aa09c04a3dff1bce77fc08b6be88d1a69ad21b398e2331d70bd52a587b04` | `c23899bdaba829e00f57e57626962f62bd72300eb402ff90453444c986497e6c` | CONC 5.2A (creditworthiness assessment), a lettered section: 37 provisions (20 R, 17 G). Last updated 04/11/2024. |

All three pages show "as of 05/11/2026".

## Notes

- Section slugs are the site's own IDs, not section numbers: `conc5/conc5s6` is CONC 5.2A. The script names each file from the section number the page shows, never from the slug.
- The pages are an Angular app's rendered DOM. The generated `_ngcontent-…` and `_nghost-…` attributes change with each site release, so a page saved again may differ byte for byte with no change to the rules.
- The date in each provision's header is taken to be the date the current version of that provision took effect. The pages do not say so.
