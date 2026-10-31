package com.agentflowharness.app;

import android.webkit.WebView;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    // Back closes a sheet or goes back a screen inside the app (window.afhBack answers whether it
    // did); on the first screen it sends the app to the background like other Android apps.
    @Override
    public void onBackPressed() {
        WebView web = getBridge() != null ? getBridge().getWebView() : null;
        if (web == null) {
            super.onBackPressed();
            return;
        }
        web.evaluateJavascript("(window.afhBack && window.afhBack()) ? 'y' : 'n'", (handled) -> {
            if (!"\"y\"".equals(handled)) moveTaskToBack(true);
        });
    }
}
