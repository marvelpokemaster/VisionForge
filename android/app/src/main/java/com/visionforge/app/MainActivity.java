package com.visionforge.app;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.util.Log;
import android.webkit.JavascriptInterface;
import android.webkit.PermissionRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import androidx.core.content.ContextCompat;
import com.getcapacitor.BridgeActivity;
import com.getcapacitor.BridgeWebChromeClient;
import com.google.android.gms.auth.api.signin.GoogleSignIn;
import com.google.android.gms.auth.api.signin.GoogleSignInAccount;
import com.google.android.gms.auth.api.signin.GoogleSignInClient;
import com.google.android.gms.auth.api.signin.GoogleSignInOptions;
import com.google.android.gms.common.api.ApiException;
import com.google.android.gms.tasks.Task;

public class MainActivity extends BridgeActivity {
    private static final int RC_SIGN_IN = 9001;
    private static final String WEB_CLIENT_ID = "1080658765469-vticakrafv4i6remp5eebn69930jjloq.apps.googleusercontent.com";
    private GoogleSignInClient mGoogleSignInClient;

    public class AndroidGoogleAuthInterface {
        @JavascriptInterface
        public void launchGoogleSignIn() {
            runOnUiThread(() -> {
                try {
                    GoogleSignInOptions gso = new GoogleSignInOptions.Builder(GoogleSignInOptions.DEFAULT_SIGN_IN)
                        .requestIdToken(WEB_CLIENT_ID)
                        .requestEmail()
                        .build();

                    mGoogleSignInClient = GoogleSignIn.getClient(MainActivity.this, gso);
                    mGoogleSignInClient.signOut().addOnCompleteListener(MainActivity.this, task -> {
                        Intent signInIntent = mGoogleSignInClient.getSignInIntent();
                        startActivityForResult(signInIntent, RC_SIGN_IN);
                    });
                } catch (Exception e) {
                    Log.e("VisionForgeAuth", "Failed to launch Google Sign In: " + e.getMessage());
                    dispatchAuthResult(null, e.getMessage());
                }
            });
        }
    }

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        WebView.setWebContentsDebuggingEnabled(true);
        if (bridge != null && bridge.getWebView() != null) {
            WebView webView = bridge.getWebView();
            WebSettings settings = webView.getSettings();
            String ua = settings.getUserAgentString();
            settings.setUserAgentString(ua.replace("; wv", "").replaceAll("Version\\/\\d+\\.\\d+\\s?", ""));
            settings.setMediaPlaybackRequiresUserGesture(false);

            // Add JavaScript interface for native Google Sign-In
            webView.addJavascriptInterface(new AndroidGoogleAuthInterface(), "AndroidGoogleAuth");

            webView.setWebChromeClient(new BridgeWebChromeClient(bridge) {
                @Override
                public void onPermissionRequest(final PermissionRequest request) {
                    boolean hasCamera = ContextCompat.checkSelfPermission(
                        MainActivity.this, Manifest.permission.CAMERA
                    ) == PackageManager.PERMISSION_GRANTED;

                    if (hasCamera) {
                        runOnUiThread(() -> request.grant(request.getResources()));
                    } else {
                        super.onPermissionRequest(request);
                    }
                }
            });
        }
    }

    @Override
    public void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == RC_SIGN_IN) {
            Task<GoogleSignInAccount> task = GoogleSignIn.getSignedInAccountFromIntent(data);
            try {
                GoogleSignInAccount account = task.getResult(ApiException.class);
                if (account != null && account.getIdToken() != null) {
                    dispatchAuthResult(account.getIdToken(), null);
                } else {
                    dispatchAuthResult(null, "No ID token received from Google");
                }
            } catch (ApiException e) {
                Log.e("VisionForgeAuth", "Google sign in failed: status=" + e.getStatusCode() + ", msg=" + e.getMessage());
                dispatchAuthResult(null, "Google sign in failed (code " + e.getStatusCode() + "): " + e.getMessage());
            }
        }
    }

    private void dispatchAuthResult(String idToken, String error) {
        if (bridge != null && bridge.getWebView() != null) {
            bridge.getWebView().post(() -> {
                String js;
                if (idToken != null) {
                    js = "window.onGoogleNativeSuccess && window.onGoogleNativeSuccess('" + idToken + "');";
                } else {
                    String safeErr = error != null ? error.replace("'", "\\'") : "Unknown error";
                    js = "window.onGoogleNativeError && window.onGoogleNativeError('" + safeErr + "');";
                }
                bridge.getWebView().evaluateJavascript(js, null);
            });
        }
    }
}

