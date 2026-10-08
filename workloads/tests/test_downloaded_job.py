import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('verify_download', Path(__file__).resolve().parents[1] / 'test-data/verify_job_results.py')
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class DownloadedJobTests(unittest.TestCase):
    def setUp(self):
        self.names = [f'photo-{i}.jpg' for i in range(10)]
        self.result = {'job_id': 'job', 'status': 'COMPLETED', 'total_tasks': 2, 'completed_tasks': 2,
                       'failed_tasks': 0, 'items_processed': 10, 'items_failed': 0, 'errors': [],
                       'metrics': {'metric_type': 'ESTIMATED', 'estimated_energy_wh': 0.03, 'execution_time_ms': 2000},
                       'predictions': [{'image': f'{i:05d}_{name}', 'task_id': f'task-{i//5}',
                                        'classId': 281, 'className': 'tabby', 'confidence': 0.8}
                                       for i, name in enumerate(self.names)]}

    def test_valid_download_verifies_two_exact_chunks(self):
        report = verifier.verify_job(self.result, self.names)
        self.assertTrue(report['exact_input_coverage'])
        self.assertEqual(report['tasks'], 2)

    def test_pending_partial_and_count_validity_are_not_success(self):
        for field, value in [('status', 'IN_PROGRESS'), ('status', 'PARTIAL_SUCCESS'),
                             ('items_processed', 9), ('completed_tasks', True), ('failed_tasks', 1)]:
            result = copy.deepcopy(self.result); result[field] = value
            with self.assertRaises(ValueError): verifier.verify_job(result, self.names)

    def test_duplicate_wrong_and_missing_names_fail(self):
        for value in [self.result['predictions'][1]['image'], '99999_other.jpg', None]:
            result = copy.deepcopy(self.result); result['predictions'][0]['image'] = value
            with self.assertRaises(ValueError): verifier.verify_job(result, self.names)

    def test_valid_counts_cannot_hide_wrong_task_grouping(self):
        result = copy.deepcopy(self.result)
        result['predictions'][0]['task_id'], result['predictions'][5]['task_id'] = 'task-1', 'task-0'
        with self.assertRaisesRegex(ValueError, 'chunks'): verifier.verify_job(result, self.names)

    def test_invalid_prediction_and_metric_values_fail(self):
        for field, value in [('confidence', float('nan')), ('confidence', 1.1), ('classId', True),
                             ('className', ''), ('task_id', None)]:
            result = copy.deepcopy(self.result); result['predictions'][0][field] = value
            with self.assertRaises(ValueError): verifier.verify_job(result, self.names)
        result = copy.deepcopy(self.result); result['metrics']['metric_type'] = 'MEASURED'
        with self.assertRaises(ValueError): verifier.verify_job(result, self.names)


if __name__ == '__main__': unittest.main()
