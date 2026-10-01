import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:appliance_energy/api.dart';
import 'package:appliance_energy/controller.dart';
import 'package:appliance_energy/models.dart';
import 'package:appliance_energy/store.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

Device sampleDevice({int revision = 4, DateTime? lastSeen}) => Device(
  id: 'fan-1',
  name: 'Studio fan',
  desiredRevision: revision,
  reportedRevision: 3,
  desired: const Setpoint(false, 0),
  reported: const Setpoint(false, 0),
  lastSeen: lastSeen,
  status: 'awaiting_device',
);

class FakeApi implements FleetApi {
  Device device = sampleDevice();
  bool unavailable = false;
  bool acceptThenTimeout = false;
  int? sendError;
  final receipts = <String, Map<String, dynamic>>{};
  final sent = <Map<String, dynamic>>[];
  @override
  Future<List<Device>> devices() async {
    if (unavailable) {
      throw const SocketException('offline');
    }
    return [device];
  }

  @override
  Future<Map<String, dynamic>?> receipt(String id) async => receipts[id];
  @override
  Future<Map<String, dynamic>> send(PendingCommand command) async {
    sent.add(jsonDecode(jsonEncode(command.payload)) as Map<String, dynamic>);
    if (sendError != null) {
      throw ApiFailure(sendError!, 'Rejected');
    }
    final value = <String, dynamic>{
      'command_id': command.id,
      'status': 'confirmed',
      'revision': command.expectedRevision + 1,
    };
    receipts[command.id] = value;
    if (acceptThenTimeout) {
      throw TimeoutException('response lost');
    }
    return value;
  }

  @override
  Future<List<Reading>> readings(String deviceId) async => [];
  @override
  void close() {}
}

Future<void> settle(FleetController controller) async {
  for (var i = 0; i < 300 && controller.busy; i++) {
    await Future<void>.delayed(const Duration(milliseconds: 5));
  }
  expect(
    controller.busy,
    false,
    reason: 'Controller should finish bounded reconciliation.',
  );
}

void main() {
  sqfliteFfiInit();
  late LocalStore store;
  late FakeApi api;
  late DateTime now;
  late FleetController controller;
  setUp(() async {
    store = await LocalStore.open(databaseFactoryFfi, inMemoryDatabasePath);
    api = FakeApi();
    now = DateTime.utc(2026, 10, 1, 10);
    controller = FleetController(
      server: 'http://127.0.0.1:8080',
      token: 'test-token',
      store: store,
      api: api,
      clock: () => now,
      newId: () => 'e51e0d39-cd48-4fab-96c1-20d07dc9b35f',
      enableLive: false,
    );
  });
  tearDown(() async {
    controller.dispose();
    await store.close();
  });

  test(
    'dispatch intent is durable and lost response reconciles without sending twice',
    () async {
      await controller.start();
      api.acceptThenTimeout = true;
      final command = await controller.enqueue(
        controller.devices.single,
        const Setpoint(true, 60),
      );
      await settle(controller);
      expect(controller.commands.single.status, 'delivery_unknown');
      expect((await store.commands(controller.server)).single.attempts, 1);
      await controller.sync();
      expect(controller.commands.single.status, 'confirmed');
      expect(api.sent, hasLength(1));
      expect(api.sent.single['command_id'], command.id);
    },
  );

  test(
    'conflicting command preserves revision and does not retry or rebase',
    () async {
      await controller.start();
      api.sendError = 409;
      final basis = controller.devices.single;
      api.device = sampleDevice(revision: 9);
      await controller.enqueue(basis, const Setpoint(true, 40));
      await settle(controller);
      expect(api.sent.single['expected_revision'], 4);
      expect(controller.commands.single.status, 'conflict');
      await controller.sync();
      expect(api.sent, hasLength(1));
      expect(controller.devices.single.desiredRevision, 9);
    },
  );

  test(
    'offline command survives and expires without ever dispatching',
    () async {
      await controller.start();
      api.unavailable = true;
      final command = await controller.enqueue(
        controller.devices.single,
        const Setpoint(true, 20),
      );
      await settle(controller);
      expect((await store.commands(controller.server)).single.id, command.id);
      expect(api.sent, isEmpty);
      now = now.add(const Duration(minutes: 3));
      api.unavailable = false;
      await controller.sync();
      expect(controller.commands.single.status, 'expired');
      expect(api.sent, isEmpty);
    },
  );

  test(
    'expired uncertain dispatch remains unknown; an existing receipt wins over expiry',
    () async {
      await controller.start();
      api.sendError = 503;
      await controller.enqueue(
        controller.devices.single,
        const Setpoint(true, 80),
      );
      await settle(controller);
      expect(controller.commands.single.status, 'delivery_unknown');
      now = now.add(const Duration(minutes: 3));
      await controller.sync();
      expect(controller.commands.single.status, 'expired_unconfirmed');
      final id = controller.commands.single.id;
      api.receipts[id] = {'status': 'confirmed', 'revision': 5};
      await controller.sync();
      expect(controller.commands.single.status, 'confirmed');
      expect(api.sent, hasLength(1));
    },
  );

  test(
    'retry after ambiguous failure uses byte-equivalent command payload',
    () async {
      await controller.start();
      api.sendError = 503;
      await controller.enqueue(
        controller.devices.single,
        const Setpoint(true, 55),
      );
      await settle(controller);
      api.sendError = null;
      await controller.sync();
      expect(api.sent, hasLength(2));
      expect(api.sent[1], api.sent[0]);
      expect(controller.commands.single.status, 'confirmed');
    },
  );

  test(
    'one unresolved command per device and namespaces isolate server queues',
    () async {
      await controller.start();
      api.unavailable = true;
      await controller.enqueue(
        controller.devices.single,
        const Setpoint(true, 50),
      );
      await settle(controller);
      await expectLater(
        controller.enqueue(controller.devices.single, const Setpoint(false, 0)),
        throwsStateError,
      );
      expect(await store.commands('https://other.example'), isEmpty);
      expect(await store.devices('https://other.example'), isEmpty);
    },
  );

  test(
    'SQLite reopen retains immutable ID, expiry, revision and snapshots',
    () async {
      final directory = await Directory.systemTemp.createTemp(
        'appliance-store-test-',
      );
      final path = '${directory.path}/queue.db';
      final first = await LocalStore.open(databaseFactoryFfi, path);
      final command = PendingCommand(
        id: 'persisted-id',
        deviceId: 'fan-1',
        expectedRevision: 7,
        desired: const Setpoint(true, 75),
        createdAt: now,
        expiresAt: now.add(const Duration(minutes: 2)),
        status: 'delivery_unknown',
        attempts: 1,
      );
      await first.saveCommand('server-a', command);
      await first.saveDevices('server-a', [sampleDevice()]);
      await first.close();
      final second = await LocalStore.open(databaseFactoryFfi, path);
      expect(
        (await second.commands('server-a')).single.payload,
        command.payload,
      );
      expect(
        (await second.commands('server-a')).single.status,
        'delivery_unknown',
      );
      expect((await second.devices('server-a')).single.id, 'fan-1');
      await second.close();
      await directory.delete(recursive: true);
    },
  );

  test('HTTP bearer is a header and does not appear in URLs', () async {
    final paths = <Uri>[];
    final client = MockClient((request) async {
      paths.add(request.url);
      expect(request.headers['Authorization'], 'Bearer not-a-real-secret');
      return http.Response('[]', 200);
    });
    final httpApi = HttpFleetApi(
      Uri.parse('http://127.0.0.1:8080'),
      'not-a-real-secret',
      client: client,
    );
    await httpApi.devices();
    expect(paths.single.toString(), 'http://127.0.0.1:8080/api/devices');
    httpApi.close();
  });

  test('freshness rejects missing, old and future-skewed reports', () {
    expect(sampleDevice().stale(now), true);
    expect(
      sampleDevice(
        lastSeen: now.subtract(const Duration(seconds: 31)),
      ).stale(now),
      true,
    );
    expect(
      sampleDevice(lastSeen: now.add(const Duration(seconds: 6))).stale(now),
      true,
    );
    expect(
      sampleDevice(
        lastSeen: now.subtract(const Duration(seconds: 5)),
      ).stale(now),
      false,
    );
  });

  test(
    'server validation rejects URL tokens, credentials and non-TLS remote hosts',
    () {
      expect(
        validateServer('http://127.0.0.1:8080/').toString(),
        'http://127.0.0.1:8080',
      );
      for (final invalid in [
        'http://example.com',
        'https://a:b@example.com',
        'https://example.com?token=x',
        'https://example.com/#x',
        'https://example.com/api',
      ]) {
        expect(() => validateServer(invalid), throwsFormatException);
      }
    },
  );

  test(
    'real WebSocket authenticates in first frame and repairs snapshots on live event',
    () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final firstFrame = Completer<Map<String, dynamic>>();
      WebSocket? socket;
      var snapshots = 0;
      final subscription = server.listen((request) async {
        if (request.uri.path == '/ws') {
          expect(request.uri.query, isEmpty);
          socket = await WebSocketTransformer.upgrade(request);
          socket!.listen((data) {
            if (!firstFrame.isCompleted) {
              firstFrame.complete(
                jsonDecode(data as String) as Map<String, dynamic>,
              );
            }
          });
        } else {
          expect(request.headers.value('Authorization'), 'Bearer ws-test');
          snapshots++;
          request.response.headers.contentType = ContentType.json;
          request.response.write(jsonEncode([sampleDevice().toJson()]));
          await request.response.close();
        }
      });
      final liveController = FleetController(
        server: 'http://127.0.0.1:${server.port}',
        token: 'ws-test',
        store: store,
      );
      try {
        await liveController.start();
        final auth = await firstFrame.future.timeout(
          const Duration(seconds: 5),
        );
        expect(auth, {'type': 'authenticate', 'token': 'ws-test'});
        await settle(liveController);
        final baseline = snapshots;
        for (var i = 0; i < 100; i++) {
          socket!.add(
            jsonEncode({
              'type': 'device_updated',
              'device': sampleDevice().toJson(),
            }),
          );
        }
        for (var i = 0; i < 200 && snapshots <= baseline; i++) {
          await Future<void>.delayed(const Duration(milliseconds: 10));
        }
        expect(
          snapshots,
          baseline + 1,
          reason: "A burst should require one repair request.",
        );
        await settle(liveController);
      } finally {
        liveController.dispose();
        await socket?.close();
        await subscription.cancel();
        await server.close(force: true);
      }
    },
  );
}
