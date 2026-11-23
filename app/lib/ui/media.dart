// Photos and files: picking them, showing them, and looking at them full screen.
import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:share_plus/share_plus.dart';

import '../core/l10n.dart';
import '../core/native.dart';
import '../core/relay.dart';
import '../core/store.dart';
import 'kit.dart';
import 'look.dart';
import 'motion.dart';

/// What picking gives back, whatever the user picked.
Future<List<Att>> pickPhotos({bool camera = false}) async {
  final picker = ImagePicker();
  final got = camera
      ? [await picker.pickImage(source: ImageSource.camera, maxWidth: 2048, maxHeight: 2048, imageQuality: 88, requestFullMetadata: false)]
      : await picker.pickMultiImage(maxWidth: 2048, maxHeight: 2048, imageQuality: 88, limit: 10, requestFullMetadata: false);
  final out = <Att>[];
  for (final x in got.whereType<XFile>()) {
    final name = x.name.contains('.') ? x.name : '${x.name}.jpg';
    out.add(await Media.keep(x.path, label: name));
  }
  return out;
}

Future<List<Att>> pickFiles() async {
  final got = await FilePicker.pickFiles();
  final out = <Att>[];
  for (final f in got) {
    if (f.path != null) out.add(await Media.keep(f.path!, label: f.name));
  }
  return out;
}

/// Photos and files added to a message that hasn't been sent.
class AttStrip extends StatelessWidget {
  const AttStrip(this.files, {super.key, required this.onRemove});
  final List<Att> files;
  final void Function(Att) onRemove;

  @override
  Widget build(BuildContext context) {
    return AnimatedSize(
      duration: med,
      curve: Curves.easeOutQuint,
      alignment: Alignment.bottomCenter,
      child: files.isEmpty
          ? const SizedBox(width: double.infinity)
          : SizedBox(
              height: 84,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.fromLTRB(12, 12, 12, 4),
                itemCount: files.length,
                separatorBuilder: (_, _) => const SizedBox(width: 10),
                itemBuilder: (c, i) => _AttChip(files[i], onRemove: () => onRemove(files[i])),
              ),
            ),
    );
  }
}

class _AttChip extends StatelessWidget {
  const _AttChip(this.a, {required this.onRemove});
  final Att a;
  final VoidCallback onRemove;
  @override
  Widget build(BuildContext context) {
    final p = context.p;
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: const Duration(milliseconds: 420),
      curve: spring,
      builder: (_, v, child) => Transform.scale(scale: .6 + .4 * v, child: Opacity(opacity: v.clamp(0, 1), child: child)),
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          if (a.isImage)
            Press(
              onTap: () => viewImages(context, [FileImage(a.file)], 0),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(15),
                child: Image.file(a.file, width: 68, height: 68, fit: BoxFit.cover, cacheWidth: 240),
              ),
            )
          else
            Container(width: 190, height: 68, padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: p.fill2, borderRadius: BorderRadius.circular(15)), child: FileLine(a.label, a.size)),
          PositionedDirectional(
            top: -6,
            end: -6,
            child: Press(
              onTap: onRemove,
              label: t('Remove'),
              child: Container(
                width: 24,
                height: 24,
                decoration: BoxDecoration(color: p.inv, shape: BoxShape.circle, border: Border.all(color: p.raised, width: 2)),
                child: Icon(LucideIcons.x, size: 13, color: p.onInv),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class FileLine extends StatelessWidget {
  const FileLine(this.name, this.size, {super.key, this.sub});
  final String name;
  final int size;
  final String? sub;
  @override
  Widget build(BuildContext context) {
    final p = context.p;
    return Row(
      children: [
        Square(fileIcon(name), color: fileColor(name, p), size: 36),
        const SizedBox(width: 10),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Text(name, maxLines: 1, overflow: TextOverflow.ellipsis, style: T.label.copyWith(color: p.text)),
              if (size > 0 || sub != null) Text(sub ?? bytesText(size), maxLines: 1, style: T.tiny.copyWith(color: p.text3)),
            ],
          ),
        ),
      ],
    );
  }
}

IconData fileIcon(String name) => switch (Media.ext(name)) {
  'png' || 'jpg' || 'jpeg' || 'gif' || 'webp' || 'heic' || 'svg' => LucideIcons.image,
  'pdf' => LucideIcons.fileText,
  'zip' || 'gz' || 'tar' || 'rar' || '7z' => LucideIcons.fileArchive,
  'mp4' || 'mov' || 'webm' => LucideIcons.fileVideo,
  'mp3' || 'wav' || 'm4a' => LucideIcons.fileAudio,
  'csv' || 'xlsx' || 'xls' => LucideIcons.fileSpreadsheet,
  'md' || 'txt' || 'log' || 'doc' || 'docx' => LucideIcons.fileText,
  'json' || 'yaml' || 'yml' || 'toml' => LucideIcons.fileJson,
  'html' || 'css' || 'js' || 'ts' || 'tsx' || 'jsx' || 'py' || 'dart' || 'go' || 'rs' || 'java' || 'kt' || 'swift' || 'c' || 'cpp' || 'cs' || 'php' || 'rb' || 'sh' || 'ps1' || 'sql' => LucideIcons.fileCode,
  _ => LucideIcons.file,
};

Color? fileColor(String name, Pal p) => switch (Media.ext(name)) {
  'png' || 'jpg' || 'jpeg' || 'gif' || 'webp' || 'svg' || 'heic' => p.good,
  'pdf' => p.bad,
  'html' || 'css' || 'js' || 'ts' || 'tsx' || 'jsx' || 'py' || 'dart' || 'go' || 'rs' || 'java' || 'kt' || 'swift' || 'c' || 'cpp' || 'cs' || 'php' || 'rb' => p.accent,
  _ => null,
};

/// Photos and files inside a sent message.
class SentFiles extends StatelessWidget {
  const SentFiles(this.items, {super.key});
  final List<Shot> items;
  @override
  Widget build(BuildContext context) {
    final p = context.p;
    final imgs = [for (final s in items) if (s.image != null) s];
    final rest = [for (final s in items) if (s.image == null) s];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        if (imgs.isNotEmpty)
          Wrap(
            spacing: 6,
            runSpacing: 6,
            alignment: WrapAlignment.end,
            children: [
              for (final (i, s) in imgs.indexed)
                Press(
                  onTap: () => viewImages(context, [for (final x in imgs) x.image!], i),
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(18),
                    child: Image(
                      image: ResizeImage.resizeIfNeeded(900, null, s.image!),
                      width: imgs.length == 1 ? 220 : 128,
                      height: imgs.length == 1 ? null : 128,
                      fit: BoxFit.cover,
                      frameBuilder: (_, child, frame, sync) => sync || frame != null ? child : Bone(w: imgs.length == 1 ? 220 : 128, h: imgs.length == 1 ? 160 : 128, r: 18),
                      errorBuilder: (_, _, _) => Container(width: 128, height: 96, color: p.fill, child: Icon(LucideIcons.imageOff, color: p.text3)),
                    ),
                  ),
                ),
            ],
          ),
        for (final s in rest)
          Container(
            width: 240,
            margin: const EdgeInsets.only(top: 6),
            padding: const EdgeInsets.all(11),
            decoration: BoxDecoration(color: p.fill, borderRadius: BorderRadius.circular(16)),
            child: FileLine(s.name, s.size),
          ),
      ],
    );
  }
}

/// One thing in a message: a picture, or a file's name.
class Shot {
  Shot(this.name, {this.image, this.size = 0});
  final String name;
  final int size;
  final ImageProvider? image;

  factory Shot.local(Att a) => Shot(a.label, size: a.size, image: a.isImage ? FileImage(a.file) : null);

  /// From a thread on a computer: {uri, name, mime}.
  factory Shot.remote(J f, Pc pc) {
    final uri = '${f['uri'] ?? ''}';
    final name = '${f['name'] ?? ''}'.isEmpty ? baseName(Uri.decodeFull(uri)) : '${f['name']}';
    if (uri.startsWith('data:image/')) {
      final b = _bytes[uri.hashCode] ??= base64Decode(uri.substring(uri.indexOf(',') + 1));
      return Shot(name, image: MemoryImage(b));
    }
    if (uri.startsWith('file:') && Media.mimeOf(name).startsWith('image/')) {
      var path = Uri.decodeFull(uri.replaceFirst(RegExp('^file://'), ''));
      if (RegExp(r'^/[A-Za-z]:').hasMatch(path)) path = path.substring(1);
      return Shot(name, image: NetworkImage(pc.imageUrl(path), headers: pc.headers));
    }
    return Shot(name);
  }
  static final Map<int, Uint8List> _bytes = {};
}

/// Pictures full screen: pinch, swipe between them, drag down to close, share.
Future<void> viewImages(BuildContext context, List<ImageProvider> images, int at) => Navigator.of(context, rootNavigator: true).push(
  PageRouteBuilder(
    opaque: false,
    barrierColor: Colors.transparent,
    transitionDuration: const Duration(milliseconds: 300),
    reverseTransitionDuration: const Duration(milliseconds: 200),
    pageBuilder: (_, a, _) => FadeTransition(
      opacity: CurvedAnimation(parent: a, curve: Curves.easeOut),
      child: _Viewer(images, at),
    ),
  ),
);

class _Viewer extends StatefulWidget {
  const _Viewer(this.images, this.at);
  final List<ImageProvider> images;
  final int at;
  @override
  State<_Viewer> createState() => _ViewerState();
}

class _ViewerState extends State<_Viewer> {
  late final _page = PageController(initialPage: widget.at);
  late int _at = widget.at;
  double _dy = 0;
  bool _zoomed = false;

  @override
  void dispose() {
    _page.dispose();
    super.dispose();
  }

  Future<void> _share() async {
    final img = widget.images[_at];
    String? path;
    if (img is FileImage) path = img.file.path;
    if (img is MemoryImage) path = (await (await File('${Directory.systemTemp.path}/afh-${newId()}.png').create()).writeAsBytes(img.bytes)).path;
    if (path != null) await SharePlus.instance.share(ShareParams(files: [XFile(path)]));
  }

  @override
  Widget build(BuildContext context) {
    final k = (1 - _dy.abs() / 400).clamp(0.0, 1.0);
    return Scaffold(
      backgroundColor: Colors.black.withValues(alpha: .96 * k),
      body: Stack(
        children: [
          GestureDetector(
            onVerticalDragUpdate: _zoomed ? null : (d) => setState(() => _dy += d.delta.dy),
            onVerticalDragEnd: _zoomed
                ? null
                : (d) {
                    if (_dy.abs() > 110 || (d.primaryVelocity ?? 0).abs() > 900) {
                      Navigator.pop(context);
                    } else {
                      setState(() => _dy = 0);
                    }
                  },
            child: Transform.translate(
              offset: Offset(0, _dy),
              child: Transform.scale(
                scale: .9 + .1 * k,
                child: PageView.builder(
                  controller: _page,
                  physics: _zoomed ? const NeverScrollableScrollPhysics() : const BouncingScrollPhysics(),
                  itemCount: widget.images.length,
                  onPageChanged: (i) => setState(() => _at = i),
                  itemBuilder: (_, i) => ZoomBox(
                    onZoom: (z) => z == _zoomed ? null : setState(() => _zoomed = z),
                    child: Center(
                      child: Image(
                        image: widget.images[i],
                        errorBuilder: (_, _, _) => const Icon(LucideIcons.imageOff, color: Colors.white54, size: 40),
                        loadingBuilder: (_, c, l) => l == null ? c : const Pulse(size: 26),
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              child: Row(
                children: [
                  Ic(LucideIcons.x, color: Colors.white, fill: Colors.white12, onTap: () => Navigator.pop(context)),
                  const Spacer(),
                  if (widget.images.length > 1) Text('${_at + 1} / ${widget.images.length}', style: T.label.copyWith(color: Colors.white)),
                  const Spacer(),
                  if (widget.images[_at] is! NetworkImage) Ic(LucideIcons.share2, color: Colors.white, fill: Colors.white12, onTap: _share) else const SizedBox(width: 40),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Pinch and double-tap to zoom.
class ZoomBox extends StatefulWidget {
  const ZoomBox({super.key, required this.child, this.onZoom});
  final Widget child;
  final ValueChanged<bool>? onZoom;
  @override
  State<ZoomBox> createState() => _ZoomBoxState();
}

class _ZoomBoxState extends State<ZoomBox> with SingleTickerProviderStateMixin {
  final _t = TransformationController();
  late final _c = AnimationController(vsync: this, duration: med);
  Animation<Matrix4>? _a;
  Offset _at = Offset.zero;

  @override
  void initState() {
    super.initState();
    _t.addListener(() => widget.onZoom?.call(_t.value.getMaxScaleOnAxis() > 1.02));
    _c.addListener(() {
      if (_a != null) _t.value = _a!.value;
    });
  }

  @override
  void dispose() {
    _t.dispose();
    _c.dispose();
    super.dispose();
  }

  void _double() {
    final big = _t.value.getMaxScaleOnAxis() > 1.02;
    final to = big
        ? Matrix4.identity()
        : (Matrix4.identity()
            ..translateByDouble(-_at.dx * 1.4, -_at.dy * 1.4, 0, 1)
            ..scaleByDouble(2.4, 2.4, 1, 1));
    _a = Matrix4Tween(begin: _t.value, end: to).animate(CurvedAnimation(parent: _c, curve: Curves.easeOutCubic));
    _c.forward(from: 0);
  }

  @override
  Widget build(BuildContext context) => GestureDetector(
    onDoubleTapDown: (d) => _at = d.localPosition,
    onDoubleTap: _double,
    child: InteractiveViewer(transformationController: _t, maxScale: 6, minScale: 1, child: widget.child),
  );
}

/// Photo, camera, file: the choices behind the paperclip.
Future<List<Att>> addSheet(BuildContext context, {List<Widget> extra = const []}) async {
  final clip = await Native.hasPicture();
  if (!context.mounted) return const [];
  final what = await sheet<String>(
    context,
    title: t('Add'),
    (c) => Padding(
      padding: EdgeInsets.fromLTRB(gutter, 2, gutter, 18 + MediaQuery.paddingOf(c).bottom),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              for (final (i, (id, icon, label)) in [('photos', LucideIcons.images, t('Photos')), ('camera', LucideIcons.camera, t('Camera')), ('files', LucideIcons.folderOpen, t('Files'))].indexed) ...[
                if (i > 0) const SizedBox(width: 10),
                Expanded(
                  child: Rise(
                    i,
                    child: Press(
                      onTap: () => Navigator.pop(c, id),
                      child: Container(
                        height: 92,
                        decoration: BoxDecoration(color: c.p.fill, borderRadius: BorderRadius.circular(20)),
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [Icon(icon, size: 24, color: c.p.text), const SizedBox(height: 9), Text(label, style: T.label.copyWith(color: c.p.text))],
                        ),
                      ),
                    ),
                  ),
                ),
              ],
            ],
          ),
          if (clip) ...[const SizedBox(height: 10), Tile(t('Paste the copied picture'), icon: LucideIcons.clipboardPaste, onTap: () => Navigator.pop(c, 'clip'))],
          if (extra.isNotEmpty) ...[const SizedBox(height: 10), ...extra],
        ],
      ),
    ),
  );
  try {
    return switch (what) {
      'photos' => await pickPhotos(),
      'camera' => await pickPhotos(camera: true),
      'files' => await pickFiles(),
      'clip' => [?await Native.picture()],
      _ => const [],
    };
  } catch (e) {
    if (context.mounted) toast(context, t('Couldn\'t open that. Check the app\'s permissions.'), bad: true);
    return const [];
  }
}

double clampD(double v, double a, double b) => math.max(a, math.min(b, v));
