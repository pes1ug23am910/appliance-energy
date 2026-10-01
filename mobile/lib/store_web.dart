import 'package:sqflite_common_ffi_web/sqflite_ffi_web.dart';

import 'store.dart';

Future<LocalStore> openLocalStore() =>
    LocalStore.open(databaseFactoryFfiWeb, 'appliance_energy_v1.db');
