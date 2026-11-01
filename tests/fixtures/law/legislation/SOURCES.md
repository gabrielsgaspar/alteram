# Sources for the legislation.gov.uk fixtures

© Crown and database right. Derived from content available under the Open Government Licence v3.0 from legislation.gov.uk.

Files are CLML (`data.xml`) responses saved unmodified. Fetched by Gabriel on 2026-11-01 with the `curl` commands in `tasks/M3-01-foundations.md`, using a descriptive User-Agent. Used by the M3 pipeline tests (CLML parser, validity spans, chunker). Do not edit them: change the hash and the entry here if a file is ever re-fetched.

| File | URL | Fetched | sha256 | Purpose |
| --- | --- | --- | --- | --- |
| `ukpga-2015-15-section-9@2015-10-01.xml` | https://www.legislation.gov.uk/ukpga/2015/15/section/9/2015-10-01/data.xml | 2026-11-01 | `2383355edcab22365f56bb6b2957607b7253fec68e7399815bdc0e8aadd609b6` | Consumer Rights Act 2015 s.9: plain subsections (P1, P2 and P3 levels). |
| `ukpga-2015-15-section-22@2015-10-01.xml` | https://www.legislation.gov.uk/ukpga/2015/15/section/22/2015-10-01/data.xml | 2026-11-01 | `f0b57fa204a1fbecc64448161fa8dfd2ec7632ae2fc81fd4a8c94e185863baf8` | Consumer Rights Act 2015 s.22: a long section with many subsections. |
| `ukpga-2015-15-section-12@current.xml` | https://www.legislation.gov.uk/ukpga/2015/15/section/12/data.xml | 2026-11-01 | `a63f3acd6b9884221d28518bdf0f3c39ab289e980eaf4c40e546e36813c1c70e` | Consumer Rights Act 2015 s.12, current: carries the unapplied Digital Markets, Competition and Consumers Act 2024 effect. |
| `ukpga-1974-39-section-88@current.xml` | https://www.legislation.gov.uk/ukpga/1974/39/section/88/data.xml | 2026-11-01 | `9e18df3b976457f442edccde3ad2717ac75b01677769aa41e072d6fc7792f39c` | Consumer Credit Act 1974 s.88, current: carries the `hasVersion` list (enacted, 1991-02-01, 2006-06-16, 2006-10-01, 2008-10-01 on 1 Nov 2026). |
| `ukpga-1974-39-section-88@2006-06-16.xml` | https://www.legislation.gov.uk/ukpga/1974/39/section/88/2006-06-16/data.xml | 2026-11-01 | `f5ca8acce1b52346b44226e4f02a686419071019fac24cb38773c449c3f5d4e2` | Consumer Credit Act 1974 s.88, first of three adjacent dated versions. |
| `ukpga-1974-39-section-88@2006-10-01.xml` | https://www.legislation.gov.uk/ukpga/1974/39/section/88/2006-10-01/data.xml | 2026-11-01 | `638f2cccb5f26da58046d5b374f06434988d90390ae16c707f579894c63dbda8` | Consumer Credit Act 1974 s.88, second adjacent version: changed text. |
| `ukpga-1974-39-section-88@2008-10-01.xml` | https://www.legislation.gov.uk/ukpga/1974/39/section/88/2008-10-01/data.xml | 2026-11-01 | `62c6f087a1b13397d72efcff886c3a423eb119fe2e643a16d2085ee84ce48a66` | Consumer Credit Act 1974 s.88, third adjacent version: new subsection. |
| `ukpga-1974-39-section-140A@1990-01-01.xml` | https://www.legislation.gov.uk/ukpga/1974/39/section/140A/1990-01-01/data.xml | 2026-11-01 | `14064e5532990bfd2aec55ae7fccf14ba52351693964774723ead302fb43d224` | Consumer Credit Act 1974 s.140A, requested at 1990-01-01: the base-date case, with `Match="false"` parts. |

## The three dated versions of CCA 1974 s.88

The `hasVersion` list in `ukpga-1974-39-section-88@current.xml` runs enacted, 1991-02-01, 2006-06-16, 2006-10-01, 2008-10-01, so the three dated files are adjacent versions. Between 2006-06-16 and 2006-10-01, words in s.88(2) and (3) were substituted ("seven days" became "14 days", effective 1 October 2006), which covers "changed text". Between 2006-10-01 and 2008-10-01, s.88(4A) (the default information sheet) was inserted, effective 1 October 2008, which covers "new subsection". CCA s.75 is no longer in the library (decision D4).
