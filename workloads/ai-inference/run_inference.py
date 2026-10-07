"""
E-Waste Compute Grid — AI Inference Entrypoint
Model: MobileNetV2 (ONNX, FP32, CPU)
Owner: Nikhil Kumar

This script is the Docker container entrypoint. It:
1. Reads images from /data/input/
2. Runs MobileNetV2 inference using ONNX Runtime (CPU)
3. Writes result.json to /data/output/

NO network access is needed. The Worker Agent handles all S3 I/O
outside the container.
"""

import os
import sys
import json
import time
import traceback
import numpy as np

# Ensure standard output can handle Unicode characters on Windows consoles
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


# Lazy imports to measure startup time
STARTUP_START = time.perf_counter()

INPUT_DIR = os.getenv("INPUT_DIR", "/data/input")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/data/output")
MODEL_PATH = os.getenv("MODEL_PATH", "/models/mobilenetv2-12.onnx")
LABELS_PATH = os.getenv("LABELS_PATH", "/models/imagenet_labels.json")

# ImageNet normalization constants (frozen — see docs/model_selection.md)
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(3, 1, 1)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(3, 1, 1)

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def load_labels(labels_path: str) -> dict:
    """Load ImageNet class index → label mapping."""
    if os.path.exists(labels_path):
        with open(labels_path, "r") as f:
            labels = json.load(f)
        # Handle both list format and dict format
        if isinstance(labels, list):
            return {i: label for i, label in enumerate(labels)}
        elif isinstance(labels, dict):
            return {int(k): v for k, v in labels.items()}
    return {}


def preprocess_image(image_path: str) -> np.ndarray:
    """
    Preprocess a single image for MobileNetV2 inference.
    
    Pipeline (frozen — see docs/model_selection.md):
    1. Open image, convert to RGB
    2. Resize to 224×224 (bilinear interpolation)
    3. Convert to float32, scale to [0.0, 1.0]
    4. Normalize with ImageNet mean/std
    5. Transpose to NCHW: shape [1, 3, 224, 224]
    """
    from PIL import Image
    
    from PIL import ImageOps
    with Image.open(image_path) as source:
        img = ImageOps.exif_transpose(source).convert("RGB")
        img = img.resize((224, 224), Image.Resampling.BILINEAR)
    
    # Convert to numpy: HWC float32 [0, 1]
    img_array = np.array(img, dtype=np.float32) / 255.0
    
    # Transpose HWC → CHW
    img_array = img_array.transpose(2, 0, 1)
    
    # Normalize with ImageNet stats
    img_array = (img_array - IMAGENET_MEAN) / IMAGENET_STD
    
    # Add batch dimension: [1, 3, 224, 224]
    return np.expand_dims(img_array, axis=0)


def softmax(logits: np.ndarray) -> np.ndarray:
    """Numerically stable softmax."""
    exp_logits = np.exp(logits - np.max(logits))
    return exp_logits / np.sum(exp_logits)


def run_inference():
    """Main inference loop — processes all images in INPUT_DIR."""
    import onnxruntime as ort
    
    print(f"[INFO] Starting inference...")
    print(f"[INFO] Input directory:  {INPUT_DIR}")
    print(f"[INFO] Output directory: {OUTPUT_DIR}")
    print(f"[INFO] Model path:       {MODEL_PATH}")
    
    # Validate input directory
    if not os.path.isdir(INPUT_DIR):
        raise FileNotFoundError(f"Input directory not found: {INPUT_DIR}")
    
    # Validate model file
    if not os.path.isfile(MODEL_PATH):
        raise FileNotFoundError(f"Model file not found: {MODEL_PATH}")
    
    # Load labels
    labels = load_labels(LABELS_PATH)
    
    # Initialize ONNX Runtime session (CPU only)
    session_options = ort.SessionOptions()
    session_options.intra_op_num_threads = max(1, min(4, os.cpu_count() or 2))
    session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    
    session = ort.InferenceSession(
        MODEL_PATH,
        sess_options=session_options,
        providers=["CPUExecutionProvider"]
    )
    input_name = session.get_inputs()[0].name
    
    startup_time_ms = int((time.perf_counter() - STARTUP_START) * 1000)
    print(f"[INFO] Model loaded in {startup_time_ms}ms")
    
    # Discover image files
    image_files = sorted([
        f for f in os.listdir(INPUT_DIR)
        if os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS
    ])
    
    if not image_files:
        raise ValueError(f"No supported images found in {INPUT_DIR}")
    
    print(f"[INFO] Found {len(image_files)} images to process")
    
    # Run inference on each image
    predictions = []
    errors = []
    inference_start = time.perf_counter()
    
    for i, img_name in enumerate(image_files):
        img_path = os.path.join(INPUT_DIR, img_name)
        try:
            input_tensor = preprocess_image(img_path)
            outputs = session.run(None, {input_name: input_tensor})
            
            logits = outputs[0][0]
            probabilities = softmax(logits)
            predicted_class = int(np.argmax(probabilities))
            confidence = float(probabilities[predicted_class])
            class_name = labels.get(predicted_class, f"class_{predicted_class}")
            
            predictions.append({
                "image": img_name,
                "classId": predicted_class,
                "className": class_name,
                "confidence": round(confidence, 4)
            })
            
            if (i + 1) % 50 == 0:
                print(f"[INFO] Processed {i + 1}/{len(image_files)} images...")
                
        except Exception as e:
            error_msg = f"Failed to process {img_name}: {str(e)}"
            print(f"[ERROR] {error_msg}")
            errors.append({
                "image": img_name,
                "error": error_msg
            })
    
    inference_time_ms = int((time.perf_counter() - inference_start) * 1000)
    total_time_ms = int((time.perf_counter() - STARTUP_START) * 1000)
    
    # Calculate summary statistics
    successful = len(predictions)
    failed = len(errors)
    avg_confidence = (
        round(sum(p["confidence"] for p in predictions) / successful, 4)
        if successful > 0 else 0.0
    )
    
    # Build result payload
    result = {
        "status": "SUCCESS" if failed == 0 else "PARTIAL_FAILURE",
        "itemsProcessed": successful,
        "itemsFailed": failed,
        "executionTimeMs": total_time_ms,
        "startupTimeMs": startup_time_ms,
        "inferenceTimeMs": inference_time_ms,
        "predictions": predictions,
        "errors": errors,
        "summary": {
            "totalImages": len(image_files),
            "successfulInferences": successful,
            "failedInferences": failed,
            "averageConfidence": avg_confidence,
            "imagesPerSecond": round(successful / (inference_time_ms / 1000), 2) if inference_time_ms > 0 else 0
        }
    }
    
    # Write output atomically to prevent partial/corrupted output on crash or kill
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, "result.json")
    tmp_path = os.path.join(OUTPUT_DIR, "result.json.tmp")
    
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    os.replace(tmp_path, output_path)
    
    print(f"[INFO] ✅ Inference complete!")
    print(f"[INFO]   Processed: {successful}/{len(image_files)} images")
    print(f"[INFO]   Failed:    {failed}")
    print(f"[INFO]   Total time: {total_time_ms}ms")
    print(f"[INFO]   Inference:  {inference_time_ms}ms")
    print(f"[INFO]   Speed:      {result['summary']['imagesPerSecond']} img/s")
    print(f"[INFO]   Output:     {output_path}")
    
    # Exit with error code if all images failed
    if failed > 0 and successful == 0:
        sys.exit(1)
    
    return result


if __name__ == "__main__":
    try:
        run_inference()
    except Exception as e:
        print(f"[FATAL] {str(e)}")
        traceback.print_exc()
        
        # Write error result atomically so the Worker Agent can report the failure cleanly
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        output_path = os.path.join(OUTPUT_DIR, "result.json")
        tmp_path = os.path.join(OUTPUT_DIR, "result.json.tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump({
                    "status": "FATAL_ERROR",
                    "itemsProcessed": 0,
                    "itemsFailed": 0,
                    "executionTimeMs": int((time.perf_counter() - STARTUP_START) * 1000),
                    "error": str(e),
                    "predictions": [],
                    "errors": [{"error": str(e), "traceback": traceback.format_exc()}]
                }, f, indent=2)
            os.replace(tmp_path, output_path)
        except Exception:
            pass
        
        sys.exit(1)

