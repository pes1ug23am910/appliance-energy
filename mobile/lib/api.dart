import 'dart:convert';

import 'package:http/http.dart' as http;

import 'models.dart';

class ApiFailure implements Exception {
  const ApiFailure(this.status, this.message);
  final int status;
  final String message;
  @override
  String toString() => message;
}

abstract class FleetApi {
  Future<List<Device>> devices();
  Future<Map<String, dynamic>?> receipt(String id);
  Future<Map<String, dynamic>> send(PendingCommand command);
  Future<List<Reading>> readings(String deviceId);
  void close();
}

class HttpFleetApi implements FleetApi {
  HttpFleetApi(this.base, this.token, {http.Client? client})
    : _client = client ?? http.Client();
  final Uri base;
  final String token;
  final http.Client _client;
  Map<String, String> get _headers => {
    'Authorization': 'Bearer $token',
    'Content-Type': 'application/json',
  };
  Uri endpoint(String path) => base.resolve(path);
  Future<dynamic> _request(
    String path, {
    Map<String, dynamic>? data,
    bool nullable = false,
  }) async {
    final response =
        await (data == null
                ? _client.get(endpoint(path), headers: _headers)
                : _client.post(
                    endpoint(path),
                    headers: _headers,
                    body: jsonEncode(data),
                  ))
            .timeout(const Duration(seconds: 8));
    if (nullable && response.statusCode == 404) {
      return null;
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiFailure(response.statusCode, switch (response.statusCode) {
        401 || 403 => 'Authentication failed. Check your operator token.',
        409 =>
          'Revision or command identity conflict. Review current state before creating a new command.',
        400 || 422 => 'Command rejected by server validation.',
        _ => 'Server request failed (${response.statusCode}).',
      });
    }
    return jsonDecode(response.body);
  }

  @override
  Future<List<Device>> devices() async =>
      (await _request('/api/devices') as List)
          .map((e) => Device.fromJson(Map<String, dynamic>.from(e as Map)))
          .toList();
  @override
  Future<Map<String, dynamic>?> receipt(String id) async {
    final result = await _request('/api/commands/$id', nullable: true);
    return result == null ? null : Map<String, dynamic>.from(result as Map);
  }

  @override
  Future<Map<String, dynamic>> send(PendingCommand command) async =>
      Map<String, dynamic>.from(
        await _request(
              '/api/devices/${command.deviceId}/commands',
              data: command.payload,
            )
            as Map,
      );
  @override
  Future<List<Reading>> readings(String deviceId) async =>
      (await _request('/api/devices/$deviceId/telemetry?limit=100') as List)
          .map((e) => Reading.fromJson(Map<String, dynamic>.from(e as Map)))
          .toList();
  @override
  void close() => _client.close();
}
