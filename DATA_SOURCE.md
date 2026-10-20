# Data source and inventory provenance

## Original research

Dumortier JG, Le Verge-Serandour M, Tortorelli AF, Mielke A, de Plater L, Turlier H, Maître JL.
_Hydraulic fracturing and active coarsening position the lumen of the mouse blastocyst_.
Science. 2019;365(6452):465–468.
DOI [10.1126/science.aaw7709](https://doi.org/10.1126/science.aaw7709).

[Publisher](https://www.science.org/doi/10.1126/science.aaw7709) · [Institut Curie publication record](https://institut-curie.org/publications/hydraulic-fracturing-and-active-coarsening-position-lumen-mouse-blastocyst) · [PubMed](https://pubmed.ncbi.nlm.nih.gov/31371608/).

The original research and data are credited to these authors, including [Jean-Léon Maître and the Mechanics of Mammalian Development team at Institut Curie](https://institut-curie.org/team/maitre).
This repository supplies independent download software, not new biological measurements or an official mirror.

## Original data location

<https://ressources.curie.fr/frackening/>

The reference inventory contains eight top-level figure-related directories.
Their names are retained exactly as observed.

```text
Fig 1-4 - S3-4-5/
Fig 2 - S7-11/
Fig 2 - S8/
Fig 4 - S8/
Fig S1/
Fig S10/
Fig S2/
Fig S6/
```

Observed workbook names include `MicrolumenCurvature.xlsx`, `MicrolumenGrowthDynamics.xlsx`, `Cdh1GFPDistributionEmbryoLevel.xlsx`, `Cdh1Heterogeneity.xlsx`, `mCdh1Chimeras.xlsx`, `mMyh9Chimeras.xlsx`, `ApicoBasalMarkers.xlsx`, `CellCurvature.xlsx`, `CellVolume.xlsx` and `Tension.xlsx`.
These names describe the repository organisation.
They are not a substitute for reading the original methods or the files themselves.
The reference preparation inspected filenames and metadata, not workbook contents or image dimensions.

## Reference snapshot

The bundled `reference_inventory.json` was derived from the maintainer-supplied `inventory.csv`, `pages.csv`, `outside_scope.csv` and `scan_summary.json` produced by the original downloader.
The scan timestamp was **2026-10-20T11:05:39.165970+00:00**.

It records 801 distinct file URLs, 95 directory pages and 144,451,717,255 reported bytes.
Every listed file had a reported size.
The scan reported zero discovery errors and one excluded outside-prefix link, `https://ressources.curie.fr/`, the parent directory.

The JSON includes public source URLs, portable relative output names, content types, observed sizes, HTTP ETags and Last-Modified values.
It does not contain a machine-specific destination, username, authentication credential or personal transfer history.
Checksums of the supplied inventory CSV, page CSV and scan-summary JSON are retained as provenance identifiers, not as imaging-file checksums.

Original HTML snapshots were not supplied with the metadata used to prepare the distributable reference.
Consequently, the bundled page records have `html_sha256` set to `null`.
Their link sets were inferred from the complete observed directory hierarchy, including in-scope parent links.
Those inferred link counts were checked against all 95 page-list records.

On the first successful run, all known directory pages are read and compared against these link sets.
The resulting HTML fingerprints are saved in the user's own `_download_metadata/inventory_cache.json` for subsequent checks.
This first check establishes a baseline rather than proving that the original HTML text was unchanged since the scan.
The runtime does not overwrite the bundled reference file.

## Scope and limitations

The downloader handles ordinary, publicly accessible HTTP links beneath the source prefix.
It follows neither external-host links nor redirects outside that prefix.
It does not discover unlinked files, execute JavaScript, authenticate through a browser, query a specialist image API or validate that every experiment in the paper is represented.

The default scope includes every inventoried file type, including source-side `Thumbs.db` and a `.lnk` shortcut.
No archive, shortcut or other data file is executed by the downloader.
Files and directories are not automatically deleted to match changes at the server.

Page fingerprints, HTTP validators, byte counts and local SHA-256 checksums address different checks.
A page fingerprint concerns a listing, HTTP validators describe server-reported identity, and a locally calculated SHA-256 concerns the bytes received and later stored locally.
None is an independent author-supplied checksum of the original experimental data.

The GPL-3.0-only licence in this repository applies to the downloader software.
The reference inventory is a factual description of the observed source and does not relicense the original files.
A dataset-specific reuse licence could not be established from the supplied metadata.
Consult the data providers about applicable terms where necessary.
