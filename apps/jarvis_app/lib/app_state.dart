// Zentraler App-Zustand: Verbindung, Chat/Fernaufträge, Genehmigungen, Aufgaben, Offline-Cache.
import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'api.dart';
import 'credentials.dart';

enum CoreState { idle, listening, thinking, acting, speaking, error, offline }

class ChatMessage {
  ChatMessage(this.role, this.text, {this.status, this.jobId});
  final String role; // user | assistant | event
  String text;
  String? status;
  String? jobId;
}

class AppState extends ChangeNotifier {
  AppState(this.creds) {
    api = JarvisApi(creds)..onRevoked = _onRevoked;
  }

  final Credentials creds;
  late final JarvisApi api;
  SharedPreferences? _prefs;

  bool online = true;
  CoreState core = CoreState.idle;
  Map<String, dynamic>? status;
  List<Map<String, dynamic>> approvals = [];
  List<Map<String, dynamic>> tasks = [];
  List<Map<String, dynamic>> notifications = [];
  List<Map<String, dynamic>> jobs = [];
  final List<ChatMessage> chat = [];
  String? conversationId;
  String? revokedMessage;
  void Function(String title, String body)? onNotification;
  void Function(String text)? onAssistantReply;

  WebSocketChannel? _ws;
  Timer? _pingTimer;
  int _wsRetry = 0;
  bool _disposed = false;

  bool get isAdmin => creds.isAdmin;

  Future<void> start() async {
    _prefs = await SharedPreferences.getInstance();
    _loadCache();
    chat.add(ChatMessage('assistant', isAdmin ? 'Guten Tag. Wie kann ich helfen?' : 'Hallo. Was soll ich auf deinem PC erledigen?'));
    await checkOnline();
    _pingTimer = Timer.periodic(const Duration(seconds: 10), (_) => checkOnline());
    if (online) {
      await refreshAll();
      _connectWs();
    }
  }

  @override
  void dispose() {
    _disposed = true;
    _pingTimer?.cancel();
    _ws?.sink.close();
    super.dispose();
  }

  void _set(VoidCallback fn) {
    fn();
    if (!_disposed) notifyListeners();
  }

  // ---------------------------------------------------------------- Verbindung
  Future<void> checkOnline() async {
    final now = await api.isOnline();
    if (now == online) return;
    _set(() {
      online = now;
      core = now ? CoreState.idle : CoreState.offline;
    });
    if (now) {
      await refreshAll();
      _connectWs();
    }
  }

  void _offline() => _set(() {
        online = false;
        core = CoreState.offline;
      });

  Future<void> _connectWs() async {
    if (_ws != null) return;
    try {
      final ch = WebSocketChannel.connect(await api.wsUri());
      _ws = ch;
      await ch.ready;
      _wsRetry = 0;
      ch.stream.listen((raw) {
        try {
          _onEvent(jsonDecode(raw as String) as Map<String, dynamic>);
        } catch (_) {}
      }, onDone: _wsClosed, onError: (_) => _wsClosed());
    } catch (_) {
      _wsClosed();
    }
  }

  void _wsClosed() {
    _ws = null;
    if (_disposed || revokedMessage != null) return;
    final delay = Duration(seconds: [1 << _wsRetry, 30].reduce((a, b) => a < b ? a : b));
    _wsRetry = (_wsRetry + 1).clamp(0, 5);
    Future.delayed(delay, () {
      if (online && !_disposed) _connectWs();
    });
  }

  void _onEvent(Map<String, dynamic> ev) {
    final data = ev['data'];
    switch (ev['type']) {
      case 'approval.created':
      case 'approval.updated':
        loadApprovals();
      case 'job.updated':
        if (data is Map<String, dynamic>) _applyJob(data);
      case 'task.changed':
      case 'task.deleted':
        loadTasks();
      case 'notification':
        loadNotifications();
        if (data is Map && data['kind'] != 'job') onNotification?.call('${data['title']}', '${data['body'] ?? ''}');
    }
  }

  void _onRevoked(String message) {
    _set(() => revokedMessage = message);
    creds.clear();
  }

  // ---------------------------------------------------------------- Laden
  Future<T?> _guard<T>(Future<T> Function() fn) async {
    try {
      return await fn();
    } on PcOfflineException {
      _offline();
    } on ApiException catch (_) {}
    return null;
  }

  Future<void> refreshAll() async {
    await Future.wait([loadStatus(), loadApprovals(), loadTasks(), loadNotifications(), loadJobs()]);
  }

  Future<void> loadStatus() async {
    final s = await _guard(() => api.get('/api/status'));
    if (s != null) {
      _set(() => status = Map<String, dynamic>.from(s));
      _cache('status', s);
    }
  }

  Future<void> loadApprovals() async {
    final a = await _guard(() => api.get('/api/approvals'));
    if (a != null) _set(() => approvals = List<Map<String, dynamic>>.from((a['data'] ?? a) as List));
  }

  Future<void> loadTasks() async {
    final t = await _guard(() => api.get('/api/tasks', {'status': 'all'}));
    if (t != null) {
      final list = List<Map<String, dynamic>>.from((t['data'] ?? t) as List);
      _set(() => tasks = list);
      _cache('tasks', list);
    }
  }

  Future<void> loadNotifications() async {
    final n = await _guard(() => api.get('/api/notifications'));
    if (n != null) {
      final list = List<Map<String, dynamic>>.from((n['data'] ?? n) as List);
      _set(() => notifications = list);
      _cache('notifications', list);
    }
  }

  Future<void> loadJobs() async {
    final j = await _guard(() => api.get('/api/jobs'));
    if (j != null) _set(() => jobs = List<Map<String, dynamic>>.from((j['data'] ?? j) as List));
  }

  // ---------------------------------------------------------------- Chat / Fernaufträge
  Future<void> send(String text) async {
    text = text.trim();
    if (text.isEmpty) return;
    _set(() => chat.add(ChatMessage('user', text)));
    if (!online) {
      _set(() => chat.add(ChatMessage('assistant', 'Dein PC ist nicht erreichbar. Der Befehl wurde nicht gesendet.', status: 'offline')));
      return;
    }
    final msg = ChatMessage('assistant', 'Auftrag übermittelt …', status: 'pending');
    _set(() {
      chat.add(msg);
      core = CoreState.thinking;
    });
    try {
      final job = await api.submitJob(text, conversationId: conversationId);
      msg.jobId = job['id'] as String;
      _applyJob(job);
      await _pollJob(msg.jobId!);
    } on PcOfflineException {
      _set(() {
        msg.text = 'Verbindung zum PC verloren.';
        msg.status = 'offline';
      });
      _offline();
    } on ApiException catch (e) {
      _set(() {
        msg.text = e.message;
        msg.status = 'failed';
        core = CoreState.error;
      });
    }
  }

  Future<void> _pollJob(String id) async {
    for (var i = 0; i < 60; i++) {
      final job = await api.job(id, wait: 20);
      _applyJob(job);
      if (const {'succeeded', 'failed', 'cancelled'}.contains(job['status'])) return;
    }
  }

  void _applyJob(Map<String, dynamic> job) {
    final msg = chat.where((m) => m.jobId == job['id']).firstOrNull;
    if (msg == null) return;
    final st = job['status'] as String;
    if (msg.status == st && st != 'running') return;
    final done = st == 'succeeded' || st == 'failed';
    _set(() {
      msg.status = st;
      if (done) {
        final result = job['result'];
        msg.text = (result is Map ? result['text'] : null) as String? ?? (job['error'] as String? ?? '');
        conversationId = job['conversation_id'] as String? ?? conversationId;
        core = st == 'failed' ? CoreState.error : CoreState.idle;
      } else if (st == 'approval_required') {
        msg.text = 'Bitte genehmige die Aktion.';
        core = CoreState.acting;
      } else if (st == 'running') {
        msg.text = 'Jarvis arbeitet auf deinem PC …';
        core = CoreState.acting;
      }
    });
    if (st == 'approval_required') loadApprovals();
    if (done) {
      onAssistantReply?.call(msg.text);
      loadTasks();
    }
  }

  Future<String?> decide(String id, bool approve, {String? confirm}) async {
    try {
      await api.decide(id, approve, confirmText: confirm);
      await loadApprovals();
      return null;
    } on ApiException catch (e) {
      return e.message;
    } on PcOfflineException catch (e) {
      _offline();
      return e.message;
    }
  }

  void newConversation() => _set(() {
        conversationId = null;
        chat
          ..clear()
          ..add(ChatMessage('assistant', 'Neue Unterhaltung. Was kann ich für dich tun?'));
      });

  void setCore(CoreState s) => _set(() => core = s);

  // ---------------------------------------------------------------- Aufgaben
  Future<String?> addTask(String title, {String? due}) async {
    try {
      await api.post('/api/tasks', {'title': title, 'due': due});
      await loadTasks();
      return null;
    } on PcOfflineException {
      _offline();
      return 'PC offline – Aufgabe wird nicht gespeichert.';
    } on ApiException catch (e) {
      return e.message;
    }
  }

  Future<void> toggleTask(Map<String, dynamic> t) async {
    await _guard(() => api.patch('/api/tasks/${t['id']}', {'status': t['status'] == 'done' ? 'open' : 'done'}));
    await loadTasks();
  }

  // ---------------------------------------------------------------- Cache (für Offline-Anzeige)
  void _cache(String key, Object value) => _prefs?.setString('cache_$key', jsonEncode(value));

  void _loadCache() {
    T? read<T>(String k) {
      final s = _prefs?.getString('cache_$k');
      return s == null ? null : jsonDecode(s) as T;
    }

    status = read<Map<String, dynamic>>('status');
    tasks = List<Map<String, dynamic>>.from(read<List>('tasks') ?? []);
    notifications = List<Map<String, dynamic>>.from(read<List>('notifications') ?? []);
  }
}
