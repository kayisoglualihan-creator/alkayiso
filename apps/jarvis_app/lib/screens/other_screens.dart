// Aufgaben, Gedächtnis, PC-Status/Fernsteuerung, Verlauf/Benachrichtigungen und Genehmigungsleiste.
import 'package:flutter/material.dart';

import '../api.dart';
import '../app_state.dart';
import '../theme.dart';

String fmtTs(dynamic ts) {
  if (ts == null) return '–';
  final d = DateTime.fromMillisecondsSinceEpoch(((ts as num) * 1000).round());
  String two(int n) => n.toString().padLeft(2, '0');
  return '${two(d.day)}.${two(d.month)}. ${two(d.hour)}:${two(d.minute)}';
}

// ------------------------------------------------------------------ Genehmigungen
class ApprovalBar extends StatelessWidget {
  const ApprovalBar({super.key, required this.state});
  final AppState state;

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: state,
      builder: (context, _) => Column(children: [
        if (!state.online)
          Container(
            width: double.infinity,
            color: JColors.err.withValues(alpha: 0.15),
            padding: const EdgeInsets.all(8),
            child: const Text('PC offline – zeige zwischengespeicherte Daten. Fernbefehle sind nicht möglich.',
                style: TextStyle(color: Color(0xFFFFC7D1), fontSize: 13)),
          ),
        for (final a in state.approvals) _ApprovalCard(state: state, a: a),
      ]),
    );
  }
}

class _ApprovalCard extends StatefulWidget {
  const _ApprovalCard({required this.state, required this.a});
  final AppState state;
  final Map<String, dynamic> a;

  @override
  State<_ApprovalCard> createState() => _ApprovalCardState();
}

class _ApprovalCardState extends State<_ApprovalCard> {
  final _confirm = TextEditingController();

  Future<void> _decide(bool ok) async {
    final err = await widget.state.decide(widget.a['id'] as String, ok, confirm: _confirm.text);
    if (err != null && mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(err)));
  }

  @override
  Widget build(BuildContext context) {
    final crit = widget.a['requires_confirm_text'] == true;
    final color = crit ? JColors.err : JColors.warn;
    return Container(
      margin: const EdgeInsets.fromLTRB(10, 8, 10, 0),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: color.withValues(alpha: 0.1), border: Border.all(color: color.withValues(alpha: 0.6)), borderRadius: BorderRadius.circular(12)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${crit ? 'Kritische Aktion' : 'Genehmigung erforderlich'}: ${widget.a['summary']}', style: const TextStyle(fontWeight: FontWeight.w600)),
        Text('läuft ab ${fmtTs(widget.a['expires_at'])}', style: const TextStyle(color: JColors.muted, fontSize: 12)),
        if (crit) Padding(padding: const EdgeInsets.only(top: 8), child: TextField(controller: _confirm, decoration: const InputDecoration(hintText: 'BESTÄTIGEN eingeben', isDense: true))),
        const SizedBox(height: 8),
        Row(children: [
          FilledButton(onPressed: () => _decide(true), child: const Text('Ausführen')),
          const SizedBox(width: 8),
          OutlinedButton(onPressed: () => _decide(false), child: const Text('Ablehnen', style: TextStyle(color: JColors.err))),
        ]),
      ]),
    );
  }
}

// ------------------------------------------------------------------ Aufgaben
class TasksScreen extends StatefulWidget {
  const TasksScreen({super.key, required this.state});
  final AppState state;

  @override
  State<TasksScreen> createState() => _TasksScreenState();
}

class _TasksScreenState extends State<TasksScreen> {
  final _title = TextEditingController();
  final _due = TextEditingController();

  Future<void> _add() async {
    if (_title.text.trim().isEmpty) return;
    final err = await widget.state.addTask(_title.text.trim(), due: _due.text.trim().isEmpty ? null : _due.text.trim());
    if (err != null && mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(err)));
    _title.clear();
    _due.clear();
  }

  @override
  Widget build(BuildContext context) {
    final s = widget.state;
    return ListenableBuilder(
      listenable: s,
      builder: (context, _) => RefreshIndicator(
        onRefresh: s.loadTasks,
        child: ListView(padding: const EdgeInsets.all(12), children: [
          TextField(controller: _title, decoration: const InputDecoration(hintText: 'Neue Aufgabe')),
          const SizedBox(height: 8),
          Row(children: [
            Expanded(child: TextField(controller: _due, decoration: const InputDecoration(hintText: 'Fällig (z. B. morgen 9 Uhr)'))),
            const SizedBox(width: 8),
            FilledButton(onPressed: s.online ? _add : null, child: const Text('+')),
          ]),
          const SizedBox(height: 12),
          if (s.tasks.isEmpty) const Text('Keine Aufgaben', style: TextStyle(color: JColors.muted)),
          for (final t in s.tasks)
            Card(
              child: CheckboxListTile(
                value: t['status'] == 'done',
                onChanged: s.online ? (_) => s.toggleTask(t) : null,
                title: Text('${t['title']}', style: TextStyle(decoration: t['status'] == 'done' ? TextDecoration.lineThrough : null)),
                subtitle: t['due_at'] != null ? Text('fällig ${fmtTs(t['due_at'])}') : null,
                secondary: t['priority'] == 3 ? const Icon(Icons.priority_high, color: JColors.warn) : null,
              ),
            ),
        ]),
      ),
    );
  }
}

// ------------------------------------------------------------------ Gedächtnis (gemeinsam mit dem PC)
class MemoryScreen extends StatefulWidget {
  const MemoryScreen({super.key, required this.state});
  final AppState state;

  @override
  State<MemoryScreen> createState() => _MemoryScreenState();
}

class _MemoryScreenState extends State<MemoryScreen> {
  List<Map<String, dynamic>> _items = [];
  final _q = TextEditingController();
  final _new = TextEditingController();
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await widget.state.api.get('/api/memory', _q.text.isEmpty ? null : {'q': _q.text});
      setState(() {
        _items = List<Map<String, dynamic>>.from((r['data'] ?? r) as List);
        _error = null;
      });
    } on PcOfflineException {
      setState(() => _error = 'PC offline – Gedächtnis nicht erreichbar.');
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    }
  }

  Future<void> _add() async {
    if (_new.text.trim().isEmpty) return;
    await widget.state.api.post('/api/memory', {'content': _new.text.trim(), 'category': 'allgemein'});
    _new.clear();
    _load();
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(padding: const EdgeInsets.all(12), children: [
        const Text('Jarvis merkt sich nur, was du ihm mitteilst.', style: TextStyle(color: JColors.muted)),
        const SizedBox(height: 8),
        Row(children: [
          Expanded(child: TextField(controller: _new, decoration: const InputDecoration(hintText: 'Neue Erinnerung'))),
          IconButton(onPressed: _add, icon: const Icon(Icons.add, color: JColors.cyan)),
        ]),
        const SizedBox(height: 8),
        TextField(controller: _q, onSubmitted: (_) => _load(), decoration: const InputDecoration(hintText: 'Suchen …', prefixIcon: Icon(Icons.search))),
        if (_error != null) Padding(padding: const EdgeInsets.all(8), child: Text(_error!, style: const TextStyle(color: JColors.err))),
        for (final m in _items)
          Card(
            child: ListTile(
              title: Text('${m['content']}'),
              subtitle: Text('${m['category']} · ${fmtTs(m['updated_at'])}'),
              trailing: IconButton(
                icon: const Icon(Icons.delete_outline),
                onPressed: () async {
                  await widget.state.api.delete('/api/memory/${m['id']}');
                  _load();
                },
              ),
            ),
          ),
      ]),
    );
  }
}

// ------------------------------------------------------------------ PC-Status & Schnellbefehle
class RemoteScreen extends StatelessWidget {
  const RemoteScreen({super.key, required this.state, required this.onCommand});
  final AppState state;
  final void Function(String) onCommand;

  static const quick = {
    'CPU/RAM': 'Wie hoch ist die CPU-Auslastung meines Computers?',
    'VS Code öffnen': 'Öffne Visual Studio Code',
    'Neueste PDF zusammenfassen': 'Fasse die neueste PDF-Datei zusammen',
    'Arbeitsbeginn': 'Starte den Workflow Arbeitsbeginn',
    'Excel-Tabelle': 'Erstelle eine Excel-Tabelle mit Spalten Datum, Aufgabe, Status',
    'Projektübersicht': 'Erstelle eine Übersicht meiner aktuellen Projekte',
    'Tagesübersicht': 'Guten Morgen',
    'PC sperren': 'Sperre den PC',
  };

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: state,
      builder: (context, _) {
        final st = state.status;
        final sys = st?['system'] as Map?;
        return RefreshIndicator(
          onRefresh: state.refreshAll,
          child: ListView(padding: const EdgeInsets.all(12), children: [
            Card(
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    Icon(Icons.circle, size: 12, color: state.online ? JColors.ok : JColors.err),
                    const SizedBox(width: 8),
                    Text(state.online ? 'Verbunden mit ${st?['hostname'] ?? state.creds.host ?? 'PC'}' : 'PC offline',
                        style: const TextStyle(fontWeight: FontWeight.w600)),
                  ]),
                  if (sys != null) ...[
                    const SizedBox(height: 12),
                    _meter('CPU', (sys['cpu_percent'] as num).toDouble()),
                    _meter('RAM', (sys['ram_percent'] as num).toDouble()),
                    for (final d in (sys['disks'] as List).take(3)) _meter('Laufwerk ${d['mount']} (${d['free_gb']} GB frei)', (d['percent'] as num).toDouble()),
                    Text('KI: ${st!['ai']['provider'] == 'offline' ? 'Lokaler Basismodus' : st['ai']['model']}${state.online ? '' : ' · Stand zwischengespeichert'}',
                        style: const TextStyle(color: JColors.muted, fontSize: 12)),
                  ],
                ]),
              ),
            ),
            const SizedBox(height: 8),
            const Text('SCHNELLBEFEHLE', style: TextStyle(color: JColors.cyan, letterSpacing: 2, fontSize: 12)),
            const SizedBox(height: 8),
            Wrap(spacing: 8, runSpacing: 8, children: [
              for (final e in quick.entries) ActionChip(label: Text(e.key), onPressed: state.online ? () => onCommand(e.value) : null),
            ]),
            const SizedBox(height: 16),
            const Text('AUFTRÄGE', style: TextStyle(color: JColors.cyan, letterSpacing: 2, fontSize: 12)),
            for (final j in state.jobs.take(20))
              ListTile(
                dense: true,
                title: Text('${j['text']}', maxLines: 2, overflow: TextOverflow.ellipsis),
                subtitle: Text(fmtTs(j['created_at'])),
                trailing: Text(jobStatusLabel[j['status']] ?? '${j['status']}', style: TextStyle(color: statusColor(j['status'] as String?))),
              ),
          ]),
        );
      },
    );
  }

  Widget _meter(String label, double pct) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('$label  ${pct.toStringAsFixed(0)}%', style: const TextStyle(fontSize: 13)),
          const SizedBox(height: 3),
          LinearProgressIndicator(value: pct / 100, minHeight: 5, color: JColors.cyan, backgroundColor: const Color(0x14FFFFFF), borderRadius: BorderRadius.circular(3)),
        ]),
      );
}

// ------------------------------------------------------------------ Verlauf / Benachrichtigungen / Gerät
class HistoryScreen extends StatelessWidget {
  const HistoryScreen({super.key, required this.state, required this.onUnpair});
  final AppState state;
  final VoidCallback onUnpair;

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: state,
      builder: (context, _) => ListView(padding: const EdgeInsets.all(12), children: [
        const Text('BENACHRICHTIGUNGEN', style: TextStyle(color: JColors.cyan, letterSpacing: 2, fontSize: 12)),
        if (state.notifications.isEmpty) const Text('Keine', style: TextStyle(color: JColors.muted)),
        for (final n in state.notifications.take(50))
          ListTile(dense: true, title: Text('${n['title']}'), subtitle: Text('${n['body']}\n${fmtTs(n['ts'])}'), isThreeLine: true),
        const Divider(),
        if (!state.isAdmin) ...[
          Text('Gerät: ${state.creds.deviceId}', style: const TextStyle(color: JColors.muted, fontSize: 12)),
          Text('Verbunden mit: ${state.creds.baseUrl}', style: const TextStyle(color: JColors.muted, fontSize: 12)),
          const SizedBox(height: 8),
          OutlinedButton(onPressed: onUnpair, child: const Text('Kopplung auf diesem Gerät entfernen')),
        ] else
          const Text('Einstellungen, Berechtigungen und Geräte verwaltest du in der Desktop-Oberfläche (Setup).',
              style: TextStyle(color: JColors.muted)),
      ]),
    );
  }
}
