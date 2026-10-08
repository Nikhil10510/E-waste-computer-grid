"""Run and record the pinned real-photo demo without claiming general model accuracy."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from setup_sample_data import BASE, DEMO_DIR, prepare_dataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=BASE.parents[1] / 'output/workloads/phase1')
    args = parser.parse_args()
    entries = prepare_dataset(verify_only=True)
    root = BASE.parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(INPUT_DIR=str(DEMO_DIR), OUTPUT_DIR=str(output), PREFLIGHT='1',
               MODEL_PATH=str(root / 'workloads/ai-inference/models/mobilenetv2-12.onnx'),
               LABELS_PATH=str(root / 'workloads/ai-inference/models/imagenet_labels.json'),
               ARTIFACT_MANIFEST=str(root / 'workloads/ai-inference/models/artifact-manifest.json'))
    subprocess.run([sys.executable, str(root / 'workloads/ai-inference/run_inference.py')],
                   env=env, check=True, timeout=90)
    result = json.loads((output / 'result.json').read_text(encoding='utf-8'))
    predictions = result['predictions']
    names = [prediction['image'] for prediction in predictions]
    if (result['itemsProcessed'] != len(entries) or result['itemsFailed'] != 0
            or len(names) != len(set(names)) or set(names) != {entry['filename'] for entry in entries}):
        raise ValueError('Demo did not return exactly one prediction for every pinned photo')
    by_name = {prediction['image']: prediction for prediction in predictions}
    rows = []
    for entry in entries:
        prediction = by_name[entry['filename']]
        expected = entry['expected_labels']
        rows.append({'image': entry['filename'], 'subject': entry['subject'],
                     'expected_labels': expected, 'prediction': prediction['className'],
                     'confidence': prediction['confidence'],
                     'label_match': prediction['className'].lower() in {label.lower() for label in expected} if expected else None})
    scored = [row for row in rows if row['label_match'] is not None]
    report = {'scope': 'Local native runtime; ten photo integration demo, not a representative accuracy benchmark.',
              'items_processed': len(rows), 'scored_images': len(scored),
              'label_matches': sum(row['label_match'] for row in scored),
              'excluded_from_label_score': len(rows) - len(scored),
              'model_sha256': json.loads(Path(env['ARTIFACT_MANIFEST']).read_text())['model_sha256'],
              'predictions': rows}
    (output / 'evaluation.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
