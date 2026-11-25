import 'package:afh_app/ui/keys.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  Future<FocusNode> open(WidgetTester t, {VoidCallback? onList, VoidCallback? onSend}) async {
    t.view.devicePixelRatio = 1;
    t.view.physicalSize = const Size(400, 800);
    addTearDown(t.view.reset);
    final f = FocusNode();
    addTearDown(f.dispose);
    await t.pumpWidget(
      MaterialApp(
        builder: (_, c) => KeyboardAway(child: c!),
        home: Scaffold(
          body: Column(
            children: [
              Expanded(child: GestureDetector(onTap: onList, behavior: HitTestBehavior.opaque, child: const SizedBox.expand(key: Key('list')))),
              TextFieldTapRegion(
                child: Column(
                  children: [
                    TextField(focusNode: f, maxLines: 7, minLines: 1),
                    TextButton(onPressed: onSend, child: const Text('Add')),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
    f.requestFocus();
    t.view.viewInsets = const FakeViewPadding(bottom: 300);
    await t.pumpAndSettle();
    expect(f.hasFocus, isTrue);
    return f;
  }

  testWidgets('a tap outside closes it and still does its own job', (t) async {
    var tapped = 0;
    final f = await open(t, onList: () => tapped++);
    await t.tap(find.byKey(const Key('list')));
    await t.pumpAndSettle();
    expect(f.hasFocus, isFalse);
    expect(tapped, 1);
  });

  testWidgets("the box and the composer's buttons keep it", (t) async {
    var sent = 0;
    final f = await open(t, onSend: () => sent++);
    await t.tap(find.byType(TextField));
    await t.tap(find.text('Add'));
    await t.pumpAndSettle();
    expect(f.hasFocus, isTrue);
    expect(sent, 1);
  });

  testWidgets('a swipe down closes it, from the composer too; up or sideways does not', (t) async {
    final f = await open(t);
    await t.drag(find.byKey(const Key('list')), const Offset(0, -80));
    await t.drag(find.byKey(const Key('list')), const Offset(90, 10));
    await t.pumpAndSettle();
    expect(f.hasFocus, isTrue);
    await t.drag(find.text('Add'), const Offset(0, 80));
    await t.pumpAndSettle();
    expect(f.hasFocus, isFalse);
  });

  testWidgets('a tap that opens the box again wins', (t) async {
    late FocusNode f;
    f = await open(t, onList: () => f.requestFocus());
    await t.tap(find.byKey(const Key('list')));
    await t.pumpAndSettle();
    expect(f.hasFocus, isTrue);
  });
}
