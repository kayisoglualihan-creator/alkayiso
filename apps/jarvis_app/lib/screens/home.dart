// Hauptansicht: Jarvis-Core, Mikrofon (Push-to-Talk), Chat bzw. Fernaufträge mit Live-Status.
import 'package:flutter/material.dart';

import '../api.dart';
import '../app_state.dart';
import '../theme.dart';
import '../voice.dart';
import '../widgets/jarvis_core.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key, required this.state, required this.voice});
  final AppState state;
  final Voice voice;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final _input = TextEditingController();
  final _scroll = ScrollController();
  double _level = 0;

  AppState get s => widget.state;

  @override
  void initState() {
    super.initState();
    s.addListener(_autoscroll);
  }

  @override
  void dispose() {
    s.removeListener(_autoscroll);
    super.dispose();
  }

  void _autoscroll() => WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_scroll.hasClients) _scroll.animateTo(_scroll.position.maxScrollExtent, duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
      });

  void _send() {
    final t = _input.text;
    _input.clear();
    s.send(t);
  }

  Future<void> _mic() async {
    if (widget.voice.listening) {
      await widget.voice.stop();
      return;
    }
    s.setCore(CoreState.listening);
    final ok = await widget.voice.listen(
      onLevel: (l) => setState(() => _level = ((l + 2) / 12).clamp(0, 1)),
      onResult: (text, isFinal) {
        _input.text = text;
        if (isFinal) {
          s.setCore(CoreState.idle);
          _send();
        }
      },
    );
    if (!ok) {
      s.setCore(CoreState.idle);
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Spracherkennung nicht verfügbar oder nicht erlaubt')));
    }
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: s,
      builder: (context, _) => Column(children: [
        const SizedBox(height: 8),
        JarvisCore(state: s.online ? s.core : CoreState.offline, level: _level, size: 170, onTap: widget.voice.stopSpeaking),
        Text(_label(s.online ? s.core : CoreState.offline), style: const TextStyle(letterSpacing: 3, color: JColors.cyan, fontSize: 12)),
        Expanded(
          child: ListView.builder(
            controller: _scroll,
            padding: const EdgeInsets.all(12),
            itemCount: s.chat.length,
            itemBuilder: (_, i) => _Bubble(s.chat[i]),
          ),
        ),
        SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(10, 4, 10, 8),
            child: Row(children: [
              GestureDetector(
                onTap: _mic,
                child: CircleAvatar(
                  radius: 26,
                  backgroundColor: widget.voice.listening ? JColors.ok.withValues(alpha: 0.3) : const Color(0x2200E5FF),
                  child: const Icon(Icons.mic, color: JColors.cyan),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: TextField(
                  controller: _input,
                  textInputAction: TextInputAction.send,
                  onSubmitted: (_) => _send(),
                  decoration: const InputDecoration(hintText: 'Nachricht an Jarvis …', isDense: true),
                ),
              ),
              IconButton(onPressed: _send, icon: const Icon(Icons.send, color: JColors.cyan)),
            ]),
          ),
        ),
      ]),
    );
  }

  String _label(CoreState c) => const {
        CoreState.idle: 'BEREIT',
        CoreState.listening: 'ICH HÖRE ZU',
        CoreState.thinking: 'DENKE NACH',
        CoreState.acting: 'FÜHRE AUS',
        CoreState.speaking: 'SPRECHE',
        CoreState.error: 'FEHLER',
        CoreState.offline: 'PC OFFLINE',
      }[c]!;
}

class _Bubble extends StatelessWidget {
  const _Bubble(this.m);
  final ChatMessage m;

  @override
  Widget build(BuildContext context) {
    final user = m.role == 'user';
    return Align(
      alignment: user ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.82),
        decoration: BoxDecoration(
          color: user ? const Color(0x381E7BFF) : const Color(0x1000E5FF),
          border: Border.all(color: user ? const Color(0x661E7BFF) : JColors.line),
          borderRadius: BorderRadius.circular(14),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SelectableText(m.text),
          if (m.status != null)
            Container(
              margin: const EdgeInsets.only(top: 6),
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              decoration: BoxDecoration(color: statusColor(m.status).withValues(alpha: 0.18), borderRadius: BorderRadius.circular(8)),
              child: Text(jobStatusLabel[m.status] ?? m.status!, style: TextStyle(fontSize: 11, color: statusColor(m.status))),
            ),
        ]),
      ),
    );
  }
}
