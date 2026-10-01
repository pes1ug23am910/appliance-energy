import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:path_provider/path_provider.dart';

import 'store.dart';

Future<LocalStore> openLocalStore() async {
  sqfliteFfiInit();
  final directory = await getApplicationSupportDirectory();
  await directory.create(recursive: true);
  return LocalStore.open(
    databaseFactoryFfi,
    '${directory.path}/appliance_energy.db',
  );
}
