"""
The authorization matrix (core.authz_matrix) against its recorded baseline.

The baseline (authz_matrix_data/baseline.json) was recorded from the Phase 1
code, commit 3d56003, before authorization moved to permissions. Every result
must still match it, except the changes listed -- with the decision that
approved each -- in authz_matrix_data/approved_changes.json.

    AUTHZ_MATRIX_RECORD=1 manage.py test core.tests_authz_matrix
        writes a new baseline.json from the code under test (only ever from
        the commit named in AUTHZ_MATRIX_SOURCE).
    AUTHZ_MATRIX_REPORT=<path> manage.py test core.tests_authz_matrix
        also writes every difference to <path> as JSON, for review.
"""
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings

from core.authz_matrix import NEW_ROLES, add_new_role_accounts, api_routes, build_world, exercised_routes, run_matrix

DATA_DIR = Path(__file__).resolve().parent / 'authz_matrix_data'
BASELINE = DATA_DIR / 'baseline.json'
APPROVED = DATA_DIR / 'approved_changes.json'


class AuthorizationMatrixTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media = tempfile.mkdtemp(prefix='eduplus-authz-matrix-')
        # Uploads go to a throwaway directory; a fast hasher keeps the many
        # fixture accounts cheap (the real hasher is covered by tests_auth).
        cls._override = override_settings(
            MEDIA_ROOT=cls._media,
            PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
        )
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)
        super().tearDownClass()

    def run_quietly(self, world, **kwargs):
        # Hundreds of deliberate refusals would otherwise flood the output.
        logging.disable(logging.CRITICAL)
        try:
            return run_matrix(world, **kwargs)
        finally:
            logging.disable(logging.NOTSET)

    def test_new_roles_reach_what_an_unknown_role_reaches(self):
        # BDE and Sales TL have role groups but no catalogue permission yet: in
        # every scenario open to signed-in accounts they must be answered as
        # the account whose role nothing knows -- no data and no action.
        world = build_world()
        add_new_role_accounts(world)
        results = self.run_quietly(world, like_unknown=tuple(NEW_ROLES))

        def as_anyone(result, caller):
            # The caller's own account (in /me, say) is the one thing that may differ.
            result = json.loads(json.dumps(result).replace(f'"{caller}"', '"<caller>"'))
            if isinstance(result.get('capture'), dict):
                result['capture'].pop('role', None)
            return result

        scenarios = sorted({key.split(' @ ')[0] for key in results})
        self.assertGreater(len(scenarios), 100)
        for scenario in scenarios:
            unknown = as_anyone(results[f'{scenario} @ unknown'], 'unknown')
            for caller in NEW_ROLES:
                with self.subTest(scenario=scenario, caller=caller):
                    self.assertEqual(as_anyone(results[f'{scenario} @ {caller}'], caller), unknown)

    def test_every_api_route_is_in_the_matrix(self):
        covered = {route.rstrip('/') for route in exercised_routes(build_world())}
        missing = sorted({route for route in api_routes() if route.rstrip('/') not in covered})
        self.assertEqual(missing, [], 'API routes no matrix scenario exercises')

    def test_every_endpoint_answers_every_caller_as_recorded(self):
        results = self.run_quietly(build_world())

        if os.environ.get('AUTHZ_MATRIX_RECORD'):
            DATA_DIR.mkdir(exist_ok=True)
            payload = {'source': os.environ.get('AUTHZ_MATRIX_SOURCE', 'unspecified'), 'results': results}
            BASELINE.write_text(json.dumps(payload, indent=1, sort_keys=True) + '\n')
            self.skipTest(f'Recorded {len(results)} results to {BASELINE}.')

        baseline = json.loads(BASELINE.read_text())['results']
        approved = json.loads(APPROVED.read_text()).get('changes', {}) if APPROVED.exists() else {}
        expected = dict(baseline)
        for key, change in approved.items():
            expected[key] = change.get('result')

        differences = {
            key: {'expected': expected.get(key), 'actual': results.get(key)}
            for key in sorted(set(expected) | set(results))
            if expected.get(key) != results.get(key)
        }
        report = os.environ.get('AUTHZ_MATRIX_REPORT')
        if report:
            Path(report).write_text(json.dumps(differences, indent=1, sort_keys=True) + '\n')
        if differences:
            self.fail('\n'.join(
                [f'{len(differences)} result(s) differ from the baseline and its approved changes:'] +
                [f'{key}\n  expected: {json.dumps(d["expected"], sort_keys=True)}\n  actual:   {json.dumps(d["actual"], sort_keys=True)}'
                 for key, d in differences.items()]
            ))
