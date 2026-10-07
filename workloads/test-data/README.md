# Test Data

This directory holds sample images for local testing and development.

## Usage:
Place sample images here and mount as input volume:
```bash
docker run --rm \
  -v ./test-data/sample:/data/input:ro \
  -v ./test-data/output:/data/output \
  ewaste/ai-workload:v1
```

## Sample images needed:
- A few .jpg/.png images (any content — animals, objects, etc.)
- At least 5-10 for meaningful testing
- Various sizes are fine — preprocessing resizes to 224×224

> **Note:** Do NOT commit large test datasets to git. 
> Use S3 for real batch datasets. Only keep a small sample set here.
