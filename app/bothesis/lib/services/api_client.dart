import 'dart:convert';

import 'package:http/http.dart' as http;

import '../config/app_config.dart';

class ApiClient {
  ApiClient({Uri? baseUri, http.Client? client})
    : baseUri = baseUri ?? AppConfig.apiBaseUri,
      _client = client ?? http.Client(),
      _ownsClient = client == null;

  final Uri baseUri;
  final http.Client _client;
  final bool _ownsClient;

  Future<Map<String, dynamic>> getJson(String path) async {
    final response = await _client.get(_uriFor(path), headers: _headers);
    return _decodeJson(response);
  }

  Future<Map<String, dynamic>> postJson(
    String path, {
    required Map<String, dynamic> body,
  }) async {
    final response = await _client.post(
      _uriFor(path),
      headers: _headers,
      body: jsonEncode(body),
    );
    return _decodeJson(response);
  }

  void close() {
    if (_ownsClient) {
      _client.close();
    }
  }

  Uri _uriFor(String path) {
    final normalizedBasePath = baseUri.path.endsWith('/')
        ? baseUri.path
        : '${baseUri.path}/';
    final normalizedPath = path.startsWith('/') ? path.substring(1) : path;
    return baseUri.replace(path: '$normalizedBasePath$normalizedPath');
  }

  Map<String, String> get _headers => const {
    'Accept': 'application/json',
    'Content-Type': 'application/json',
  };

  Map<String, dynamic> _decodeJson(http.Response response) {
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException(response.statusCode, response.body);
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw const FormatException('Expected a JSON object from the API.');
    }
    return decoded;
  }
}

class ApiException implements Exception {
  const ApiException(this.statusCode, this.responseBody);

  final int statusCode;
  final String responseBody;

  @override
  String toString() => 'ApiException($statusCode)';
}
