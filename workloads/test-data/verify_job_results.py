"""Verify the downloaded, successful ten-photo Phase 2 acceptance result."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path

BASE = Path(__file__).resolve().parent


def verify_job(result, names, chunk_size=5):
    if not isinstance(result, dict) or result.get('status') != 'COMPLETED':
        raise ValueError('Expected a terminal COMPLETED job, not an in-progress/partial snapshot')
    expected_tasks = math.ceil(len(names) / chunk_size)
    counts = {'total_tasks': expected_tasks, 'completed_tasks': expected_tasks,
              'failed_tasks': 0, 'items_processed': len(names), 'items_failed': 0}
    for key, expected in counts.items():
        if type(result.get(key)) is not int or result[key] != expected:
            raise ValueError(f'Unexpected {key}: expected {expected}')
    predictions = result.get('predictions')
    if not isinstance(predictions, list) or len(predictions) != len(names) or result.get('errors') != []:
        raise ValueError('Expected one successful prediction for each photo and no errors')
    expected_names = [f'{i:05d}_{name}' for i, name in enumerate(names)]
    actual_names = []
    task_names = {}
    for prediction in predictions:
        if not isinstance(prediction, dict):
            raise ValueError('Invalid prediction object')
        name = prediction.get('image')
        if not isinstance(name, str):
            raise ValueError('Prediction must include its assigned image identity')
        actual_names.append(name)
        class_id = prediction.get('classId')
        label = prediction.get('className')
        confidence = prediction.get('confidence')
        if (type(class_id) is not int or not 0 <= class_id <= 999
                or not isinstance(label, str) or not 0 < len(label.strip()) <= 200
                or type(confidence) not in (int, float) or not math.isfinite(confidence)
                or not 0 <= confidence <= 1):
            raise ValueError('Prediction class or confidence violates the contract')
        task_id = prediction.get('task_id')
        if not isinstance(task_id, str) or not task_id:
            raise ValueError('Prediction must identify its accepted task')
        task_names.setdefault(task_id, []).append(name)
    if Counter(actual_names) != Counter(expected_names):
        raise ValueError('Missing, duplicated or unassigned image identities')
    expected_chunks = {frozenset(expected_names[i:i+chunk_size]) for i in range(0, len(names), chunk_size)}
    if len(task_names) != expected_tasks or {frozenset(v) for v in task_names.values()} != expected_chunks:
        raise ValueError('Accepted task chunks do not match the submitted split')
    metrics = result.get('metrics', {})
    if not isinstance(metrics, dict) or metrics.get('metric_type') != 'ESTIMATED':
        raise ValueError('Expected explicitly estimated energy metrics')
    for field in ('estimated_energy_wh', 'execution_time_ms'):
        value = metrics.get(field)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(f'Invalid {field}')
    return {'job_id': result.get('job_id'), 'status': result['status'], 'tasks': expected_tasks,
            'images': len(names), 'exact_input_coverage': True, 'errors': 0,
            'task_ids': sorted(task_names), 'metric_type': 'ESTIMATED',
            'scope': 'Downloaded job accounting/structure; not visual label accuracy or physical-machine evidence.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('result', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    manifest = json.loads((BASE / 'demo-manifest.json').read_text(encoding='utf-8'))
    names = sorted(entry['filename'] for entry in manifest['images'])
    try:
        report = verify_job(json.loads(args.result.read_text(encoding='utf-8-sig')), names)
    except (OSError, ValueError) as error:
        print(f'Acceptance verification failed: {error}')
        return 1
    raw = json.dumps(report, indent=2) + '\n'
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(raw, encoding='utf-8')
    print(raw)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
