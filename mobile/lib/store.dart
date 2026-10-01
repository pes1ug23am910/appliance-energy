import 'dart:convert';

import 'package:sqflite_common/sqlite_api.dart';

import 'models.dart';

class LocalStore {
  LocalStore(this.db);
  final Database db;
  static Future<LocalStore> open(DatabaseFactory factory, String path) async {
    final db = await factory.openDatabase(
      path,
      options: OpenDatabaseOptions(
        version: 1,
        onCreate: (db, version) async {
          await db.execute(
            'CREATE TABLE commands (server TEXT NOT NULL, id TEXT NOT NULL, '
            'device_id TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL, '
            'status TEXT NOT NULL, attempts INTEGER NOT NULL, message TEXT NOT NULL, '
            'receipt_revision INTEGER, PRIMARY KEY(server,id))',
          );
          await db.execute(
            'CREATE TABLE snapshots (server TEXT NOT NULL, device_id TEXT NOT NULL, '
            'json TEXT NOT NULL, PRIMARY KEY(server,device_id))',
          );
        },
      ),
    );
    return LocalStore(db);
  }

  Future<void> saveCommand(String server, PendingCommand command) async {
    await db.insert(
      'commands',
      command.toRow(server),
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  Future<List<PendingCommand>> commands(String server) async => (await db.query(
    'commands',
    where: 'server = ?',
    whereArgs: [server],
    orderBy: 'created_at DESC',
  )).map(PendingCommand.fromRow).toList();
  Future<void> saveDevices(String server, List<Device> devices) async {
    await db.transaction((txn) async {
      await txn.delete('snapshots', where: 'server = ?', whereArgs: [server]);
      for (final d in devices) {
        await txn.insert('snapshots', {
          'server': server,
          'device_id': d.id,
          'json': jsonEncode(d.toJson()),
        });
      }
    });
  }

  Future<List<Device>> devices(String server) async =>
      (await db.query('snapshots', where: 'server = ?', whereArgs: [server]))
          .map(
            (r) => Device.fromJson(
              jsonDecode(r['json'] as String) as Map<String, dynamic>,
            ),
          )
          .toList();
  Future<void> close() => db.close();
}
