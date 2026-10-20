// Animierter Jarvis-Core (CustomPainter, reagiert auf Zustand und Sprachpegel).
import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../app_state.dart';
import '../theme.dart';

class JarvisCore extends StatefulWidget {
  const JarvisCore({super.key, required this.state, this.level = 0, this.size = 220, this.onTap});
  final CoreState state;
  final double level;
  final double size;
  final VoidCallback? onTap;

  @override
  State<JarvisCore> createState() => _JarvisCoreState();
}

class _JarvisCoreState extends State<JarvisCore> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(seconds: 60))..repeat();
  double _energy = 0;

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  static const _colors = {
    CoreState.idle: JColors.cyan,
    CoreState.listening: JColors.ok,
    CoreState.thinking: JColors.blue,
    CoreState.acting: JColors.warn,
    CoreState.speaking: JColors.cyan,
    CoreState.error: JColors.err,
    CoreState.offline: Color(0xFF78828C),
  };

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: widget.onTap,
      child: RepaintBoundary(
        child: AnimatedBuilder(
          animation: _c,
          builder: (context, _) {
            final t = _c.value * 60;
            final target = switch (widget.state) {
              CoreState.listening => 0.35 + widget.level * 0.9,
              CoreState.thinking => 0.4,
              CoreState.acting => 0.5,
              CoreState.speaking => 0.3 + (math.sin(t * 9)).abs() * 0.4,
              CoreState.offline => 0.0,
              _ => 0.08,
            };
            _energy += (target - _energy) * 0.12;
            return CustomPaint(
              size: Size.square(widget.size),
              painter: _CorePainter(t, _energy, _colors[widget.state]!, widget.state),
            );
          },
        ),
      ),
    );
  }
}

class _CorePainter extends CustomPainter {
  _CorePainter(this.t, this.e, this.color, this.state);
  final double t;
  final double e;
  final Color color;
  final CoreState state;

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width;
    final c = Offset(w / 2, w / 2);
    final glow = Paint()
      ..shader = RadialGradient(colors: [color.withValues(alpha: 0.35 + e * 0.3), color.withValues(alpha: 0.06), Colors.transparent], stops: const [0, 0.4, 1])
          .createShader(Rect.fromCircle(center: c, radius: w / 2));
    canvas.drawCircle(c, w / 2, glow);
    final speed = state == CoreState.thinking ? 2.2 : state == CoreState.acting ? 1.6 : 0.6;
    const rings = [(0.44, 0.012, 0.8, 1.0), (0.38, 0.006, -1.3, 0.7), (0.32, 0.018, 0.5, 0.9), (0.25, 0.008, -2.0, 0.6)];
    for (var i = 0; i < rings.length; i++) {
      final (rad, sw, dir, alpha) = rings[i];
      final r = w * rad * (1 + e * 0.04 * math.sin(t * 3 + i));
      final segs = 3 + i;
      final rot = t * dir * speed;
      final p = Paint()
        ..style = PaintingStyle.stroke
        ..strokeCap = StrokeCap.round
        ..strokeWidth = w * sw
        ..color = color.withValues(alpha: alpha * (0.5 + e * 0.5));
      for (var s = 0; s < segs; s++) {
        final a0 = rot + s * 2 * math.pi / segs;
        final len = 2 * math.pi / segs * (0.55 + 0.25 * math.sin(t + s));
        canvas.drawArc(Rect.fromCircle(center: c, radius: r), a0, len, false, p);
      }
    }
    final wave = Path();
    final r0 = w * 0.16;
    for (var i = 0; i <= 120; i++) {
      final a = i / 120 * 2 * math.pi;
      final amp = e * w * 0.035 * (math.sin(a * 6 + t * 5) + math.sin(a * 11 - t * 7) * 0.5);
      final pt = c + Offset(math.cos(a), math.sin(a)) * (r0 + amp);
      i == 0 ? wave.moveTo(pt.dx, pt.dy) : wave.lineTo(pt.dx, pt.dy);
    }
    canvas.drawPath(wave..close(), Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = w * 0.006
      ..color = color.withValues(alpha: 0.9));
    final core = Paint()
      ..shader = RadialGradient(colors: [Colors.white, color.withValues(alpha: 0.9), color.withValues(alpha: 0.05)], stops: const [0, 0.3, 1])
          .createShader(Rect.fromCircle(center: c, radius: r0 * 0.8));
    canvas.drawCircle(c, r0 * (0.75 + e * 0.15), core);
  }

  @override
  bool shouldRepaint(covariant _CorePainter old) => true;
}
