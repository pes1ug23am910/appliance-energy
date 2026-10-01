import 'package:appliance_energy/controller.dart';
import 'package:appliance_energy/main.dart';
import 'package:appliance_energy/store.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import 'reliability_test.dart' show FakeApi, sampleDevice;

void main() {
  testWidgets('connection form requires a token and keeps it obscured', (
    tester,
  ) async {
    String? connectedServer;
    await tester.pumpWidget(
      MaterialApp(
        theme: fleetTheme(),
        home: ConnectionScreen(
          onConnect: (server, token) => connectedServer = server,
        ),
      ),
    );
    await tester.tap(find.byKey(const Key('connect')));
    await tester.pump();
    expect(find.text('Enter the operator token.'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('token')), 'fixture-token');
    final field = tester.widget<TextField>(find.byKey(const Key('token')));
    expect(field.obscureText, true);
    await tester.tap(find.byKey(const Key('connect')));
    expect(connectedServer, 'http://127.0.0.1:18080');
  });

  testWidgets('dashboard distinguishes cached stale report and revisions', (
    tester,
  ) async {
    sqfliteFfiInit();
    final store = (await tester.runAsync(
      () => LocalStore.open(databaseFactoryFfi, inMemoryDatabasePath),
    ))!;
    final api = FakeApi();
    final controller = FleetController(
      server: 'http://127.0.0.1:8080',
      token: 'fixture-token',
      store: store,
      api: api,
      enableLive: false,
    );
    await tester.runAsync(controller.start);
    await tester.pumpWidget(
      MaterialApp(
        theme: fleetTheme(),
        home: FleetDashboard(controller: controller, onDisconnect: () {}),
      ),
    );
    expect(find.text('Fleet overview'), findsOneWidget);
    expect(find.textContaining('Desired r4 / reported r3'), findsOneWidget);
    expect(find.textContaining('Stale or unknown report'), findsOneWidget);
    expect(find.text('fixture-token'), findsNothing);
    await tester.pumpWidget(const SizedBox.shrink());
    controller.dispose();
    await tester.runAsync(store.close);
  });

  testWidgets('device editor requires explicit review when revision changes', (
    tester,
  ) async {
    sqfliteFfiInit();
    final store = (await tester.runAsync(
      () => LocalStore.open(databaseFactoryFfi, inMemoryDatabasePath),
    ))!;
    final api = FakeApi();
    final controller = FleetController(
      server: 'http://127.0.0.1:8080',
      token: 'fixture-token',
      store: store,
      api: api,
      enableLive: false,
    );
    await tester.runAsync(controller.start);
    await tester.pumpWidget(
      MaterialApp(
        theme: fleetTheme(),
        home: DevicePage(controller: controller, deviceId: 'fan-1'),
      ),
    );
    await tester.pumpAndSettle();
    api.device = sampleDevice(revision: 8);
    await tester.runAsync(controller.sync);
    await tester.pump();
    expect(find.text('Use latest snapshot'), findsOneWidget);
    final button = tester.widget<FilledButton>(
      find.widgetWithText(FilledButton, 'Save and send command'),
    );
    expect(button.onPressed, isNull);
    await tester.ensureVisible(find.text('Use latest snapshot'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Use latest snapshot'));
    await tester.pump();
    expect(find.textContaining('Draft uses revision 8.'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
    controller.dispose();
    await tester.runAsync(store.close);
  });
}
