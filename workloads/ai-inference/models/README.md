# Pinned inference artifacts

`mobilenetv2-12.onnx` is the CPU MobileNetV2 FP32 classifier;
`imagenet_labels.json` maps all 1000 classes. `artifact-manifest.json` records
their SHA-256 values. Label hashes normalize CRLF to LF so Windows and Linux
verify the same text. Model hashes are over exact bytes.

From the repository root:

```powershell
.\.venv-local\Scripts\python.exe workloads\ai-inference\download_model.py
```

The downloader verifies existing files too. Missing/changed/unavailable labels
or a model checksum mismatch cause a nonzero exit; it never claims success with
invented labels. Downloaded files are verified before atomic replacement.
An optional `--output` directory receives both artifacts and the manifest.

The Dockerfile copies `models/` into the image; it does not download artifacts.
Run setup before building, then rebuild whenever approved artifacts/script change.
Worker runtime preflight verifies the hashes, complete label map, ONNX session
and one actual inference result before advertising `image_inference`.
Files are present in this local checkout; their presence here does not prove
availability on another laptop or in a future clean checkout.
