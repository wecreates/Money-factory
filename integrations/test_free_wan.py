import unittest
from free_wan import parameters, download_url, HOST


class FreeWanTests(unittest.TestCase):
    def job(self):
        return dict(prompt='Original stick figure turns its head', publication_enabled=False,
                    paid_generation_enabled=False, external_processing_approved=True)

    def test_bounded_defaults(self):
        self.assertEqual(parameters(self.job())[1:], (1, 42))

    def test_rejects_unbounded_and_paid_jobs(self):
        for field, value in [('external_processing_approved', False), ('paid_generation_enabled', True), ('publication_enabled', True),
                             ('duration_seconds', 30), ('duration_seconds', float('nan')),
                             ('duration_seconds', True), ('seed', -1), ('prompt', '')]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                parameters(dict(self.job(), **{field: value}))
        job = self.job()
        del job['paid_generation_enabled']
        with self.assertRaises(ValueError):
            parameters(job)

    def test_output_must_stay_on_provider_file_endpoint(self):
        good = HOST + '/gradio_api/file=/tmp/video.mp4'
        self.assertEqual(download_url([{'video': {'url': good}}]), good)
        for url in ['http://127.0.0.1/private', HOST + '.evil.example/gradio_api/file=x',
                    HOST + '/admin', HOST + '/gradio_api/file=x?token=secret']:
            with self.assertRaises(ValueError):
                download_url([{'video': {'url': url}}])
