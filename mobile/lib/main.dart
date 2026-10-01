import 'dart:async';

import 'package:flutter/material.dart';

import 'controller.dart';
import 'models.dart';
import 'store.dart';
import 'store_native.dart' if (dart.library.js_interop) 'store_web.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  WidgetsBinding.instance.ensureSemantics();
  try {
    final store = await openLocalStore();
    runApp(FleetApp(store: store));
  } catch (_) {
    runApp(
      MaterialApp(
        home: Scaffold(
          body: Center(
            child: Padding(
              padding: const EdgeInsets.all(32),
              child: Text(
                'Local storage could not open. Check that browser storage is enabled and '
                'the SQLite web assets are served. Reload after fixing storage.',
              ),
            ),
          ),
        ),
      ),
    );
  }
}

ThemeData fleetTheme() => ThemeData(
  useMaterial3: true,
  colorScheme: ColorScheme.fromSeed(
    seedColor: const Color(0xff087f8c),
    brightness: Brightness.light,
  ),
  scaffoldBackgroundColor: const Color(0xfff3f6f8),
  appBarTheme: const AppBarTheme(
    backgroundColor: Color(0xfff3f6f8),
    surfaceTintColor: Colors.transparent,
  ),
  inputDecorationTheme: const InputDecorationTheme(
    border: OutlineInputBorder(),
  ),
);

class FleetApp extends StatefulWidget {
  const FleetApp({super.key, required this.store});
  final LocalStore store;
  @override
  State<FleetApp> createState() => _FleetAppState();
}

class _FleetAppState extends State<FleetApp> {
  FleetController? controller;
  @override
  void dispose() {
    controller?.dispose();
    super.dispose();
  }

  void connect(String server, String token) {
    controller?.dispose();
    final next = FleetController(
      server: server,
      token: token,
      store: widget.store,
    );
    setState(() => controller = next);
    unawaited(next.start());
  }

  void disconnect() {
    controller?.dispose();
    setState(() => controller = null);
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'Appliance Energy',
    debugShowCheckedModeBanner: false,
    theme: fleetTheme(),
    home: controller == null
        ? ConnectionScreen(onConnect: connect)
        : FleetDashboard(controller: controller!, onDisconnect: disconnect),
  );
}

class ConnectionScreen extends StatefulWidget {
  const ConnectionScreen({super.key, required this.onConnect});
  final void Function(String, String) onConnect;
  @override
  State<ConnectionScreen> createState() => _ConnectionScreenState();
}

class _ConnectionScreenState extends State<ConnectionScreen> {
  final server = TextEditingController(text: 'http://127.0.0.1:18080');
  final token = TextEditingController();
  String? error;
  @override
  void dispose() {
    server.dispose();
    token.dispose();
    super.dispose();
  }

  void submit() {
    try {
      final uri = validateServer(server.text);
      if (token.text.trim().isEmpty) {
        throw const FormatException('Enter the operator token.');
      }
      widget.onConnect(uri.toString(), token.text.trim());
    } on FormatException catch (e) {
      setState(() => error = e.message);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    body: Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 460),
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(32),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Icon(
                    Icons.energy_savings_leaf_outlined,
                    size: 52,
                    color: Color(0xff087f8c),
                  ),
                  const SizedBox(height: 20),
                  Text(
                    'Appliance Energy',
                    style: Theme.of(context).textTheme.headlineMedium,
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'Know the state. Control the fleet. See the energy.',
                  ),
                  const SizedBox(height: 28),
                  TextField(
                    key: const Key('server'),
                    controller: server,
                    decoration: const InputDecoration(
                      labelText: 'Server origin',
                    ),
                  ),
                  const SizedBox(height: 16),
                  TextField(
                    key: const Key('token'),
                    controller: token,
                    obscureText: true,
                    autocorrect: false,
                    enableSuggestions: false,
                    decoration: const InputDecoration(
                      labelText: 'Operator token',
                    ),
                    onSubmitted: (_) => submit(),
                  ),
                  const SizedBox(height: 12),
                  const Text(
                    'The token stays in this session. Commands and snapshots are '
                    'saved locally for reconnects. Use HTTPS for remote servers.',
                    style: TextStyle(color: Color(0xff52616c), fontSize: 12),
                  ),
                  if (error != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 12),
                      child: Text(
                        error!,
                        style: const TextStyle(color: Colors.red),
                      ),
                    ),
                  const SizedBox(height: 24),
                  FilledButton.icon(
                    key: const Key('connect'),
                    onPressed: submit,
                    icon: const Icon(Icons.login),
                    label: const Text('Open fleet'),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    ),
  );
}

class FleetDashboard extends StatefulWidget {
  const FleetDashboard({
    super.key,
    required this.controller,
    required this.onDisconnect,
  });
  final FleetController controller;
  final VoidCallback onDisconnect;
  @override
  State<FleetDashboard> createState() => _FleetDashboardState();
}

class _FleetDashboardState extends State<FleetDashboard> {
  String filter = '';
  bool showHistory = false;
  int visibleCount = 12;
  FleetController get controller => widget.controller;
  VoidCallback get onDisconnect => widget.onDisconnect;
  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: controller,
    builder: (context, _) {
      final now = controller.clock();
      final fresh = controller.devices.where((d) => !d.stale(now)).length;
      final pending = controller.commands.where((c) => !c.terminal).length;
      final filtered = controller.devices
          .where(
            (d) =>
                d.id.toLowerCase().contains(filter.toLowerCase()) ||
                d.name.toLowerCase().contains(filter.toLowerCase()),
          )
          .toList();
      return Scaffold(
        appBar: AppBar(
          title: const Text('Appliance Energy'),
          actions: [
            IconButton(
              tooltip: 'Refresh snapshots',
              onPressed: controller.busy ? null : controller.sync,
              icon: const Icon(Icons.refresh),
            ),
            IconButton(
              tooltip: 'Disconnect and clear session token',
              onPressed: onDisconnect,
              icon: const Icon(Icons.logout),
            ),
            const SizedBox(width: 12),
          ],
        ),
        body: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 1120),
            child: ListView(
              padding: const EdgeInsets.all(24),
              children: [
                Text(
                  'Fleet overview',
                  style: Theme.of(context).textTheme.headlineLarge,
                ),
                const SizedBox(height: 8),
                Text(
                  controller.server,
                  style: const TextStyle(color: Color(0xff52616c)),
                ),
                const SizedBox(height: 20),
                ConnectionBanner(controller: controller),
                const SizedBox(height: 20),
                Wrap(
                  spacing: 12,
                  runSpacing: 12,
                  children: [
                    MetricCard(
                      label: 'Devices',
                      value: controller.devices.length.toString(),
                      icon: Icons.devices,
                    ),
                    MetricCard(
                      label: 'Recent reports',
                      value: '$fresh',
                      icon: Icons.sensors,
                    ),
                    MetricCard(
                      label: 'Unresolved commands',
                      value: '$pending',
                      icon: Icons.pending_actions,
                    ),
                  ],
                ),
                const SizedBox(height: 24),
                SegmentedButton<bool>(
                  segments: const [
                    ButtonSegment(
                      value: false,
                      label: Text('Devices'),
                      icon: Icon(Icons.devices),
                    ),
                    ButtonSegment(
                      value: true,
                      label: Text('Commands'),
                      icon: Icon(Icons.receipt_long),
                    ),
                  ],
                  selected: {showHistory},
                  onSelectionChanged: (values) =>
                      setState(() => showHistory = values.single),
                ),
                const SizedBox(height: 20),
                if (!showHistory) ...[
                  TextField(
                    decoration: const InputDecoration(
                      labelText: 'Search devices',
                      prefixIcon: Icon(Icons.search),
                    ),
                    onChanged: (value) => setState(() {
                      filter = value;
                      visibleCount = 12;
                    }),
                  ),
                  const SizedBox(height: 16),
                  if (controller.devices.isEmpty)
                    const Card(
                      child: Padding(
                        padding: EdgeInsets.all(28),
                        child: Text(
                          'No device snapshots yet. Start the simulator and refresh. '
                          'If you are reconnecting offline, use the same server origin as before.',
                        ),
                      ),
                    ),
                  ...filtered
                      .take(visibleCount)
                      .map(
                        (device) => Padding(
                          padding: const EdgeInsets.only(bottom: 12),
                          child: Card(
                            child: ListTile(
                              contentPadding: const EdgeInsets.all(20),
                              leading: CircleAvatar(
                                backgroundColor: const Color(0xffd9eeef),
                                child: Icon(
                                  device.reported.power
                                      ? Icons.mode_fan_off_outlined
                                      : Icons.power_settings_new,
                                  color: const Color(0xff087f8c),
                                ),
                              ),
                              title: Text(
                                device.name,
                                style: Theme.of(context).textTheme.titleLarge,
                              ),
                              subtitle: Padding(
                                padding: const EdgeInsets.only(top: 8),
                                child: Text(
                                  '${device.id}  ·  ${statusLabel(device.status)}\nDesired r${device.desiredRevision} / reported r${device.reportedRevision}  ·  ${device.stale(now) ? 'Stale or unknown report' : 'Recent report'}',
                                ),
                              ),
                              isThreeLine: true,
                              trailing: const Icon(Icons.chevron_right),
                              onTap: () => Navigator.of(context).push(
                                MaterialPageRoute<void>(
                                  builder: (_) => DevicePage(
                                    controller: controller,
                                    deviceId: device.id,
                                  ),
                                ),
                              ),
                            ),
                          ),
                        ),
                      ),
                  if (filtered.length > visibleCount)
                    TextButton(
                      onPressed: () => setState(() => visibleCount += 12),
                      child: const Text('Show more devices'),
                    ),
                  if (filtered.isEmpty && controller.devices.isNotEmpty)
                    const Text('No devices match this search.'),
                ],
                if (showHistory) ...[
                  const SizedBox(height: 20),
                  Text(
                    'Command history',
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                  const SizedBox(height: 10),
                  if (controller.commands.isEmpty)
                    const Text('No commands on this client yet.'),
                  ...controller.commands
                      .take(30)
                      .map((c) => CommandCard(command: c)),
                ],
              ],
            ),
          ),
        ),
      );
    },
  );
}

class ConnectionBanner extends StatelessWidget {
  const ConnectionBanner({super.key, required this.controller});
  final FleetController controller;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(
      color: controller.online
          ? const Color(0xffdff1eb)
          : const Color(0xffffedcd),
      borderRadius: BorderRadius.circular(12),
    ),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(
          controller.online
              ? Icons.cloud_done_outlined
              : Icons.cloud_off_outlined,
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Text(
            controller.error ??
                (controller.online
                    ? 'Server connected · ${controller.live ? 'live channel + snapshot repair' : 'snapshot polling'}\nLast snapshot: ${timeLabel(controller.lastSync)}'
                    : 'Connecting. Cached reports may be stale.'),
          ),
        ),
        if (controller.busy)
          const SizedBox(
            width: 18,
            height: 18,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
      ],
    ),
  );
}

class MetricCard extends StatelessWidget {
  const MetricCard({
    super.key,
    required this.label,
    required this.value,
    required this.icon,
  });
  final String label, value;
  final IconData icon;
  @override
  Widget build(BuildContext context) => SizedBox(
    width: 240,
    child: Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Row(
          children: [
            Icon(icon, color: const Color(0xff087f8c), size: 30),
            const SizedBox(width: 18),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    value,
                    style: Theme.of(context).textTheme.headlineMedium,
                  ),
                  Text(label),
                ],
              ),
            ),
          ],
        ),
      ),
    ),
  );
}

class DevicePage extends StatefulWidget {
  const DevicePage({
    super.key,
    required this.controller,
    required this.deviceId,
  });
  final FleetController controller;
  final String deviceId;
  @override
  State<DevicePage> createState() => _DevicePageState();
}

class _DevicePageState extends State<DevicePage> {
  Device? draftBasis;
  bool power = false, submitting = false;
  double speed = 0;
  String? error;
  List<Reading> readings = [];
  bool readingBusy = false;
  String? readingError;
  Timer? timer;
  @override
  void initState() {
    super.initState();
    final matches = widget.controller.devices.where(
      (d) => d.id == widget.deviceId,
    );
    if (matches.isNotEmpty) {
      useSnapshot(matches.first);
    }
    unawaited(loadReadings());
    timer = Timer.periodic(
      const Duration(seconds: 10),
      (_) => unawaited(loadReadings()),
    );
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  void useSnapshot(Device d) {
    draftBasis = d;
    power = d.desired.power;
    speed = d.desired.speed.toDouble();
  }

  Future<void> loadReadings() async {
    if (readingBusy) {
      return;
    }
    readingBusy = true;
    try {
      final result = await widget.controller.readings(widget.deviceId);
      result.sort((a, b) => b.time.compareTo(a.time));
      if (mounted) {
        setState(() {
          readings = result;
          readingError = null;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(
          () => readingError =
              'Telemetry unavailable. Existing rows may be stale.',
        );
      }
    } finally {
      readingBusy = false;
    }
  }

  Future<void> submit() async {
    if (draftBasis == null) {
      return;
    }
    setState(() {
      submitting = true;
      error = null;
    });
    try {
      await widget.controller.enqueue(
        draftBasis!,
        Setpoint(power, speed.round()),
      );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
              'Command saved. Confirmation follows the device report.',
            ),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        setState(
          () => error = e is StateError
              ? e.message.toString()
              : 'Unable to persist command. Nothing was dispatched.',
        );
      }
    } finally {
      if (mounted) {
        setState(() => submitting = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: widget.controller,
    builder: (context, _) {
      final controller = widget.controller;
      final matches = controller.devices.where((d) => d.id == widget.deviceId);
      if (matches.isEmpty) {
        return const Scaffold(
          body: Center(child: Text('Device snapshot unavailable.')),
        );
      }
      final device = matches.first;
      final changed = draftBasis?.desiredRevision != device.desiredRevision;
      final blocked = controller.commands.any(
        (c) => c.deviceId == device.id && c.blocksNewCommand,
      );
      return Scaffold(
        appBar: AppBar(title: Text(device.name)),
        body: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 960),
            child: ListView(
              padding: const EdgeInsets.all(24),
              children: [
                ConnectionBanner(controller: controller),
                const SizedBox(height: 20),
                Text(
                  device.id,
                  style: Theme.of(context).textTheme.headlineMedium,
                ),
                const SizedBox(height: 8),
                Text(
                  '${device.stale(controller.clock()) ? 'Stale / unknown observation' : 'Recent observation'} · Last seen ${timeLabel(device.lastSeen)}',
                ),
                const SizedBox(height: 16),
                Wrap(
                  spacing: 12,
                  runSpacing: 12,
                  children: [
                    StateCard(
                      title: 'Desired',
                      value: device.desired,
                      revision: device.desiredRevision,
                    ),
                    StateCard(
                      title: 'Reported',
                      value: device.reported,
                      revision: device.reportedRevision,
                    ),
                  ],
                ),
                const SizedBox(height: 20),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Text(
                          'Set an absolute state',
                          style: Theme.of(context).textTheme.titleLarge,
                        ),
                        const SizedBox(height: 8),
                        Text(
                          'Draft uses revision ${draftBasis?.desiredRevision.toString() ?? '?'}. Lifetime: 2 minutes. A queued command is an intent, not a device confirmation.',
                        ),
                        SwitchListTile(
                          contentPadding: EdgeInsets.zero,
                          title: const Text('Power'),
                          value: power,
                          onChanged: blocked || submitting
                              ? null
                              : (v) => setState(() => power = v),
                        ),
                        Text('Fan speed: ${speed.round()}%'),
                        Slider(
                          value: speed,
                          max: 100,
                          divisions: 20,
                          label: '${speed.round()}%',
                          onChanged: blocked || submitting
                              ? null
                              : (v) => setState(() => speed = v),
                        ),
                        if (changed) ...[
                          const Text(
                            'The desired revision changed. Review the latest snapshot before sending.',
                            style: TextStyle(color: Color(0xff9b5700)),
                          ),
                          Align(
                            alignment: Alignment.centerLeft,
                            child: TextButton(
                              onPressed: () =>
                                  setState(() => useSnapshot(device)),
                              child: const Text('Use latest snapshot'),
                            ),
                          ),
                        ],
                        if (blocked)
                          const Text(
                            'An earlier command is unresolved. Retry reconciliation below; '
                            'its ID, expected revision and deadline will stay unchanged.',
                          ),
                        if (error != null)
                          Text(
                            error!,
                            style: const TextStyle(color: Colors.red),
                          ),
                        const SizedBox(height: 14),
                        FilledButton.icon(
                          onPressed: changed || blocked || submitting
                              ? null
                              : submit,
                          icon: const Icon(Icons.send_outlined),
                          label: Text(
                            controller.online
                                ? 'Save and send command'
                                : 'Queue command locally',
                          ),
                        ),
                        const SizedBox(height: 8),
                        TextButton(
                          onPressed: controller.busy ? null : controller.sync,
                          child: const Text(
                            'Refresh and reconcile original commands',
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 20),
                Text(
                  'Recent energy telemetry',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                const SizedBox(height: 8),
                const Text(
                  'Event samples, not a gap-filled energy total. Source labels are preserved.',
                ),
                if (readingError != null)
                  Text(
                    readingError!,
                    style: const TextStyle(color: Color(0xff9b5700)),
                  ),
                if (readings.isEmpty)
                  const Padding(
                    padding: EdgeInsets.all(20),
                    child: Text('No readings available yet.'),
                  ),
                if (readings.isNotEmpty)
                  Card(
                    child: SingleChildScrollView(
                      scrollDirection: Axis.horizontal,
                      child: DataTable(
                        columns: const [
                          DataColumn(label: Text('Time (local)')),
                          DataColumn(label: Text('Power W')),
                          DataColumn(label: Text('Boot counter Wh')),
                          DataColumn(label: Text('Source')),
                        ],
                        rows: readings
                            .take(8)
                            .map(
                              (r) => DataRow(
                                cells: [
                                  DataCell(Text(timeLabel(r.time))),
                                  DataCell(Text(r.watts.toStringAsFixed(2))),
                                  DataCell(Text(r.totalWh.toStringAsFixed(3))),
                                  DataCell(Text(r.source)),
                                ],
                              ),
                            )
                            .toList(),
                      ),
                    ),
                  ),
                const SizedBox(height: 24),
                Text(
                  'Commands for this device',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                const SizedBox(height: 8),
                ...controller.commands
                    .where((c) => c.deviceId == device.id)
                    .take(20)
                    .map((c) => CommandCard(command: c)),
              ],
            ),
          ),
        ),
      );
    },
  );
}

class StateCard extends StatelessWidget {
  const StateCard({
    super.key,
    required this.title,
    required this.value,
    required this.revision,
  });
  final String title;
  final Setpoint value;
  final int revision;
  @override
  Widget build(BuildContext context) => SizedBox(
    width: 300,
    child: Card(
      child: Padding(
        padding: const EdgeInsets.all(22),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '$title · r$revision',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 12),
            Text(
              value.power ? 'ON' : 'OFF',
              style: Theme.of(context).textTheme.headlineMedium,
            ),
            Text('Speed ${value.speed}%'),
          ],
        ),
      ),
    ),
  );
}

class CommandCard extends StatelessWidget {
  const CommandCard({super.key, required this.command});
  final PendingCommand command;
  @override
  Widget build(BuildContext context) {
    final positive = command.status == 'confirmed';
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  positive
                      ? Icons.check_circle_outline
                      : Icons.receipt_long_outlined,
                  color: positive
                      ? const Color(0xff087f67)
                      : const Color(0xff9b5700),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    '${command.deviceId} · ${statusLabel(command.status)}',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Semantics(
              label: 'Command ID: ${command.id}',
              excludeSemantics: true,
              child: SelectableText(
                command.id,
                style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
              ),
            ),
            Text(
              '${command.desired.power ? 'ON' : 'OFF'} · ${command.desired.speed}% · expected r${command.expectedRevision} · dispatch attempts ${command.attempts}',
            ),
            Text('Expires ${timeLabel(command.expiresAt)}'),
            if (command.message.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(command.message),
              ),
            if (command.status == 'outcome_unknown' ||
                command.status == 'expired_unconfirmed')
              const Text(
                'Unknown outcome does not mean the device did nothing.',
                style: TextStyle(fontWeight: FontWeight.w600),
              ),
          ],
        ),
      ),
    );
  }
}

String statusLabel(String value) => value.replaceAll('_', ' ');
String timeLabel(DateTime? value) {
  if (value == null) {
    return 'never';
  }
  final local = value.toLocal();
  String two(int n) => n.toString().padLeft(2, '0');
  return '${local.year}-${two(local.month)}-${two(local.day)} ${two(local.hour)}:${two(local.minute)}:${two(local.second)}';
}
