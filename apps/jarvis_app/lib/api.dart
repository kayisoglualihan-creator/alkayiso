// HTTP-Client für die JARVIS-API inkl. Token-Erneuerung und Offline-Erkennung.
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import 'credentials.dart';

/// Der PC (Jarvis-Backend) ist nicht erreichbar – ausgeschaltet, Ruhezustand oder kein Tailscale.
class PcOfflineException implements Exception {
  final String message;
  PcOfflineException([this.message = 'PC offline']);
  @override
  String toString() => message;
}

class ApiException implements Exception {
  final int status;
  final String code;
  final String message;
  ApiException(this.status, this.code, this.message);
  @override
  String toString() => message;
}

/// Statusbezeichnungen für Fernaufträge (identisch zur Web-App).
const jobStatusLabel = {
  'pending': 'Wartend',
  'approval_required': 'Genehmigung erforderlich',
  'running': 'In Bearbeitung',
  'succeeded': 'Erfolgreich',
  'failed': 'Fehlgeschlagen',
  'cancelled': 'Abgebrochen',
  'offline': 'PC offline',
};

class JarvisApi {
  JarvisApi(this.creds, {http.Client? client}) : _http = client ?? http.Client();

  final Credentials creds;
  final http.Client _http;
  String? _access;
  double _accessExp = 0;

  /// Wird aufgerufen, wenn das Gerät widerrufen wurde (Kopplung lokal entfernen).
  void Function(String message)? onRevoked;

  String get baseUrl => creds.baseUrl!;

  Uri _uri(String path, [Map<String, String>? query]) => Uri.parse('$baseUrl$path').replace(queryParameters: query);

  Future<String> _token() async {
    if (creds.isAdmin) return creds.adminToken!;
    final now = DateTime.now().millisecondsSinceEpoch / 1000;
    if (_access == null || _accessExp - 30 < now) await refresh();
    return _access!;
  }

  Future<void> refresh() async {
    final res = await _send(() => _http.post(_uri('/api/auth/refresh'),
        headers: {'content-type': 'application/json'},
        body: jsonEncode({'device_id': creds.deviceId, 'refresh_token': creds.refreshToken})));
    final body = _decode(res);
    if (res.statusCode >= 400) {
      final err = (body['error'] ?? {}) as Map;
      final code = '${err['code'] ?? 'refresh_failed'}';
      if (const {'device_revoked', 'refresh_invalid', 'refresh_expired'}.contains(code)) {
        onRevoked?.call('${err['message'] ?? 'Gerät nicht mehr gekoppelt'}');
      }
      throw ApiException(res.statusCode, code, '${err['message'] ?? 'Erneuerung fehlgeschlagen'}');
    }
    _access = body['access_token'] as String;
    _accessExp = (body['expires_at'] as num).toDouble();
    await creds.saveRefresh(body['refresh_token'] as String); // Rotation
  }

  void setInitialAccess(String token, double exp) {
    _access = token;
    _accessExp = exp;
  }

  Future<http.Response> _send(Future<http.Response> Function() fn, {Duration timeout = const Duration(seconds: 30)}) async {
    try {
      return await fn().timeout(timeout);
    } on SocketException catch (e) {
      throw PcOfflineException('PC nicht erreichbar (${e.message})');
    } on TimeoutException {
      throw PcOfflineException('Zeitüberschreitung – PC antwortet nicht');
    } on http.ClientException catch (e) {
      throw PcOfflineException('Verbindung fehlgeschlagen: ${e.message}');
    }
  }

  Map<String, dynamic> _decode(http.Response res) {
    try {
      final d = jsonDecode(utf8.decode(res.bodyBytes));
      return d is Map<String, dynamic> ? d : {'data': d};
    } catch (_) {
      return {};
    }
  }

  Future<dynamic> request(String method, String path,
      {Object? body, Map<String, String>? query, Duration timeout = const Duration(seconds: 30), bool retry = true}) async {
    final token = await _token();
    final headers = {'Authorization': 'Bearer $token', if (body != null) 'content-type': 'application/json'};
    final uri = _uri(path, query);
    final res = await _send(() {
      final req = http.Request(method, uri)..headers.addAll(headers);
      if (body != null) req.body = jsonEncode(body);
      return _http.send(req).then(http.Response.fromStream);
    }, timeout: timeout);
    final decoded = jsonDecode(utf8.decode(res.bodyBytes).isEmpty ? '{}' : utf8.decode(res.bodyBytes));
    if (res.statusCode >= 400) {
      final err = (decoded is Map ? decoded['error'] : null) as Map? ?? {};
      final code = '${err['code'] ?? 'error'}';
      if (res.statusCode == 401 && retry && !creds.isAdmin && (code == 'token_expired' || code == 'token_revoked')) {
        _access = null;
        return request(method, path, body: body, query: query, timeout: timeout, retry: false);
      }
      if (code == 'device_revoked') onRevoked?.call('${err['message']}');
      throw ApiException(res.statusCode, code, '${err['message'] ?? 'Fehler ${res.statusCode}'}');
    }
    return decoded;
  }

  Future<dynamic> get(String path, [Map<String, String>? q]) => request('GET', path, query: q);
  Future<dynamic> post(String path, [Object? body]) => request('POST', path, body: body ?? {});
  Future<dynamic> patch(String path, Object body) => request('PATCH', path, body: body);
  Future<dynamic> delete(String path) => request('DELETE', path);

  /// Öffentlicher Health-Check ohne Anmeldung – dient der Online/Offline-Erkennung.
  Future<bool> isOnline() async {
    try {
      final r = await _http.get(_uri('/api/health')).timeout(const Duration(seconds: 5));
      return r.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  Future<Map<String, dynamic>> submitJob(String text, {String? conversationId}) async =>
      Map<String, dynamic>.from(await post('/api/jobs', {'text': text, 'conversation_id': conversationId}));

  Future<Map<String, dynamic>> job(String id, {int wait = 0}) async => Map<String, dynamic>.from(
      await request('GET', '/api/jobs/$id', query: {'wait': '$wait'}, timeout: Duration(seconds: wait + 15)));

  Future<void> decide(String approvalId, bool approve, {String? confirmText}) =>
      post('/api/approvals/$approvalId', {'approve': approve, 'confirm_text': confirmText});

  /// WebSocket-URL für Live-Ereignisse.
  Future<Uri> wsUri() async {
    final t = await _token();
    final u = Uri.parse(baseUrl);
    return u.replace(scheme: u.scheme == 'https' ? 'wss' : 'ws', path: '/ws', queryParameters: {'token': t});
  }

  // ---------------------------------------------------------------- Kopplung
  static Future<Map<String, dynamic>> claim(String baseUrl, String pairingId, String code, String deviceName) async {
    final res = await http
        .post(Uri.parse('$baseUrl/api/pairing/claim'),
            headers: {'content-type': 'application/json'},
            body: jsonEncode({'pairing_id': pairingId, 'code': code, 'device_name': deviceName, 'platform': 'ios'}))
        .timeout(const Duration(seconds: 15));
    final body = jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
    if (res.statusCode >= 400) {
      final err = body['error'] as Map? ?? {};
      throw ApiException(res.statusCode, '${err['code']}', '${err['message']}');
    }
    return body;
  }

  static Future<Map<String, dynamic>> poll(String baseUrl, String pairingId, String claimSecret) async {
    final res = await http
        .post(Uri.parse('$baseUrl/api/pairing/poll'),
            headers: {'content-type': 'application/json'},
            body: jsonEncode({'pairing_id': pairingId, 'claim_secret': claimSecret}))
        .timeout(const Duration(seconds: 15));
    return jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
  }
}

/// Inhalt des Kopplungs-QR-Codes: `https://pc.tailnet.ts.net/#pair=<base64url(JSON)>`
class PairingPayload {
  final String url;
  final String pairingId;
  final String code;
  final String host;
  PairingPayload(this.url, this.pairingId, this.code, this.host);

  static PairingPayload? parse(String raw) {
    final idx = raw.indexOf('#pair=');
    if (idx < 0) return null;
    var enc = raw.substring(idx + 6).trim();
    enc = enc.padRight(enc.length + (4 - enc.length % 4) % 4, '=');
    try {
      final j = jsonDecode(utf8.decode(base64Url.decode(enc))) as Map<String, dynamic>;
      return PairingPayload('${j['url']}', '${j['pid']}', '${j['code']}', '${j['host'] ?? 'PC'}');
    } catch (_) {
      return null;
    }
  }
}
