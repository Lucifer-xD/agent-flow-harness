package com.agentflowharness.app

import android.content.Intent
import android.net.Uri
import android.provider.OpenableColumns
import io.flutter.embedding.android.FlutterFragmentActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File
import kotlin.concurrent.thread

/** The app's window, plus what Flutter can't do itself: take what other apps share, and keep the
 *  connection open with a notification while work runs on a computer. */
class MainActivity : FlutterFragmentActivity() {
    private var channel: MethodChannel? = null
    private var pending: Map<String, Any?>? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        channel = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "afh/native").apply {
            setMethodCallHandler { call, result ->
                when (call.method) {
                    "shared" -> {
                        result.success(pending)
                        pending = null
                    }
                    "live" -> try {
                        LiveService.show(this@MainActivity, call.argument<String>("title") ?: "AFH", call.argument<String>("text") ?: "")
                        result.success(true)
                    } catch (e: Exception) { // the system may refuse it while the app is in the background
                        result.success(false)
                    }
                    "background" -> result.success(moveTaskToBack(true))
                    "liveStop" -> {
                        stopService(Intent(this@MainActivity, LiveService::class.java))
                        result.success(true)
                    }
                    else -> result.notImplemented()
                }
            }
        }
        take(intent)
    }

    override fun onDestroy() {
        if (isFinishing) stopService(Intent(this, LiveService::class.java))
        super.onDestroy()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        take(intent)
    }

    private fun take(i: Intent?) {
        if (i == null || (i.action != Intent.ACTION_SEND && i.action != Intent.ACTION_SEND_MULTIPLE)) return
        if (i.getBooleanExtra("afh.taken", false) || (i.flags and Intent.FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY) != 0) return
        i.putExtra("afh.taken", true)
        @Suppress("DEPRECATION")
        val uris: List<Uri> = if (i.action == Intent.ACTION_SEND) listOfNotNull(i.getParcelableExtra<Uri>(Intent.EXTRA_STREAM)) else i.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM) ?: emptyList()
        val text = listOfNotNull(i.getStringExtra(Intent.EXTRA_SUBJECT), i.getStringExtra(Intent.EXTRA_TEXT)).distinct().joinToString("\n")
        thread {
            val files = uris.take(10).mapNotNull { copyIn(it) }
            runOnUiThread {
                pending = mapOf("text" to text, "files" to files)
                channel?.invokeMethod("sharedNow", null)
            }
        }
    }

    private fun copyIn(uri: Uri): Map<String, Any?>? = try {
        var name = "file"
        contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c -> if (c.moveToFirst()) name = c.getString(0) ?: name }
        val mime = contentResolver.getType(uri) ?: "application/octet-stream"
        if (!name.contains('.') && mime.startsWith("image/")) name += "." + mime.substringAfter('/').replace("jpeg", "jpg")
        val dir = File(cacheDir, "shared").apply { mkdirs() }
        val out = File(dir, System.nanoTime().toString() + "-" + name.replace(Regex("[^\\w.\\- ]"), "_").takeLast(80))
        contentResolver.openInputStream(uri)!!.use { input -> out.outputStream().use { input.copyTo(it) } }
        mapOf("path" to out.path, "name" to name, "mime" to mime)
    } catch (e: Exception) {
        null
    }
}
