import 'dart:convert';

class Setpoint {
  const Setpoint(this.power, this.speed);
  final bool power;
  final int speed;
  factory Setpoint.fromJson(Map<String, dynamic> json) => Setpoint(
    json['power'] as bool? ?? false,
    (json['speed_percent'] as num? ?? 0).toInt(),
  );
  Map<String, dynamic> toJson() => {'power': power, 'speed_percent': speed};
}

class Device {
  const Device({
    required this.id,
    required this.name,
    required this.desiredRevision,
    required this.reportedRevision,
    required this.desired,
    required this.reported,
    required this.lastSeen,
    required this.status,
  });
  final String id, name, status;
  final int desiredRevision, reportedRevision;
  final Setpoint desired, reported;
  final DateTime? lastSeen;
  bool stale(DateTime now) =>
      lastSeen == null ||
      now.difference(lastSeen!).inSeconds > 30 ||
      lastSeen!.difference(now).inSeconds > 5;
  factory Device.fromJson(Map<String, dynamic> json) => Device(
    id: json['device_id'] as String,
    name: json['name'] as String? ?? json['device_id'] as String,
    desiredRevision: (json['desired_revision'] as num).toInt(),
    reportedRevision: (json['reported_revision'] as num? ?? 0).toInt(),
    desired: Setpoint.fromJson(
      Map<String, dynamic>.from(json['desired'] as Map),
    ),
    reported: Setpoint.fromJson(
      Map<String, dynamic>.from(json['reported'] as Map),
    ),
    lastSeen: DateTime.tryParse(json['last_seen'] as String? ?? ''),
    status: json['status'] as String? ?? 'unknown',
  );
  Map<String, dynamic> toJson() => {
    'device_id': id,
    'name': name,
    'desired_revision': desiredRevision,
    'reported_revision': reportedRevision,
    'desired': desired.toJson(),
    'reported': reported.toJson(),
    'last_seen': lastSeen?.toUtc().toIso8601String(),
    'status': status,
  };
}

class PendingCommand {
  const PendingCommand({
    required this.id,
    required this.deviceId,
    required this.expectedRevision,
    required this.desired,
    required this.expiresAt,
    required this.createdAt,
    this.status = 'queued',
    this.attempts = 0,
    this.message = '',
    this.receiptRevision,
  });
  final String id, deviceId, status, message;
  final int expectedRevision, attempts;
  final int? receiptRevision;
  final Setpoint desired;
  final DateTime expiresAt, createdAt;
  bool get terminal => const {
    'confirmed',
    'expired',
    'superseded',
    'conflict',
    'rejected',
    'expired_unconfirmed',
    'outcome_unknown',
  }.contains(status);
  bool get blocksNewCommand => !terminal;
  Map<String, dynamic> get payload => {
    'command_id': id,
    'expected_revision': expectedRevision,
    'desired': desired.toJson(),
    'expires_at': expiresAt.toUtc().toIso8601String(),
  };
  PendingCommand change({
    String? status,
    int? attempts,
    String? message,
    int? revision,
  }) => PendingCommand(
    id: id,
    deviceId: deviceId,
    expectedRevision: expectedRevision,
    desired: desired,
    expiresAt: expiresAt,
    createdAt: createdAt,
    status: status ?? this.status,
    attempts: attempts ?? this.attempts,
    message: message ?? this.message,
    receiptRevision: revision ?? receiptRevision,
  );
  PendingCommand receipt(Map<String, dynamic> value) => change(
    status: value['status'] as String,
    revision: (value['revision'] as num?)?.toInt(),
    message: '',
  );
  Map<String, Object?> toRow(String server) => {
    'server': server,
    'id': id,
    'device_id': deviceId,
    'payload': jsonEncode(payload),
    'created_at': createdAt.toUtc().toIso8601String(),
    'status': status,
    'attempts': attempts,
    'message': message,
    'receipt_revision': receiptRevision,
  };
  factory PendingCommand.fromRow(Map<String, Object?> row) {
    final payload =
        jsonDecode(row['payload'] as String) as Map<String, dynamic>;
    return PendingCommand(
      id: row['id'] as String,
      deviceId: row['device_id'] as String,
      expectedRevision: payload['expected_revision'] as int,
      desired: Setpoint.fromJson(payload['desired'] as Map<String, dynamic>),
      expiresAt: DateTime.parse(payload['expires_at'] as String),
      createdAt: DateTime.parse(row['created_at'] as String),
      status: row['status'] as String,
      attempts: row['attempts'] as int,
      message: row['message'] as String,
      receiptRevision: row['receipt_revision'] as int?,
    );
  }
}

class Reading {
  Reading({
    required this.time,
    required this.watts,
    required this.totalWh,
    required this.source,
  });
  final DateTime time;
  final double watts, totalWh;
  final String source;
  factory Reading.fromJson(Map<String, dynamic> value) => Reading(
    time: DateTime.parse(value['event_time'] as String),
    watts: (value['power_w'] as num).toDouble(),
    totalWh: (value['energy_wh_total'] as num).toDouble(),
    source: value['source_kind'] as String,
  );
}
