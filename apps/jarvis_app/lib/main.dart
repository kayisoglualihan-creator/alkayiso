// J.A.R.V.I.S. – native App für iPhone (iOS) und Windows-Desktop.
import 'package:flutter/material.dart';

import 'app_state.dart';
import 'credentials.dart';
import 'screens/home.dart';
import 'screens/other_screens.dart';
import 'screens/pairing.dart';
import 'theme.dart';
import 'voice.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final creds = await Credentials.load();
  runApp(JarvisApp(creds: creds));
}

class JarvisApp extends StatefulWidget {
  const JarvisApp({super.key, required this.creds});
  final Credentials creds;

  @override
  State<JarvisApp> createState() => _JarvisAppState();
}

class _JarvisAppState extends State<JarvisApp> {
  AppState? _state;
  String? _message;

  @override
  void initState() {
    super.initState();
    if (widget.creds.isPaired) _startSession();
  }

  void _startSession([Map<String, dynamic>? pairResult]) {
    final s = AppState(widget.creds);
    if (pairResult != null) {
      s.api.setInitialAccess(pairResult['access_token'] as String, (pairResult['expires_at'] as num).toDouble());
    }
    s.addListener(() {
      if (s.revokedMessage != null && _state == s) {
        setState(() {
          _message = s.revokedMessage;
          _state = null;
        });
        s.dispose();
      }
    });
    s.start();
    setState(() => _state = s);
  }

  Future<void> _unpair() async {
    await widget.creds.clear();
    _state?.dispose();
    setState(() {
      _state = null;
      _message = 'Kopplung entfernt.';
    });
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'J.A.R.V.I.S.',
      debugShowCheckedModeBanner: false,
      theme: jarvisTheme(),
      home: _state == null
          ? PairingScreen(creds: widget.creds, message: _message, onPaired: _startSession)
          : Shell(state: _state!, onUnpair: _unpair),
    );
  }
}

class Shell extends StatefulWidget {
  const Shell({super.key, required this.state, required this.onUnpair});
  final AppState state;
  final VoidCallback onUnpair;

  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  int _tab = 0;
  final Voice _voice = Voice();

  @override
  void initState() {
    super.initState();
    _voice.init();
    widget.state.onAssistantReply = (text) => _voice.speak(text,
        onStart: () => widget.state.setCore(CoreState.speaking), onDone: () => widget.state.setCore(CoreState.idle));
    widget.state.onNotification = (title, body) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(body.isEmpty ? title : '$title: $body')));
    };
  }

  void _command(String text) {
    setState(() => _tab = 0);
    widget.state.send(text);
  }

  @override
  Widget build(BuildContext context) {
    final s = widget.state;
    final pages = [
      HomeScreen(state: s, voice: _voice),
      TasksScreen(state: s),
      MemoryScreen(state: s),
      RemoteScreen(state: s, onCommand: _command),
      HistoryScreen(state: s, onUnpair: widget.onUnpair),
    ];
    return Scaffold(
      appBar: AppBar(
        title: ListenableBuilder(
          listenable: s,
          builder: (_, _) => Row(children: [
            Icon(Icons.circle, size: 10, color: s.online ? JColors.ok : JColors.err),
            const SizedBox(width: 10),
            const Text('J.A.R.V.I.S.', style: TextStyle(letterSpacing: 5, color: JColors.cyan, fontSize: 18)),
          ]),
        ),
        actions: [
          IconButton(
            tooltip: 'Sprachausgabe',
            icon: Icon(_voice.enabled ? Icons.volume_up : Icons.volume_off),
            onPressed: () => setState(() {
              _voice.enabled = !_voice.enabled;
              if (!_voice.enabled) _voice.stopSpeaking();
            }),
          ),
          IconButton(tooltip: 'Neue Unterhaltung', icon: const Icon(Icons.add_comment_outlined), onPressed: s.newConversation),
        ],
      ),
      body: Column(children: [
        ApprovalBar(state: s),
        Expanded(child: IndexedStack(index: _tab, children: pages)),
      ]),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.blur_circular), label: 'Core'),
          NavigationDestination(icon: Icon(Icons.check_circle_outline), label: 'Aufgaben'),
          NavigationDestination(icon: Icon(Icons.lightbulb_outline), label: 'Gedächtnis'),
          NavigationDestination(icon: Icon(Icons.computer), label: 'PC'),
          NavigationDestination(icon: Icon(Icons.history), label: 'Verlauf'),
        ],
      ),
    );
  }
}
