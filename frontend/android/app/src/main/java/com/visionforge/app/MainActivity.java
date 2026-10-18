package com.visionforge.app;

import android.os.Bundle;
import android.webkit.WebSettings;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if (bridge != null && bridge.getWebView() != null) {
            WebSettings settings = bridge.getWebView().getSettings();
            String ua = settings.getUserAgentString();
            settings.setUserAgentString(ua.replace("; wv", "").replaceAll("Version\\/\\d+\\.\\d+\\s?", ""));
        }
    }
}
