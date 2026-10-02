"""Cross-compile all adapter paths with inert configuration; never flash a board."""
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
local = root / '.local'
local.mkdir(exist_ok=True)
defaults = local / 'compile.defaults'
defaults.write_text((root / 'sdkconfig.defaults').read_text() + '\n' + (root / 'sdkconfig.compile.defaults').read_text())
options = [
    'make', 'SDKCONFIG=' + str(local / 'sdkconfig.compile'),
    'SDKCONFIG_DEFAULTS=' + str(defaults),
    'BUILD_DIR_BASE=' + str(root / 'build-compile'),
]
subprocess.run(options + ['defconfig'], cwd=root, check=True)
subprocess.run(options + ['-j2', 'all'], cwd=root, check=True)
subprocess.run(options + ['size'], cwd=root, check=True)
# cJSON uses floating-point printf/scanf even for integer-valued JSON numbers.
config = (local / 'sdkconfig.compile').read_text()
if '# CONFIG_NEWLIB_NANO_FORMAT is not set' not in config:
    raise RuntimeError('Full Newlib numeric formatting must be enabled')
# Detect an accidentally empty configuration that eliminated networking.
symbols = subprocess.check_output(['xtensa-lx106-elf-nm', str(root / 'build-compile/appliance_esp8266.elf')], text=True)
for symbol in ('esp_mqtt_client_start', 'esp_wifi_start', 'mbedtls_ssl_handshake', 'spool_append', 'desired_accept'):
    if not any(line.endswith(' ' + symbol) for line in symbols.splitlines()):
        raise RuntimeError('Expected linked feature missing: ' + symbol)
print('PASS Wi-Fi, TLS, MQTT, durable spool and desired-state symbols are linked')

for symbol in ('_svfprintf_r', '_dtoa_r'):
    if not any(line.endswith(' ' + symbol) for line in symbols.splitlines()):
        raise RuntimeError('Full numeric formatter was not linked: ' + symbol)
for symbol in ('_printf_i', '_scanf_i'):
    if any(line.endswith(' ' + symbol) for line in symbols.splitlines()):
        raise RuntimeError('Unexpected nano integer formatter linked: ' + symbol)
print('PASS full Newlib numeric formatting is configured and linked for cJSON')
