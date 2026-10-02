"""Verify TLS configuration defaults and fail-closed compile-time requirements."""
from itertools import product
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
flags = ('CONFIG_MBEDTLS_HAVE_TIME', 'CONFIG_MBEDTLS_HAVE_TIME_DATE')
for defaults in (root / 'sdkconfig.defaults', root / 'esp8266/sdkconfig.defaults'):
    values = dict(line.split('=', 1) for line in defaults.read_text().splitlines()
                  if line.startswith('CONFIG_') and '=' in line)
    for flag in flags:
        if values.get(flag) != 'y':
            raise AssertionError(f'{defaults.name}: {flag} must be explicitly enabled')
print('PASS ESP32 and ESP8266 defaults explicitly enable TLS time and validity-date checks')

with tempfile.TemporaryDirectory(prefix='appliance-tls-config-') as directory:
    path = Path(directory)
    for values in product((None, 0, 1), repeat=2):
        configuration = ''.join(f'#define {flag} {value}\n'
                                for flag, value in zip(flags, values) if value is not None)
        (path / 'sdkconfig.h').write_text(configuration)
        result = subprocess.run([
            'cc', '-E', '-x', 'c', '-I', str(path),
            str(root / 'main/tls_requirements.h'),
        ], capture_output=True, text=True, timeout=10)
        expected = values == (1, 1)
        if (result.returncode == 0) != expected:
            raise AssertionError(f'TLS config {values} unexpectedly returned {result.returncode}: {result.stderr}')
        if not expected and 'TLS requires CONFIG_MBEDTLS_' not in result.stderr:
            raise AssertionError(f'Configuration failed for an unrelated reason: {result.stderr}')
print('PASS eight missing/disabled combinations rejected; both required options enabled accepted')
