import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import '../../../app/app_config.dart';
import '../models/chat_models.dart';
import '../models/chat_stream.dart';

class ChatService {
  ChatService({http.Client? client})
    : _client = client ?? http.Client(),
      _ownsClient = client == null;

  final http.Client _client;
  final bool _ownsClient;

  ChatStreamHandle streamMessage({
    required String message,
    required String conversationId,
    required List<Map<String, String>> history,
    required List<String> documentIds,
    required ChatConnectorMode connectorMode,
    required List<String> connectorIds,
  }) {
    final requestClient = http.Client();
    final controller = StreamController<ChatStreamEvent>();
    var cancelled = false;

    Future<void>(() async {
      try {
        final request = http.Request('POST', _uri('/api/v1/agent/chat'))
          ..headers.addAll(<String, String>{
            ..._identityHeaders,
            'Accept': 'text/event-stream',
            'Content-Type': 'application/json',
          })
          ..body = jsonEncode(<String, dynamic>{
            'message': message,
            'conversation_id': conversationId,
            'history': history,
            'document_ids': documentIds,
            'connector_mode': connectorMode.name,
            'connector_ids': connectorMode == ChatConnectorMode.selected
                ? connectorIds
                      .map<Object>((id) => int.tryParse(id) ?? id)
                      .toList()
                : <Object>[],
          });
        final response = await requestClient.send(request);
        if (response.statusCode < 200 || response.statusCode >= 300) {
          final detail = await response.stream.bytesToString();
          throw ChatRequestException(
            detail.trim().isEmpty
                ? 'Chat request failed (${response.statusCode}).'
                : _errorDetail(detail),
          );
        }
        final contentType = response.headers['content-type'] ?? '';
        if (!contentType.toLowerCase().contains('text/event-stream')) {
          throw const ChatProtocolException(
            'Chat endpoint did not return an event stream.',
          );
        }
        await for (final line
            in response.stream
                .transform(utf8.decoder)
                .transform(const LineSplitter())) {
          if (cancelled) break;
          final trimmed = line.trim();
          if (!trimmed.startsWith('data:')) continue;
          final data = trimmed.substring(5).trim();
          if (data.isEmpty) continue;
          try {
            controller.add(ChatStreamEvent.decode(data));
          } on FormatException {
            throw const ChatProtocolException(
              'Received an invalid agent stream event.',
            );
          }
        }
      } catch (error, stackTrace) {
        if (!cancelled && !controller.isClosed) {
          controller.addError(_connectionError(error), stackTrace);
        }
      } finally {
        requestClient.close();
        if (!controller.isClosed) await controller.close();
      }
    });

    return ChatStreamHandle(
      events: controller.stream,
      cancel: () {
        cancelled = true;
        requestClient.close();
      },
    );
  }

  Future<List<ChatConnector>> getAvailableConnectors() async {
    final response = await _client.get(
      _uri('/api/v1/agent/connectors'),
      headers: _identityHeaders,
    );
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ChatRequestException(
        _errorDetail(
          response.body,
          fallback: 'Could not load permitted connectors.',
        ),
      );
    }
    final payload = jsonDecode(response.body);
    if (payload is! Map || payload['items'] is! List) return <ChatConnector>[];
    return (payload['items'] as List)
        .whereType<Map>()
        .map((item) => ChatConnector.fromJson(Map<String, dynamic>.from(item)))
        .toList();
  }

  Future<ConversationDocument> uploadDocument(
    UploadFile file, {
    required void Function(UploadProgress progress) onProgress,
  }) async {
    onProgress(UploadProgress.starting);
    final start = await _client.post(
      _uri('/api/v1/documents/uploads'),
      headers: <String, String>{
        ..._identityHeaders,
        'Content-Type': 'application/json',
        'Idempotency-Key': file.idempotencyKey,
      },
      body: jsonEncode(<String, dynamic>{
        'file_name': file.fileName,
        'content_type': file.contentType,
        'size_bytes': file.bytes.length,
      }),
    );
    if (start.statusCode < 200 || start.statusCode >= 300) {
      throw ChatRequestException(
        _errorDetail(start.body, fallback: 'Could not start document upload.'),
      );
    }
    final started = _jsonObject(start.body);
    final rawDocument = started['document'];
    if (rawDocument is! Map) {
      throw const ChatProtocolException(
        'Document upload did not return document metadata.',
      );
    }
    if (started['upload_required'] != true) {
      return _documentFromResponse(Map<String, dynamic>.from(rawDocument));
    }
    final target = started['target'];
    if (target is! Map) {
      throw const ChatProtocolException(
        'Document upload did not return a storage destination.',
      );
    }

    onProgress(UploadProgress.uploading);
    final targetMap = Map<String, dynamic>.from(target);
    final uploadRequest = http.Request(
      targetMap['method'] as String? ?? 'PUT',
      Uri.parse(targetMap['url'] as String),
    )..bodyBytes = file.bytes;
    final targetHeaders = targetMap['headers'];
    if (targetHeaders is Map) {
      uploadRequest.headers.addAll(
        targetHeaders.map(
          (key, value) => MapEntry(key.toString(), value.toString()),
        ),
      );
    }
    final upload = await _client.send(uploadRequest);
    if (upload.statusCode < 200 || upload.statusCode >= 300) {
      final detail = await upload.stream.bytesToString();
      throw ChatRequestException(
        _errorDetail(detail, fallback: 'Document storage rejected the upload.'),
      );
    }

    onProgress(UploadProgress.validating);
    final documentId = (rawDocument['id'] as String?) ?? '';
    final complete = await _client.post(
      _uri('/api/v1/documents/${Uri.encodeComponent(documentId)}/complete'),
      headers: _identityHeaders,
    );
    if (complete.statusCode < 200 || complete.statusCode >= 300) {
      throw ChatRequestException(
        _errorDetail(
          complete.body,
          fallback: 'Could not validate the uploaded document.',
        ),
      );
    }
    return _documentFromResponse(_jsonObject(complete.body));
  }

  Future<void> releaseDocument(String documentId) async {
    final response = await _client.delete(
      _uri('/api/v1/documents/${Uri.encodeComponent(documentId)}'),
      headers: _identityHeaders,
    );
    if (response.statusCode != 404 &&
        (response.statusCode < 200 || response.statusCode >= 300)) {
      throw ChatRequestException(
        _errorDetail(response.body, fallback: 'Could not remove the document.'),
      );
    }
  }

  Uri resolveSourceUrl(String value) {
    final uri = Uri.tryParse(value);
    if (uri != null && uri.hasScheme) return uri;
    return _uri(value.startsWith('/') ? value : '/$value');
  }

  void close() {
    if (_ownsClient) _client.close();
  }

  Uri _uri(String path) {
    final base = AppConfig.apiBaseUri;
    final basePath = base.path.endsWith('/')
        ? base.path.substring(0, base.path.length - 1)
        : base.path;
    return base.replace(path: '$basePath$path');
  }

  Map<String, String> get _identityHeaders => <String, String>{
    'X-Bothesis-User-Id': AppConfig.userId,
    'X-Bothesis-Tenant-Id': AppConfig.tenantId,
  };

  static Map<String, dynamic> _jsonObject(String value) {
    final decoded = jsonDecode(value);
    if (decoded is! Map) {
      throw const ChatProtocolException('Expected a JSON object from the API.');
    }
    return Map<String, dynamic>.from(decoded);
  }

  static Object _connectionError(Object error) {
    if (error is http.ClientException) {
      return ChatRequestException(
        'Could not reach the BoThesis API at ${AppConfig.apiBaseUrl}. '
        'Check that the backend is running and this device is on the same network.',
      );
    }
    return error;
  }

  static String _errorDetail(String value, {String? fallback}) {
    try {
      final decoded = jsonDecode(value);
      if (decoded is Map && decoded['detail'] is String) {
        return decoded['detail'] as String;
      }
    } on FormatException {
      if (value.trim().isNotEmpty) return value.trim();
    }
    return fallback ?? value.trim();
  }

  static ConversationDocument _documentFromResponse(
    Map<String, dynamic> value,
  ) {
    const directTypes = <String>{
      'application/pdf',
      'image/png',
      'image/jpeg',
      'image/webp',
      'image/gif',
    };
    final size = value['size_bytes'] as int? ?? 0;
    final contentType =
        value['content_type'] as String? ?? 'application/octet-stream';
    return ConversationDocument(
      id: value['id'] as String,
      fileName: value['file_name'] as String? ?? 'Document',
      contentType: contentType,
      sizeBytes: size,
      mode: size <= 20 * 1024 * 1024 && directTypes.contains(contentType)
          ? 'direct'
          : 'indexed',
      status: value['upload_status'] == 'available' ? 'available' : 'failed',
    );
  }
}

class ChatStreamHandle {
  const ChatStreamHandle({required this.events, required this.cancel});

  final Stream<ChatStreamEvent> events;
  final void Function() cancel;
}

enum UploadProgress { starting, uploading, validating, ready, failed }

class UploadFile {
  const UploadFile({
    required this.fileName,
    required this.contentType,
    required this.bytes,
    required this.idempotencyKey,
  });

  final String fileName;
  final String contentType;
  final Uint8List bytes;
  final String idempotencyKey;
}

class ChatRequestException implements Exception {
  const ChatRequestException(this.message);

  final String message;

  @override
  String toString() => message;
}

class ChatProtocolException extends ChatRequestException {
  const ChatProtocolException(super.message);
}
