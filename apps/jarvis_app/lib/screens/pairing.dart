// Kopplung: QR-Code vom PC scannen -> Prüfnummer vergleichen -> am PC bestätigen.
import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../api.dart';
import '../credentials.dart';
import '../theme.dart';

class PairingScreen extends StatefulWidget {
  const PairingScreen({super.key, required this.creds, required this.onPaired, this.message});
  final Credentials creds;
  final void Function(Map<String, dynamic> result) onPaired;
  final String? message;

  @override
  State<PairingScreen> createState() => _PairingScreenState();
}

class _PairingScreenState extends State<PairingScreen> {
  String? _verify;
  String? _error;
  bool _scanning = false;
  bool _busy = false;
  final _manual = TextEditingController();

  Future<void> _start(String raw) async {
    final p = PairingPayload.parse(raw);
    if (p == null) {
      setState(() => _error = 'Kein gültiger Jarvis-QR-Code.');
      return;
    }
    setState(() {
      _scanning = false;
      _busy = true;
      _error = null;
    });
    try {
      final name = Platform.isIOS ? 'iPhone (App)' : '${Platform.operatingSystem} (App)';
      final claim = await JarvisApi.claim(p.url, p.pairingId, p.code, name);
      setState(() => _verify = claim['verify_code'] as String);
      for (var i = 0; i < 150; i++) {
        await Future.delayed(const Duration(seconds: 2));
        Map<String, dynamic> r;
        try {
          r = await JarvisApi.poll(p.url, p.pairingId, claim['claim_secret'] as String);
        } catch (_) {
          continue;
        }
        if (r['status'] == 'completed') {
          await widget.creds.savePairing(baseUrl: p.url, deviceId: r['device_id'] as String, refresh: r['refresh_token'] as String, host: p.host);
          widget.onPaired(r);
          return;
        }
        if (const {'rejected', 'expired', 'cancelled', 'locked'}.contains(r['status'])) {
          setState(() {
            _verify = null;
            _error = r['status'] == 'rejected' ? 'Kopplung am PC abgelehnt.' : 'Kopplung abgelaufen. Bitte neuen QR-Code erzeugen.';
          });
          return;
        }
      }
      setState(() => _error = 'Zeitüberschreitung.');
    } on ApiException catch (e) {
      setState(() => _error = e.code == 'tailscale_required'
          ? 'Bitte Tailscale auf dem iPhone aktivieren und erneut versuchen.'
          : e.message);
    } catch (_) {
      setState(() => _error = 'PC nicht erreichbar. Sind iPhone und PC im selben Tailscale-Netzwerk und läuft Jarvis?');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 440),
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                const Text('J.A.R.V.I.S.', style: TextStyle(fontSize: 30, letterSpacing: 9, color: JColors.cyan)),
                const SizedBox(height: 6),
                const Text('Just A Rather Very Intelligent System', style: TextStyle(color: JColors.muted)),
                const SizedBox(height: 24),
                if (widget.message != null) Text(widget.message!, style: const TextStyle(color: JColors.warn)),
                if (_verify != null) ...[
                  const Text('Bitte am PC bestätigen. Prüfnummer:'),
                  const SizedBox(height: 12),
                  Text(_verify!, style: const TextStyle(fontSize: 42, letterSpacing: 10, color: JColors.cyan)),
                  const SizedBox(height: 8),
                  const Text('Die Nummer muss mit der Anzeige am PC übereinstimmen.', style: TextStyle(color: JColors.muted)),
                ] else if (_scanning) ...[
                  ClipRRect(
                    borderRadius: BorderRadius.circular(16),
                    child: SizedBox(
                      height: 300,
                      child: MobileScanner(onDetect: (capture) {
                        final raw = capture.barcodes.firstOrNull?.rawValue;
                        if (raw != null && !_busy) _start(raw);
                      }),
                    ),
                  ),
                  TextButton(onPressed: () => setState(() => _scanning = false), child: const Text('Abbrechen')),
                ] else ...[
                  const Text(
                    '1. Tailscale auf PC und iPhone aktivieren\n2. Am PC in Jarvis „PC → iPhone verbinden“ öffnen\n3. QR-Code scannen',
                    style: TextStyle(color: JColors.muted, height: 1.6),
                  ),
                  const SizedBox(height: 20),
                  FilledButton.icon(
                    onPressed: _busy ? null : () => setState(() => _scanning = true),
                    icon: const Icon(Icons.qr_code_scanner),
                    label: const Text('QR-Code scannen'),
                  ),
                  const SizedBox(height: 16),
                  TextField(controller: _manual, decoration: const InputDecoration(hintText: 'oder Kopplungslink einfügen')),
                  TextButton(onPressed: _busy ? null : () => _start(_manual.text), child: const Text('Mit Link koppeln')),
                ],
                if (_busy && _verify == null) const Padding(padding: EdgeInsets.all(12), child: CircularProgressIndicator()),
                if (_error != null) Padding(padding: const EdgeInsets.only(top: 16), child: Text(_error!, style: const TextStyle(color: JColors.err))),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}
