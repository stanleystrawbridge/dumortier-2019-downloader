# Dumortier 2019 dataset downloader

Download the publicly linked imaging and associated data accompanying **Dumortier et al. (2019), _Hydraulic fracturing and active coarsening position the lumen of the mouse blastocyst_** from the original Institut Curie repository.

**Original data and research** — [Jean-Léon Maître and the Mechanics of Mammalian Development team, Institut Curie](https://institut-curie.org/team/maitre), with the co-authors of the [Science paper](https://www.science.org/doi/10.1126/science.aaw7709).
**Data source** — <https://ressources.curie.fr/frackening/>.

This is an independent downloader maintained by Stanley E. Strawbridge.
It is not an official Institut Curie application and does not imply endorsement by the original researchers.
The data are downloaded directly from Institut Curie, not hosted in this GitHub repository.

## Quick start

You need **Python 3.10 or newer**, an internet connection and a writable destination folder.
The recorded dataset is approximately **144.45 GB / 134.53 GiB**.
Allow at least **160 GB of free space** for a fresh download as a practical margin.
The script also checks the reported free space before transferring data.

Download this repository using **Code → Download ZIP**, then **extract the ZIP completely**.
Keep all the extracted files together.
No Git installation, GitHub account for a public repository, code editing or separate inventory command is needed.

### Windows

Double-click **`run_downloader.bat`** in the extracted folder.
Enter or paste the destination folder when asked, review the size and location, then type **`y`** to start.

The launcher creates an isolated `.venv` environment and installs the dependency on first use.
It does not modify an existing Anaconda environment.
Python must already be installed and discoverable through `py`, `python` or `python3`.
With Anaconda-only installations, open an Anaconda Prompt, navigate to the extracted folder, and run the following command instead.

```bat
run_downloader.bat
```

### macOS or Linux

Open Terminal in the extracted folder and run the following command.

```bash
bash run_downloader.sh
```

Enter or paste the destination folder, review the summary, then type **`y`** to start.
The launcher sets up the dependency in `.venv` on first use.

### What happens next

The downloader checks the small directory-listing pages, reuses the saved file inventory where possible, checks available space and asks for confirmation before downloading data.
Files are downloaded one at a time, with progress reports and short pauses between requests.

Keep the terminal open, the computer awake and the destination drive connected.
To continue after an interruption, run the same launcher and select **the same destination folder**.
Completed files recorded by the downloader are skipped when their metadata and local size agree.
Partially downloaded files resume when the server provides suitable validators and byte-range support, or restart safely when it does not.

**This version is a pre-release build.**
Automated local tests pass, but the revised package has not yet completed a full live-repository download or been executed on Windows/macOS during preparation.
See [TESTING.md](TESTING.md) for the precise validation status and the included cross-platform test workflow.

## What data are downloaded?

The study investigates the formation and positioning of the blastocoel during mouse preimplantation development.
It examines hydraulic fracturing of cell-cell contacts, the formation of microlumens and their coarsening into a dominant lumen.
See the [original paper](https://doi.org/10.1126/science.aaw7709) for experimental methods and interpretation.

The bundled inventory records a scan on **20 October 2026** with **801 file URLs across 95 HTML directory pages**, totalling **144,451,717,255 reported bytes**.
These are observed repository entries, not a claim that every underlying experiment or every file associated with the publication is available.

| Observed files | Number |
|---|---:|
| TIFF imaging files, including `.tif` and `.TIF` | 351 |
| Zeiss `.czi` imaging files | 3 |
| ZIP archives, many named or located as ROI data | 389 |
| Excel `.xlsx` workbooks | 10 |
| RTF supporting notes | 10 |
| Plain-text notes | 2 |
| `Thumbs.db` files | 35 |
| Windows shortcut `.lnk` file | 1 |

The directory names associate data with figures and supplementary figures.
The downloader preserves that hierarchy and includes all inventoried file types rather than restricting the download to images.
It does not interpret spreadsheet contents, determine biological replicate counts, convert images, reconstruct figure panels or extract archives.
Unsafe filename characters would be sanitised consistently, with the URL-to-path mapping retained in the inventory.

ZIP files and the shortcut are **saved but never automatically opened or executed**.
Do not open an unfamiliar shortcut simply because it was included in the dataset.

See [DATA_SOURCE.md](DATA_SOURCE.md) for the directory list, reference-inventory provenance and limitations.

## Inventory caching and updates

A fresh destination uses `reference_inventory.json`, supplied with this repository.
Subsequent runs prefer `_download_metadata/inventory_cache.json` in the selected destination.
Metadata from the earlier inventory-only script can also be imported automatically.

On a normal run, the downloader fetches **all known nested directory pages**, not just the homepage.
When their recorded links and available HTML fingerprints agree, it reuses the file metadata without sending a new header request for every file.
When a listing changes, it refreshes the inventory, including the per-file response headers.
A failed check stops the run rather than being treated as “no changes”.

**Initial reference limitation.**
The bundled reference was prepared from the supplied CSV inventory and page list, not the original HTML snapshots.
Its initial link sets were reconstructed from the observed directory hierarchy.
The first successful check compares those link sets and establishes local HTML fingerprints.
It cannot retrospectively prove that the original listing text or same-name remote files were unchanged before that first check.
Later runs compare the saved HTML fingerprints as well as the links.
An HTML-only presentation change may therefore trigger a conservative full refresh.

An unchanged listing is not proof that every remote file's content is unchanged.
The downloader checks available validators and sizes again when it actually transfers a file.
Use `--refresh-inventory` when an explicit recheck of all file headers is needed.
Even remote headers are not independent, author-supplied content checksums.

```bash
bash run_downloader.sh --refresh-inventory
```

```bat
run_downloader.bat --refresh-inventory
```

Files removed from the remote inventory are **not deleted locally**.
Changed remote versions that would conflict with existing completed files are reported, not silently overwritten.
Keep the old data and choose a new destination when downloading a changed version of the dataset.

## Python and advanced usage

The downloader itself is a **single Python script**.
The launchers are optional.
With a suitable Python environment, run these commands from the repository folder.

```bash
python -m pip install -r requirements.txt
python download_dumortier_2019.py
```

Use `python3` instead of `python` where appropriate.
The `requests` dependency is constrained in `requirements.txt` but the complete transitive environment is not locked.
Record `python --version` and `python -m pip freeze` alongside any reproducibility-critical run.
The launchers reuse their installed environment after initial setup rather than upgrading dependencies on every download.

| Option | Behaviour |
|---|---|
| `--destination "PATH"` | Supply a destination instead of the interactive folder prompt. |
| `--yes` | Skip the download confirmation. Requires an explicit `--destination`. |
| `--inventory-only` | Check or rebuild metadata without downloading data files. |
| `--refresh-inventory` | Force full discovery and inspection of file headers. |
| `--verify` | Recompute local SHA-256 checksums before skipping completed files. Still follows the normal download workflow. |
| `--use-cached-inventory` | Explicitly skip directory checks for this run. Requires an existing suitable inventory. Transfer-time header checks still apply. |
| `--download` | Backwards-compatible alias for the default download workflow. Confirmation is still required unless `--yes` is given. |
| `--source URL` | Advanced override for another static HTTP(S) directory. Not a guarantee of compatibility with other websites. |
| `--help` | Display the command-line help. |

For example, the following command uses a user-chosen relative folder and does not prompt for confirmation.
The path is illustrative, not a built-in destination.

```bash
python download_dumortier_2019.py --destination "./data" --yes
```

**Relative paths are relative to the current working directory.**
Both launchers change to the repository folder first.
An absolute destination path avoids ambiguity, particularly for external or shared drives.
There is no default destination, automatic drive selection or silent fallback to another drive.

## Verification and retained metadata

Keep `_download_metadata` together with the data.
It includes the inventory, page snapshots, transfer state, checksums and any error reports.

`checksums.csv` contains **locally calculated SHA-256 values**, not checksums supplied by the original authors.
Re-running with `--verify` checks completed files against those locally recorded values and can detect subsequent local changes.
It does not establish independently that the downloaded bytes match an original author-validated copy.
Without `--verify`, skipping completed files uses recorded identity/metadata and size, not a new full-file hash.

A run reports the number downloaded, skipped and failed.
A zero failure count applies only to the **inventoried, in-scope files**.
Unlinked resources, browser-only download APIs, authenticated material and external hosts are not discovered automatically.
Outside-prefix links are reported in `outside_scope.csv` rather than followed.
The original scan's single outside-prefix link was the parent resources directory.

## Troubleshooting

**The ZIP cannot run, or a file cannot be found.**
Extract the repository first.
Run the launcher from the extracted folder, keeping the Python script, requirements and reference inventory together.

**Python cannot be found.**
Install Python 3.10 or newer from [python.org](https://www.python.org/downloads/), following the instructions for your operating system, or use an existing Anaconda Prompt with a suitable Python version.
The launcher does not install Python itself.

**The environment cannot be created.**
Use a writable repository folder and a Python installation with `venv` support.
Some Linux distributions package `venv` separately.
See the [Python virtual environment documentation](https://docs.python.org/3/library/venv.html).
A moved or broken `.venv` can be removed and recreated by rerunning the launcher.
Remove only `.venv`, not the data or `_download_metadata`.

**A shared drive is unavailable or a path is too long.**
Connect/mount the drive first and use a valid path for that computer.
No data are redirected to another drive.
On Windows, prefer a short destination folder path to reduce nested-path issues.
Network quotas and filesystem restrictions may differ from reported free space.

**A connection or certificate check fails.**
Check network access, proxy configuration and institutional certificate requirements.
The program uses certificate verification and does not offer an insecure bypass.
Do not disable security protections to make the download run.
Retry after connectivity is restored.

**An existing file cannot be verified.**
The program will not silently adopt or replace an unrelated file, even if its filename or size matches.
Keep it and choose a new destination, or investigate the conflicting file before retrying.
A failed `--verify` check similarly leaves the file untouched.

**Another download may already be active.**
Do not run two copies against the same destination or modify its files during a transfer.
After an abrupt crash, a stale `_download_metadata/download.lock` may remain.
Remove that lock only after confirming that no downloader process is still using the destination.
Closing the terminal abruptly is not equivalent to a clean cancellation.

**The server reports changed file metadata.**
Run again with `--refresh-inventory`.
Existing files representing an older version are preserved and may require choosing a new destination.

## Citation, attribution and licence

For scientific use of these data, cite the original study.

> Dumortier, J. G., Le Verge-Serandour, M., Tortorelli, A. F., Mielke, A., de Plater, L., Turlier, H., and Maître, J.-L. (2019).
> Hydraulic fracturing and active coarsening position the lumen of the mouse blastocyst.
> _Science_ **365**(6452), 465–468.
> https://doi.org/10.1126/science.aaw7709

The [institutional publication record](https://institut-curie.org/publications/hydraulic-fracturing-and-active-coarsening-position-lumen-mouse-blastocyst), [PubMed record](https://pubmed.ncbi.nlm.nih.gov/31371608/) and [Jean-Léon Maître's team page](https://institut-curie.org/team/maitre) provide additional context.
`CITATION.cff` identifies the downloader separately and makes the original study the preferred scientific citation.

The downloader software is distributed under **GNU General Public License version 3 only**, identified as `GPL-3.0-only`.
The full text is in [LICENSE](LICENSE).
This software licence **does not grant or change rights in the original dataset, paper or third-party dependencies**.
No dataset-specific reuse licence was established from the supplied inventory metadata.
Consult the original providers' terms and seek clarification where needed before redistribution or other uses requiring permission.

For software problems, open an issue in this repository with the operating system, Python version, command and relevant error message.
Remove private paths or other sensitive local information from logs before posting.
Do not upload the imaging data, local environments or private download history to GitHub.
