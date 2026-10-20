# Testing and release status

## Checks performed for this package

Prepared on 20 October 2026.
The included suite passed **52 tests** on Linux with CPython **3.13.5** and Requests **2.32.5**.
The tests use a temporary local HTTP server and small synthetic payloads, not experimental images.
They make no requests to the Institut Curie repository.

The suite exercises full discovery, reference bootstrapping, nested-directory checks, changed and removed listings, forced refresh, failed-check preservation of the prior cache and migration of earlier CSV metadata.
It checks explicitly that unchanged listings do not cause per-file HTTP requests.

Transfer tests cover successful downloads, recorded checksums, skipping completed files, local checksum mismatch, byte-range resumption, servers that ignore ranges, interrupted connections, missing validators, malformed ranges, changed remote metadata, HTML substituted for data and completed-partial recovery.

Safety and interface tests cover unrelated existing files, partial ownership metadata, publication conflicts, path traversal, case-colliding filenames, manifest validation, symlink targets, quoted destinations with spaces, invalid destinations, active download locks, inventory-only operation and the default confirmation prompt.

The bundled reference passed validation with 801 files, 95 pages and 144,451,717,255 reported bytes.
Its inferred directory-link counts were also checked against the supplied page-list CSV.
Repository text was separately screened for the earlier machine-specific destinations and private setup details.
Those details are not included in the distributable files.

The Bash launcher passed a shell syntax check and an existing-environment help/exit-code smoke test from a different working directory, with spaces in the repository path.
That offline smoke test used an already available dependency environment and did not exercise a clean PyPI installation.
The Python command-line help and version output were also checked.

## What has not been validated here

The revised package has **not** completed an end-to-end download from the live Institut Curie repository.
The live repository could not be retrieved from the preparation environment.
The reference inventory comes from the earlier scan supplied by the maintainer.
A successful scan or an in-progress transfer with an earlier script is not validation of all revised behaviour.

The Windows batch launcher and native Windows/macOS filesystem behaviour have not been executed in the preparation environment.
Shared-drive disconnects, quotas, Windows long paths and full-scale transfer performance remain to be checked on the intended systems.
The rare exclusive-copy publication fallback on filesystems without hard-link support is not covered by the included transfer tests.
A hard process kill during that fallback can leave an incomplete final file and a retained complete partial, which will be reported as a conflict rather than silently overwritten.

The GitHub Actions workflow is supplied, **not a completed CI result**.
After upload, it is configured to run the local suite and launcher help checks on Linux, Windows and macOS, using Python 3.10 and 3.13.
It installs the declared dependency constraints but does not download the research dataset.
Workflow execution depends on the repository's Actions settings and available runner usage.

## Run the tests

From an environment containing the runtime dependency, run the following command in the repository root.

```bash
python -m unittest discover -s tests -v
```

No additional test framework is required.
On Windows, the symlink-creation test is skipped because privileges vary.

## Before a validated public release

Check the cross-platform workflow results after upload.
Run the revised package against the live source with a separate test destination or after any existing transfer has stopped.
Do not run two versions in the same destination concurrently.

Confirm that a complete download has no unresolved errors and agrees with the inventory.
Rerun in the same destination to check that completed files are skipped.
Use `--verify` to compare the completed files with the recorded local checksums.
Test an intentional clean interruption and resumption on the intended operating system.

Record the exact Python and installed package versions with the validation results.
The dependency constraints intentionally permit compatible Requests releases rather than providing a fully locked environment.
