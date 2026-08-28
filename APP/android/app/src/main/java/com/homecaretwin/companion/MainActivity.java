package com.homecaretwin.companion;

import android.os.Bundle;
import android.webkit.WebSettings;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // Android Debug builds use the HTTPS Capacitor origin so cookies and the
        // service worker keep their normal semantics. Allowing a private-LAN HTTP
        // API therefore has to be explicit at the WebView layer as well. The
        // server URL validator still rejects public cleartext targets, and the
        // BuildConfig guard keeps this setting out of Release behavior.
        if (BuildConfig.DEBUG && getBridge() != null && getBridge().getWebView() != null) {
            WebSettings settings = getBridge().getWebView().getSettings();
            settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        }
    }
}
