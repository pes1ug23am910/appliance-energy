import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'package:appliance_energy/models.dart';
import 'package:appliance_energy/store_native.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets(
    'native SQLite retains uncertain command identity and origin isolation',
    (tester) async {
      const origin = 'https://native-store-test.invalid';
      const otherOrigin = 'https://other-native-store-test.invalid';
      var store = await openLocalStore();
      final now = DateTime.utc(2026, 1, 1);
      final command = PendingCommand(
        id: '00000000-0000-4000-8000-000000000123',
        deviceId: 'native-device',
        expectedRevision: 4294967296,
        desired: const Setpoint(true, 65),
        expiresAt: now.add(const Duration(minutes: 5)),
        createdAt: now,
        status: 'delivery_unknown',
        attempts: 1,
      );
      try {
        await store.db.delete(
          'commands',
          where: 'server IN (?, ?)',
          whereArgs: [origin, otherOrigin],
        );
        await store.saveCommand(origin, command);
        await store.close();
        store = await openLocalStore();
        final recovered = (await store.commands(origin)).single;
        expect(recovered.id, command.id);
        expect(recovered.payload, command.payload);
        expect(recovered.expectedRevision, 4294967296);
        expect(recovered.status, 'delivery_unknown');
        expect(recovered.attempts, 1);
        expect(await store.commands(otherOrigin), isEmpty);
        await store.saveCommand(
          origin,
          recovered.change(status: 'confirmed', revision: 4294967297),
        );
        await store.close();
        store = await openLocalStore();
        final confirmed = (await store.commands(origin)).single;
        expect(confirmed.status, 'confirmed');
        expect(confirmed.receiptRevision, 4294967297);
        expect(confirmed.payload, command.payload);
      } finally {
        await store.db.delete(
          'commands',
          where: 'server IN (?, ?)',
          whereArgs: [origin, otherOrigin],
        );
        await store.close();
      }
    },
  );
}
