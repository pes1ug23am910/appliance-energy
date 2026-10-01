import 'dart:io';

import 'package:sqflite/sqflite.dart' as mobile_sqlite;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:path_provider/path_provider.dart';

import 'store.dart';

Future<LocalStore> openLocalStore() async {
  final isMobile = Platform.isAndroid || Platform.isIOS;
  if (!isMobile) sqfliteFfiInit();
  final directory = await getApplicationSupportDirectory();
  await directory.create(recursive: true);
  return LocalStore.open(
    isMobile ? mobile_sqlite.databaseFactory : databaseFactoryFfi,
    '${directory.path}/appliance_energy.db',
  );
}
