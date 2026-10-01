import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:uuid/uuid.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'api.dart';
import 'models.dart';
import 'store.dart';

Uri validateServer(String value) {
  final uri = Uri.tryParse(value.trim());
  if (uri == null ||
      !const {'http', 'https'}.contains(uri.scheme) ||
      uri.host.isEmpty ||
      uri.userInfo.isNotEmpty ||
      uri.hasQuery ||
      uri.hasFragment ||
      (uri.path.isNotEmpty && uri.path != '/')) {
    throw const FormatException(
      'Use a server origin, such as http://127.0.0.1:8080.',
    );
  }
  if (uri.scheme != 'https' &&
      !const {'localhost', '127.0.0.1', '::1'}.contains(uri.host)) {
    throw const FormatException(
      'Remote servers require HTTPS. HTTP is allowed only on loopback.',
    );
  }
  return uri.replace(path: '');
}

class FleetController extends ChangeNotifier {
  FleetController({
    required this.server,
    required this.token,
    required this.store,
    FleetApi? api,
    DateTime Function()? clock,
    String Function()? newId,
    this.enableLive = true,
  }) : api = api ?? HttpFleetApi(Uri.parse(server), token),
       clock = clock ?? DateTime.now,
       newId = newId ?? const Uuid().v4;
  final String server, token;
  final LocalStore store;
  final FleetApi api;
  final DateTime Function() clock;
  final String Function() newId;
  final bool enableLive;
  List<Device> devices = [];
  List<PendingCommand> commands = [];
  bool online = false,
      busy = false,
      live = false,
      _closed = false,
      _connecting = false;
  String? error;
  DateTime? lastSync;
  Timer? _timer;
  Timer? _liveRepair;
  WebSocketChannel? _channel;

  void _notify() {
    if (!_closed) {
      notifyListeners();
    }
  }

  Future<void> start() async {
    devices = await store.devices(server);
    commands = await store.commands(server);
    _notify();
    if (enableLive) {
      _timer = Timer.periodic(const Duration(seconds: 5), (_) {
        _notify();
        unawaited(sync());
      });
    }
    await sync();
  }

  Future<void> _save(PendingCommand command) async {
    await store.saveCommand(server, command);
    commands = await store.commands(server);
    _notify();
  }

  Future<PendingCommand> enqueue(
    Device device,
    Setpoint desired, {
    Duration ttl = const Duration(minutes: 2),
  }) async {
    if (commands.any((c) => c.deviceId == device.id && c.blocksNewCommand)) {
      throw StateError('A command is still unresolved for this device.');
    }
    if (desired.speed < 0 || desired.speed > 100 || ttl <= Duration.zero) {
      throw ArgumentError('Invalid setpoint or command lifetime.');
    }
    final now = clock().toUtc();
    final command = PendingCommand(
      id: newId(),
      deviceId: device.id,
      expectedRevision: device.desiredRevision,
      desired: desired,
      expiresAt: now.add(ttl),
      createdAt: now,
    );
    await _save(command);
    unawaited(sync());
    return command;
  }

  Future<void> sync() async {
    if (busy || _closed) {
      return;
    }
    busy = true;
    _notify();
    try {
      for (final command in List<PendingCommand>.of(commands)) {
        if (!command.terminal && !clock().toUtc().isBefore(command.expiresAt)) {
          await _save(
            command.change(
              status: command.attempts == 0 ? 'expired' : 'expired_unconfirmed',
              message: command.attempts == 0
                  ? 'Expired locally before dispatch.'
                  : 'Deadline passed without confirmation. No further dispatch; receipt reconciliation continues.',
            ),
          );
        }
      }
      final snapshots = await api.devices();
      if (_closed) {
        return;
      }
      devices = snapshots;
      await store.saveDevices(server, devices);
      online = true;
      error = null;
      lastSync = clock().toUtc();
      for (final command in List<PendingCommand>.of(commands)) {
        if (_closed) {
          break;
        }
        if (!command.terminal ||
            command.status == 'expired_unconfirmed' ||
            command.status == 'outcome_unknown') {
          await reconcile(command);
        }
      }
      if (enableLive && !_closed) {
        unawaited(_connect());
      }
    } on ApiFailure catch (e) {
      online = false;
      error = e.message;
    } catch (_) {
      online = false;
      error =
          'Server unavailable. Saved state may be stale; queued commands remain on this device.';
    } finally {
      busy = false;
      _notify();
    }
  }

  Future<void> reconcile(PendingCommand original) async {
    var command = original;
    try {
      // Always ask for a receipt before retransmitting a possibly dispatched command.
      final receipt = await api.receipt(command.id);
      if (receipt != null) {
        await _save(command.receipt(receipt));
        return;
      }
      if (!clock().toUtc().isBefore(command.expiresAt)) {
        await _save(
          command.change(
            status: command.attempts == 0 ? 'expired' : 'expired_unconfirmed',
            message: command.attempts == 0
                ? 'Expired locally before dispatch.'
                : 'No server receipt found after expiry. No further dispatch; physical outcome is unconfirmed.',
          ),
        );
        return;
      }
      command = command.change(
        status: 'sending',
        attempts: command.attempts + 1,
        message: '',
      );
      // Persist dispatch intent before the network call, preserving identity and revision.
      await _save(command);
      final result = await api.send(command);
      await _save(command.receipt(result));
    } on ApiFailure catch (e) {
      if (e.status == 409) {
        await _save(command.change(status: 'conflict', message: e.message));
      } else if (e.status == 400 || e.status == 422) {
        await _save(command.change(status: 'rejected', message: e.message));
      } else if (e.status == 401 || e.status == 403) {
        rethrow;
      } else {
        await _unknown(command);
      }
    } catch (_) {
      await _unknown(command);
    }
  }

  Future<void> _unknown(PendingCommand command) async {
    final expired = !clock().toUtc().isBefore(command.expiresAt);
    await _save(
      command.change(
        status: expired
            ? (command.attempts == 0 ? 'expired' : 'expired_unconfirmed')
            : (command.attempts == 0 ? 'queued' : 'delivery_unknown'),
        message: expired
            ? 'Deadline passed. Dispatch has stopped; review reported state.'
            : 'Connection interrupted. The original ID and expected revision will be preserved.',
      ),
    );
  }

  Future<List<Reading>> readings(String deviceId) => api.readings(deviceId);

  Future<void> _connect() async {
    if (_closed || _connecting || _channel != null) {
      return;
    }
    _connecting = true;
    WebSocketChannel? channel;
    try {
      final base = Uri.parse(server);
      channel = WebSocketChannel.connect(
        base.replace(
          scheme: base.scheme == 'https' ? 'wss' : 'ws',
          path: '/ws',
        ),
      );
      _channel = channel;
      final current = channel;
      current.stream.listen(
        (event) {
          try {
            final message = jsonDecode(event as String) as Map<String, dynamic>;
            if (message['type'] == 'device_updated' ||
                message['type'] == 'command_updated') {
              // Coalesce fleet bursts while HTTP repairs omissions and ordering.
              _liveRepair ??= Timer(const Duration(seconds: 1), () {
                _liveRepair = null;
                unawaited(sync());
              });
            }
          } catch (_) {
            /* Invalid live frames cannot replace authoritative state. */
          }
        },
        onError: (Object _) => _lost(current),
        onDone: () => _lost(current),
      );
      await current.ready.timeout(const Duration(seconds: 8));
      if (_closed) {
        await current.sink.close();
        return;
      }
      current.sink.add(jsonEncode({'type': 'authenticate', 'token': token}));
      live = true;
      // Repair snapshots after subscribing as well as on every reconnect.
      unawaited(sync());
    } catch (_) {
      if (channel != null) {
        _lost(channel);
      }
    } finally {
      _connecting = false;
      _notify();
    }
  }

  void _lost(WebSocketChannel channel) {
    if (identical(_channel, channel)) {
      _channel = null;
      live = false;
      _notify();
    }
  }

  @override
  void dispose() {
    _closed = true;
    _timer?.cancel();
    _liveRepair?.cancel();
    unawaited(_channel?.sink.close());
    api.close();
    super.dispose();
  }
}
