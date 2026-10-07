# Model files directory

This directory holds the ONNX model and ImageNet labels.
These files are baked into the Docker image at build time.

## Files (after running download_model.py):
- `mobilenetv2-12.onnx` — MobileNetV2 FP32 ONNX model (~13.3 MiB)
- `imagenet_labels.json` — ImageNet 1000-class label mapping

## How to populate:
```bash
cd workloads/ai-inference
python download_model.py --output ./models/
```

> **Note:** Model files are NOT committed to git (too large). 
> They are downloaded during Docker build or local development setup.
