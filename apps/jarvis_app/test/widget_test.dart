import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jarvis_app/api.dart';
import 'package:jarvis_app/app_state.dart';
import 'package:jarvis_app/credentials.dart';
import 'package:jarvis_app/widgets/jarvis_core.dart';

void main() {
  test('PairingPayload parst den QR-Link', () {
    final payload = {'v': 1, 'url': 'https://pc.tailnet.ts.net', 'pid': 'abc', 'code': 'xyz', 'host': 'PC'};
    final enc = base64Url.encode(utf8.encode(jsonEncode(payload))).replaceAll('=', '');
    final p = PairingPayload.parse('https://pc.tailnet.ts.net/#pair=$enc')!;
    expect(p.url, 'https://pc.tailnet.ts.net');
    expect(p.pairingId, 'abc');
    expect(p.code, 'xyz');
    expect(PairingPayload.parse('https://example.com'), isNull);
    expect(PairingPayload.parse('x#pair=!!!'), isNull);
  });

  test('Statusbezeichnungen vollständig', () {
    for (final s in ['pending', 'approval_required', 'running', 'succeeded', 'failed', 'offline']) {
      expect(jobStatusLabel.containsKey(s), isTrue);
    }
  });

  test('Offline wird als PcOfflineException gemeldet', () async {
    final client = MockClient((_) async => throw http.ClientException('Connection refused'));
    final api = JarvisApi(FakeCreds(), client: client);
    expect(await api.isOnline(), isFalse);
    expect(() => api.get('/api/status'), throwsA(isA<PcOfflineException>()));
  });

  test('API-Fehler werden mit Code geliefert', () async {
    final client = MockClient((_) async => http.Response(jsonEncode({'error': {'code': 'admin_required', 'message': 'Nur am PC'}}), 403));
    final api = JarvisApi(FakeCreds(), client: client);
    try {
      await api.get('/api/settings');
      fail('keine Exception');
    } on ApiException catch (e) {
      expect(e.code, 'admin_required');
      expect(e.status, 403);
    }
  });

  testWidgets('Jarvis-Core rendert in allen Zuständen', (tester) async {
    for (final s in CoreState.values) {
      await tester.pumpWidget(MaterialApp(home: Center(child: JarvisCore(state: s, size: 120))));
      await tester.pump(const Duration(milliseconds: 50));
      expect(find.byType(JarvisCore), findsOneWidget);
    }
  });
}

class FakeCreds implements Credentials {
  @override
  String? get baseUrl => 'http://127.0.0.1:1';
  @override
  bool get isAdmin => true;
  @override
  String? get adminToken => 'admintoken';
  @override
  dynamic noSuchMethod(Invocation invocation) => null;
}
