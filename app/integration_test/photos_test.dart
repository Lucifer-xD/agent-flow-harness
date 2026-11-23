// A photo goes from an old chat (one written by app 1.x) to the model, on a real device or simulator:
//   flutter test integration_test/photos_test.dart -d <device>
import 'dart:convert';
import 'dart:io';

import 'package:afh_app/core/store.dart';
import 'package:afh_app/main.dart' as app;
import 'package:afh_app/ui/composer.dart';
import 'package:afh_app/ui/kit.dart' show LucideIcons;
import 'package:afh_app/ui/media.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker_platform_interface/image_picker_platform_interface.dart';
import 'package:integration_test/integration_test.dart';
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _Gallery extends ImagePickerPlatform {
  _Gallery(this.path);
  final String path;
  @override
  Future<List<XFile>> getMultiImageWithOptions({MultiImagePickerOptions options = const MultiImagePickerOptions()}) async => [XFile(path)];
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('a HEIC photo, sent in an old chat', (tester) async {
    final got = <Map<String, dynamic>>[];
    final server = await HttpServer.bind('127.0.0.1', 0);
    server.listen((r) async {
      final body = await utf8.decoder.bind(r).join();
      if (r.uri.path.endsWith('/models')) {
        r.response.headers.contentType = ContentType.json;
        r.response.write(jsonEncode({'data': [{'id': 'eyes'}]}));
      } else {
        got.add(jsonDecode(body) as Map<String, dynamic>);
        r.response.headers.set('content-type', 'text/event-stream');
        final say = jsonEncode({
          'choices': [
            {'index': 0, 'delta': {'content': 'I see it.'}},
          ],
        });
        r.response.write('data: $say\n\ndata: [DONE]\n\n');
      }
      await r.response.close();
    });

    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool('onboarded', true);
    await prefs.setString('base.custom', 'http://127.0.0.1:${server.port}/v1');
    await prefs.setBool('asked.notify', true);
    await prefs.setString('models', jsonEncode({'custom': ['eyes']}));
    final dir = Directory('${(await getApplicationSupportDirectory()).path}/chats');
    await dir.create(recursive: true);
    await File('${dir.path}/old1.json').writeAsString(jsonEncode({
      'id': 'old1', 'title': 'An old chat', 'provider': 'custom', 'model': 'eyes', 'updated': 1730000000000, 'pinned': false,
      'messages': [
        {'role': 'user', 'text': 'Hello', 'at': 1730000000000, 'images': ['/var/mobile/gone/photo.jpg']},
        {'role': 'assistant', 'text': 'Hi', 'model': 'eyes', 'at': 1730000001000},
      ],
    }));
    final heic = File('${(await getTemporaryDirectory()).path}/IMG_0001.HEIC');
    await heic.writeAsBytes(base64Decode(_heic));
    ImagePickerPlatform.instance = _Gallery(heic.path);

    await app.main();
    Future<void> wait([int ms = 900]) async {
      for (var i = 0; i < ms ~/ 50; i++) {
        await tester.pump(const Duration(milliseconds: 50));
      }
    }

    Future<void> until(bool Function() ok) async {
      for (var i = 0; i < 200 && !ok(); i++) {
        await wait(100);
      }
      expect(ok(), isTrue);
    }

    await until(() => Chats.i.byId('old1') != null && find.text('Chats').evaluate().isNotEmpty);
    await wait(1500);
    await tester.tap(find.text('Chats').last);
    await until(() => find.text('An old chat').evaluate().isNotEmpty);
    await wait();
    await tester.tap(find.text('An old chat').last);
    await until(() => find.byType(Composer).evaluate().isNotEmpty);
    await wait();
    await tester.tap(find.byIcon(LucideIcons.plus).hitTestable().last);
    await until(() => find.text('Photos').evaluate().isNotEmpty);
    await wait();
    await tester.tap(find.text('Photos').last);
    await until(() => find.byType(AttStrip).evaluate().isNotEmpty && find.byIcon(LucideIcons.x).evaluate().isNotEmpty);
    await wait();
    await tester.tap(find.byIcon(LucideIcons.arrowUp).hitTestable().last);
    await until(() => got.isNotEmpty);
    await wait(1500);

    final last = (got.first['messages'] as List).last as Map;
    final url = ((last['content'] as List).firstWhere((x) => x['type'] == 'image_url') as Map)['image_url']['url'] as String;
    expect(url, startsWith('data:image/png;base64,'));
    final png = base64Decode(url.split(',').last);
    expect(Media.kindOf(png), 'png');
    expect(Chats.i.byId('old1')!.messages[2].files.single.mime, 'image/png');
    expect(find.text('I see it.'), findsWidgets);
    Chats.i.delete(Chats.i.byId('old1')!);
    await prefs.remove('base.custom');
    await server.close(force: true);
  });
}

const _heic =
    'AAAAHGZ0eXBoZWljAAAAAG1pZjFoZWljbWlhZgAAAVdtZXRhAAAAAAAAACFoZGxyAAAAAAAAAABwaWN0AAAAAAAAAAAAAAAAAAAAACJpbG9jAAAAAERAAAEAAQAAAAABewABAAAAAAAAA5oAAAAjaWluZgAAAAAAAQAAABVpbmZlAgAAAAABAABodmMxAAAAAA5waXRtAAAAAAABAAAA12lwcnAAAAC4aXBjbwAAAHlodmNDAQNwAAAAkAAAAAAAWvAA/P34+AAADwNgAAEAGEABDAH//wNwAAADAJAAAAMAAAMAWroCQGEAAQAsQgEBA3AAAAMAkAAAAwAAAwBaoAUCAeFlupJKa5uAhoMCAAADADIAAAMAAhBiAAEAB0QBwXKwYkAAAAATY29scm5jbHgAAQANAAaAAAAAFGlzcGUAAAAAAAACgAAAAeAAAAAQcGl4aQAAAAADCAgIAAAAF2lwbWEAAAAAAAAAAQABBIECAwQAAAOibWRhdAAAA5YoAa9RAiXdnRvdmxvg+IRrX3yilDPXrojWcn538z8jyLvtFjrAfniHR5Wu2Ph7AdmjjR1wnbJDV5irkVYz+Cii8gEaY5k4Cr2i7FZNEUGCaEq1d8Phy7dKU/EsLon+jIfjsp4yveQNf11GQOHxGycMLHGknxv+vymivNZn0x8q67S01ihiJpLQfg6sQ0lQBqAKyYXwFsow5yKH/SQ2RlDxQt7JcqC50UDVvtFcauNoiV3NdbB5AG9a0/lTe5rBehvprAgE0AePBEx1OgdH2/TXMK/6LoUPXb4iIU9D5rN7U+zxgJ7RFGGg7uY4w8BU3Zk0LWG0Ze6t++NOfs2Om6mkV0ps5UPsqKLFH7lnecqaFtLujNMwkMMF0qzTMrfYJZlCj+MP0RMGAERHEf11nPsCBnOQeFxE4377ou/nkva2KUchtdd5kaSo2XnlHo2F7MsRq6afJ4sgog2Xk1taK7iyiICGiJV8JUSQpC+pC2/Szewmtj5pXEH3SnFSOp3NuZ5sn7p+HHdNXol/yriJjUC8qLCYCPtUX8IAiQI1ksNQYMqojAduMOP9Z//TNOYE8Y70BlSle67Qugdu3bc+6SeXvX7EugSXWA5BmdhC5/NjSWDiuAOPzJY8Bf1B0lYPlxcVRZRIH4FJnCWSNphpyldhxB9UPMmInJ0uNUw51zmqiBAs1Bwc3ej84uzKilKWQhzUZur3fq0hak2p7nCI1ytr9SeP8bPXa4U4mv8fmfTKNXjenGXE+kJ/e0gCIU6aBpRrPWC8bjfTiUwjm5bAlj4aej6Gk/0zB7PggBIkMhR72iLfpk2xbqtoINMRATHGBtkjn2mPh9TIMMiyqEgOmvhlFFMoH83ttzWYL3uxeZ6KAWiooDIsRgSPo325YnweXdf32WLrTn3pWLzs3R1vYHGpdqXjZ2e2jIqfD3LJl/U4GooIVY+zs3PsRhwhKrNhoXq9IRDr16PnJE5wU8G2Zj6T5pSiiX1lU4V6OJStCauueXjIe0wy+Db4YoIHGpsybbcV8F9x/L6k9RyuBvAcIj8E7W0pSkWmHCZFxj/3Wdri8V06+zpfsoA+9DCRtgSRiv390cQ3HqSNteWxaEBudJ3sCyV+EnlcEXkDM3DlDW3ipdSxeQ9AgxHybbavMx98WxjYWJPS2q3JyIqU2wsTSdrbQ8rt/zAT0lXLwVfTibfX06OsoSeaquvp5mKMlAAJkKVn5UoWysA=';
