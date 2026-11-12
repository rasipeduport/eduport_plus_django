"""Offline checks only: fake Stripe binary, temporary files, Compose rendering.

No Docker Engine connection, container startup, Django startup, DB or network.
"""

import ast
import json
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
LISTENER = ROOT / 'docker/stripe/listener.sh'
SECRET = 'whsec_TESTONLYNOTACREDENTIAL'
OTHER_SECRET = 'whsec_OTHERTESTONLYNOTACREDENTIAL'


class ListenerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.state = self.directory / 'state'
        self.calls = self.directory / 'calls'
        fake_cli = self.directory / 'stripe'
        fake_cli.write_text('''#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_CALLS"
case "$*" in
  *--print-secret*)
    case "${FAKE_RESPONSE:-valid}" in
      failed) printf '%s\\n' "$FAKE_SECRET" >&2; exit 9 ;;
      invalid) printf 'Unexpected response: %s\\n' "$FAKE_SECRET" ;;
      duplicate) printf '%s\\n%s\\n' "$FAKE_SECRET" "$FAKE_SECRET" ;;
      *) printf '%s\\n' "$FAKE_SECRET" ;;
    esac ;;
  *) printf 'Mock listener started\\n'; exit "${FAKE_LISTEN_EXIT:-0}" ;;
esac
''')
        fake_cli.chmod(0o700)
        # No inherited Stripe credentials or operational configuration.
        self.env = {
            'PATH': f'{self.directory}:/usr/bin:/bin',
            'HOME': str(self.directory),
            'EDUPORT_STRIPE_LOCAL': '1',
            'STRIPE_API_KEY': 'sk_test_not_a_real_key',
            'STRIPE_STATE_DIR': str(self.state),
            'FAKE_CALLS': str(self.calls),
            'FAKE_SECRET': SECRET,
        }

    def run_listener(self, mode='prepare', **overrides):
        result = subprocess.run(
            ['sh', str(LISTENER), mode],
            env={**self.env, **overrides}, text=True, capture_output=True,
            timeout=10,
        )
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        self.assertNotIn(OTHER_SECRET, result.stdout + result.stderr)
        return result

    def test_prepare_writes_secret_privately_without_printing_it(self):
        self.assertEqual(self.run_listener().returncode, 0)
        secret_file = self.state / 'webhook-secret'
        self.assertEqual(secret_file.read_text(), SECRET)
        self.assertEqual(stat.S_IMODE(secret_file.stat().st_mode), 0o444)
        self.assertEqual(list(self.state.iterdir()), [secret_file])

    def test_repeated_prepare_preserves_existing_file(self):
        self.assertEqual(self.run_listener().returncode, 0)
        before = (self.state / 'webhook-secret').stat().st_ino
        self.assertEqual(self.run_listener().returncode, 0)
        self.assertEqual((self.state / 'webhook-secret').stat().st_ino, before)

    def test_concurrent_prepare_is_idempotent(self):
        processes = [subprocess.Popen(
            ['sh', str(LISTENER), 'prepare'], env=self.env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        ) for _ in range(2)]
        for process in processes:
            output, errors = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, errors)
            self.assertNotIn(SECRET, output + errors)
        self.assertEqual((self.state / 'webhook-secret').read_text(), SECRET)
        self.assertEqual(len(list(self.state.iterdir())), 1)

    def test_mismatch_never_overwrites_existing_secret(self):
        self.assertEqual(self.run_listener().returncode, 0)
        result = self.run_listener(FAKE_SECRET=OTHER_SECRET)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('mismatch', result.stderr)
        self.assertEqual((self.state / 'webhook-secret').read_text(), SECRET)

    def test_mismatch_never_starts_forwarding(self):
        self.run_listener()
        self.assertNotEqual(self.run_listener('listen', FAKE_SECRET=OTHER_SECRET).returncode, 0)
        self.assertNotIn('--forward-to', self.calls.read_text())

    def test_verify_does_not_start_forwarding(self):
        self.run_listener()
        self.assertEqual(self.run_listener('verify').returncode, 0)
        self.assertNotIn('--forward-to', self.calls.read_text())

    def test_listen_requires_prepare_before_contacting_stripe(self):
        self.assertNotEqual(self.run_listener('listen').returncode, 0)
        self.assertFalse(self.calls.exists())

    def test_overlay_is_required(self):
        self.assertNotEqual(self.run_listener(EDUPORT_STRIPE_LOCAL='').returncode, 0)
        self.assertFalse(self.calls.exists())

    def test_missing_and_live_keys_are_rejected_before_calling_stripe(self):
        for value in ('', 'sk_live_not_a_real_key', 'rk_live_not_a_real_key'):
            with self.subTest(value=value):
                self.assertNotEqual(self.run_listener(STRIPE_API_KEY=value).returncode, 0)
        self.assertFalse(self.calls.exists())

    def test_restricted_test_key_is_accepted(self):
        self.assertEqual(self.run_listener(STRIPE_API_KEY='rk_test_not_a_real_key').returncode, 0)

    def test_failed_bootstrap_does_not_leak_secret_or_leave_files(self):
        self.assertNotEqual(self.run_listener(FAKE_RESPONSE='failed').returncode, 0)
        self.assertEqual(list(self.state.iterdir()), [])

    def test_invalid_responses_do_not_persist_secret(self):
        for response in ('invalid', 'duplicate'):
            with self.subTest(response=response):
                self.assertNotEqual(self.run_listener(FAKE_RESPONSE=response).returncode, 0)
                self.assertEqual(list(self.state.iterdir()), [])

    def test_listener_uses_matching_identity_and_internal_url(self):
        self.run_listener()
        self.assertEqual(self.run_listener('listen').returncode, 0)
        calls = self.calls.read_text().splitlines()
        bootstrap_prefix = calls[0].removesuffix('listen --print-secret')
        self.assertEqual(calls[-1], bootstrap_prefix + (
            'listen --all-snapshot --forward-to http://backend:8000/api/sales/webhooks/stripe/'
        ))
        self.assertIn('--all-snapshot', calls[-1].split())
        self.assertNotIn('--all-snapshot', calls[0].split())
        self.assertNotIn('--live', self.calls.read_text())
        self.assertNotIn('sk_test_', self.calls.read_text())

    def test_listener_exit_status_is_preserved(self):
        self.run_listener()
        self.assertEqual(self.run_listener('listen', FAKE_LISTEN_EXIT='23').returncode, 23)

    def test_failed_listener_revalidation_preserves_prepared_secret(self):
        self.assertEqual(self.run_listener().returncode, 0)
        self.assertNotEqual(self.run_listener('listen', FAKE_RESPONSE='failed').returncode, 0)
        secret_file = self.state / 'webhook-secret'
        self.assertEqual(secret_file.read_text(), SECRET)
        self.assertEqual(list(self.state.iterdir()), [secret_file])
        self.assertNotIn('--forward-to', self.calls.read_text())


class ComposeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def render(overlay=False):
            command = ['docker', 'compose', '-p', 'eduport_plus_django',
                       '--project-directory', str(ROOT), '-f',
                       str(ROOT / 'docker-compose.yml')]
            if overlay:
                command += ['-f', str(ROOT / 'docker-compose.stripe-local.yml'),
                            '--profile', 'local-stripe']
            command += ['config', '--no-env-resolution',
                        '--no-interpolate', '--format', 'json']
            result = subprocess.run(command, cwd=ROOT, capture_output=True,
                                    text=True, check=True, timeout=15)
            return json.loads(result.stdout)

        cls.base = render()
        cls.local = render(overlay=True)

    def test_existing_services_and_entrypoints_are_unchanged_by_default(self):
        # A fixed service contract remains meaningful in a clean checkout after
        # commit. Reading HEAD here would compare the Compose file with itself.
        expected = {
            'db': {'dependencies': set(), 'ports': {('5433', 5432)},
                   'volumes': {'/var/lib/postgresql/data': 'pgdata'}},
            'redis': {'dependencies': set(), 'ports': {('6380', 6379)}, 'volumes': {}},
            'backend': {'dependencies': {'db'}, 'ports': {('8000', 8000)},
                        'volumes': {'/app/media': 'media'}},
            'worker': {'dependencies': {'backend', 'redis'}, 'ports': set(), 'volumes': {}},
            'beat': {'dependencies': {'backend', 'redis'}, 'ports': set(), 'volumes': {}},
            'hub': {'dependencies': {'backend'}, 'ports': {('3000', 80)}, 'volumes': {}},
            'learn': {'dependencies': {'backend'}, 'ports': {('3001', 80)}, 'volumes': {}},
        }
        self.assertEqual(set(self.base['services']), set(expected))
        for name, contract in expected.items():
            with self.subTest(service=name):
                service = self.base['services'][name]
                self.assertEqual(service['container_name'], f'eduplus-{name}')
                self.assertEqual(service['restart'], 'unless-stopped')
                self.assertFalse(service.get('profiles'))
                self.assertEqual(set(service.get('depends_on', {})), contract['dependencies'])
                self.assertEqual(
                    {(str(port['published']), port['target']) for port in service.get('ports', [])},
                    contract['ports'],
                )
                self.assertEqual(
                    {volume['target']: volume['source'] for volume in service.get('volumes', [])},
                    contract['volumes'],
                )

        backend = self.base['services']['backend']
        # Inherit the image's migration entrypoint and Gunicorn command.
        self.assertNotIn('entrypoint', backend)
        self.assertNotIn('command', backend)
        self.assertEqual(backend['depends_on']['db']['condition'], 'service_healthy')
        for name, arguments in {
            'worker': ['worker', '--loglevel=info', '--concurrency=2'],
            'beat': ['beat', '--loglevel=info', '--schedule', '/tmp/celerybeat-schedule'],
        }.items():
            with self.subTest(celery_service=name):
                service = self.base['services'][name]
                self.assertEqual(service['entrypoint'], [])
                self.assertEqual(service['command'], ['celery', '-A', 'config', *arguments])
                for dependency in ('backend', 'redis'):
                    self.assertEqual(service['depends_on'][dependency]['condition'], 'service_healthy')

        for name in ('backend', 'worker', 'beat'):
            with self.subTest(backend_image_service=name):
                service = self.base['services'][name]
                self.assertEqual(service['build']['context'], str(ROOT / 'backend'))
                self.assertEqual(len(service['env_file']), 1)
                self.assertEqual(service['env_file'][0]['path'], str(ROOT / 'backend/.env'))
        for name in ('hub', 'learn'):
            with self.subTest(frontend_service=name):
                service = self.base['services'][name]
                self.assertEqual(service['build']['context'], str(ROOT / 'frontend' / name))
                self.assertNotIn('entrypoint', service)
                self.assertNotIn('command', service)

    def test_listener_is_pinned_opt_in_and_has_no_ports_or_persistent_logs(self):
        service = self.local['services']['stripe-listener']
        self.assertEqual(service['image'], 'stripe/stripe-cli:v1.55.11')
        self.assertEqual(service['profiles'], ['local-stripe'])
        self.assertEqual(service['restart'], 'unless-stopped')
        self.assertEqual(service['logging']['driver'], 'none')
        self.assertNotIn('ports', service)
        self.assertNotIn('expose', service)
        self.assertEqual(service['depends_on']['backend']['condition'], 'service_healthy')

    def test_listener_has_dedicated_env_and_persistent_config_and_secret(self):
        service = self.local['services']['stripe-listener']
        self.assertEqual(len(service['env_file']), 1)
        self.assertTrue(service['env_file'][0]['path'].endswith('/.local/stripe/listener.env'))
        volumes = {item['target']: item for item in service['volumes']}
        self.assertEqual(volumes['/root/.config/stripe']['source'], 'stripe_cli_config')
        self.assertEqual(volumes['/run/eduport-stripe']['source'], 'stripe_webhook_secret')
        self.assertTrue(volumes['/opt/eduport-stripe/listener.sh']['read_only'])

    def test_overlay_leaves_existing_application_services_unchanged(self):
        self.assertEqual(set(self.local['services']), set(self.base['services']) | {'stripe-listener'})
        for name, service in self.base['services'].items():
            with self.subTest(service=name):
                self.assertEqual(self.local['services'][name], service)
        local_volumes = {'stripe_cli_config', 'stripe_webhook_secret'}
        self.assertEqual(set(self.local['volumes']), set(self.base['volumes']) | local_volumes)
        for name in local_volumes:
            self.assertEqual(self.local['volumes'][name]['name'], f'{self.base["name"]}_{name}')

    def test_base_has_no_listener_or_listener_state_volumes(self):
        self.assertNotIn('stripe-listener', self.base['services'])
        self.assertEqual(set(self.base['volumes']), {'pgdata', 'media'})
        self.assertNotIn('local-stripe', (ROOT / 'docker-compose.yml').read_text())

    def test_listener_reuses_existing_project_and_default_network(self):
        self.assertEqual(self.local['name'], self.base['name'])
        self.assertEqual(self.local['networks'], self.base['networks'])
        self.assertEqual(set(self.local['networks']), {'default'})
        self.assertEqual(
            self.local['services']['stripe-listener']['networks'],
            self.local['services']['backend']['networks'],
        )

    def test_django_keeps_existing_environment_based_signing_secret(self):
        source = (ROOT / 'backend/config/settings.py').read_text()
        setting = next(
            node for node in ast.parse(source).body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == 'STRIPE_WEBHOOK_SECRET'
                    for target in node.targets)
        )
        self.assertIsInstance(setting.value, ast.Call)
        self.assertIsInstance(setting.value.func, ast.Name)
        self.assertEqual(setting.value.func.id, 'env')
        self.assertEqual([argument.value for argument in setting.value.args], ['STRIPE_WEBHOOK_SECRET'])
        self.assertEqual([(keyword.arg, keyword.value.value) for keyword in setting.value.keywords],
                         [('default', '')])
        self.assertNotIn('STRIPE_WEBHOOK_SECRET_FILE', source)
        self.assertFalse((ROOT / 'backend/core/stripe_secrets.py').exists())

    def test_template_is_empty_and_local_credential_path_is_ignored(self):
        template = (ROOT / 'docker/stripe/.env.example').read_text()
        values = [line for line in template.splitlines() if line and not line.startswith('#')]
        self.assertEqual(values, ['STRIPE_API_KEY='])
        result = subprocess.run(
            ['git', 'check-ignore', '.local/stripe/listener.env'], cwd=ROOT,
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
