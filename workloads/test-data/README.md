# Genuine demo photos

Owner: Nikhil. `demo-manifest.json` pins ten photographic samples, their source
URLs, published SHA-256 values, subjects, label expectations and license notes.
Sources are pinned to scikit-image v0.25.2:
[checksum registry](https://github.com/scikit-image/scikit-image/blob/v0.25.2/skimage/data/_registry.py)
and [data descriptions](https://github.com/scikit-image/scikit-image/blob/v0.25.2/skimage/data/_fetchers.py).
Keep these provenance notes when sharing the dataset.

From the repository root:

```powershell
.\.venv-local\Scripts\python.exe workloads\test-data\setup_sample_data.py
.\.venv-local\Scripts\python.exe workloads\test-data\setup_sample_data.py --verify-only
.\.venv-local\Scripts\python.exe workloads\test-data\evaluate_demo.py
```

Install the worker and inference requirements first (see `worker/README.md`).
The default output directory is `demo/`. The setup verifies both cached and
downloaded bytes: checksum, decoding, bounded size/dimensions, non-solid pixels.
Failed downloads return nonzero; there are no generated fallback photos.
`--verify-only` makes no network requests. `--output` chooses a different directory.

The evaluator invokes the actual native ONNX script, checks all ten output
identities and writes `output/workloads/phase1/result.json` and `evaluation.json`.
Only five manifest entries have explicit compatible ImageNet label expectations;
the remaining five are excluded from label scoring. Review confidence and wrong
labels honestly. This small curated sanity check is not representative accuracy,
speedup, energy or production-quality evidence. The model returns one class per
image, not detected objects or bounding boxes.

Upload these ten files through the dashboard with chunk size 5 for the next
browser/physical-worker milestone. Accepted outputs use the server-prefixed
names such as `00000_astronaut.png`, not the originals.

The existing `sample/` files are synthetic unit-test fixtures. They must not be
used as real classification or accuracy evidence. The tiny synthetic worker
preflight image checks runtime health only. Tests mock network failures rather
than contacting external sources:

```powershell
.\.venv-local\Scripts\python.exe -m unittest discover -s workloads\tests -v
```
