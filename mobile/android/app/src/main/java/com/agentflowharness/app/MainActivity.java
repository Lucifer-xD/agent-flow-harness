package com.agentflowharness.app;

import android.webkit.WebView;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    // Back goes back a page (AFH on a computer -> the list of computers) before it leaves the app.
    @Override
    public void onBackPressed() {
        WebView web = getBridge() != null ? getBridge().getWebView() : null;
        if (web != null && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
