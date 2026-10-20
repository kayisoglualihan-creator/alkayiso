// Sprachein- und -ausgabe (iOS: Apple Spracherkennung + AVSpeechSynthesizer, Windows: SAPI).
import 'package:flutter_tts/flutter_tts.dart';
import 'package:speech_to_text/speech_to_text.dart';

class Voice {
  final SpeechToText _stt = SpeechToText();
  final FlutterTts _tts = FlutterTts();
  bool _sttReady = false;
  bool enabled = true;
  bool get listening => _stt.isListening;

  Future<void> init() async {
    await _tts.setLanguage('de-DE');
    await _tts.setSpeechRate(0.5);
    await _tts.awaitSpeakCompletion(false);
  }

  /// Push-to-Talk: hört zu, bis der Nutzer aufhört zu sprechen oder [stop] aufgerufen wird.
  Future<bool> listen({required void Function(String text, bool isFinal) onResult, void Function(double level)? onLevel}) async {
    if (!_sttReady) {
      _sttReady = await _stt.initialize(onError: (_) {});
      if (!_sttReady) return false;
    }
    await stopSpeaking();
    await _stt.listen(
      onResult: (r) => onResult(r.recognizedWords, r.finalResult),
      onSoundLevelChange: onLevel,
      listenOptions: SpeechListenOptions(
        localeId: 'de_DE',
        partialResults: true,
        cancelOnError: true,
        listenMode: ListenMode.dictation,
        pauseFor: const Duration(seconds: 2),
        listenFor: const Duration(seconds: 30),
      ),
    );
    return true;
  }

  Future<void> stop() => _stt.stop();

  Future<void> speak(String text, {void Function()? onStart, void Function()? onDone}) async {
    if (!enabled || text.trim().isEmpty) return;
    _tts.setStartHandler(() => onStart?.call());
    _tts.setCompletionHandler(() => onDone?.call());
    _tts.setCancelHandler(() => onDone?.call());
    final clean = text.replaceAll(RegExp(r'[#*_`>|]'), '').replaceAll(RegExp(r'https?://\S+'), 'Link');
    await _tts.speak(clean.length > 1200 ? clean.substring(0, 1200) : clean);
  }

  Future<void> stopSpeaking() => _tts.stop();
}
