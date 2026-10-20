// Zugangsdaten: iOS-Keychain (flutter_secure_storage) bzw. unter Windows das lokale Admin-Token.
import 'dart:io';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class Credentials {
  Credentials._(this._storage);

  static const _kBase = 'jarvis_base_url';
  static const _kDevice = 'jarvis_device_id';
  static const _kRefresh = 'jarvis_refresh_token';
  static const _kHost = 'jarvis_host';

  // Keychain-Eintrag nur auf diesem Gerät, nach erster Entsperrung verfügbar (auch für Siri-Kurzbefehle).
  static const _ios = IOSOptions(accessibility: KeychainAccessibility.first_unlock_this_device);

  final FlutterSecureStorage _storage;
  String? baseUrl;
  String? deviceId;
  String? refreshToken;
  String? host;
  String? adminToken; // nur Windows-Desktop: lokales Admin-Token des laufenden Backends

  bool get isAdmin => adminToken != null;
  bool get isPaired => isAdmin || (baseUrl != null && deviceId != null && refreshToken != null);

  static Future<Credentials> load() async {
    final c = Credentials._(const FlutterSecureStorage(iOptions: _ios));
    if (Platform.isWindows) {
      // Desktop-App auf demselben PC: lokales Admin-Token lesen (gilt nur für 127.0.0.1)
      final local = Platform.environment['LOCALAPPDATA'];
      final dataDir = Platform.environment['JARVIS_DATA_DIR'] ?? (local != null ? '$local\\Jarvis' : null);
      final f = dataDir == null ? null : File('$dataDir\\local_admin_token');
      if (f != null && f.existsSync()) {
        c.adminToken = f.readAsStringSync().trim();
        c.baseUrl = 'http://127.0.0.1:${Platform.environment['JARVIS_PORT'] ?? '8765'}';
        c.host = Platform.localHostname;
        return c;
      }
    }
    c.baseUrl = await c._storage.read(key: _kBase);
    c.deviceId = await c._storage.read(key: _kDevice);
    c.refreshToken = await c._storage.read(key: _kRefresh);
    c.host = await c._storage.read(key: _kHost);
    return c;
  }

  Future<void> savePairing({required String baseUrl, required String deviceId, required String refresh, required String host}) async {
    this.baseUrl = baseUrl;
    this.deviceId = deviceId;
    refreshToken = refresh;
    this.host = host;
    await _storage.write(key: _kBase, value: baseUrl);
    await _storage.write(key: _kDevice, value: deviceId);
    await _storage.write(key: _kRefresh, value: refresh);
    await _storage.write(key: _kHost, value: host);
  }

  Future<void> saveRefresh(String refresh) async {
    refreshToken = refresh;
    await _storage.write(key: _kRefresh, value: refresh);
  }

  Future<void> clear() async {
    baseUrl = deviceId = refreshToken = host = null;
    await _storage.deleteAll();
  }
}
