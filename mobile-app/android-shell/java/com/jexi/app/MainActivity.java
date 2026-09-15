package com.jexi.app;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.Message;
import android.view.Gravity;
import android.view.View;
import android.view.Window;
import android.webkit.CookieManager;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import org.json.JSONObject;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * Jexi app shell.
 * The app IS the JEXI Market website — it opens https://jexi-web.vercel.app
 * in a full-screen WebView, so the phone always shows exactly what the web
 * shows (same sign-in page, same everything, always current).
 *
 * Native extras kept minimal:
 *  - update gate: if the server says the shell itself is too old, block with
 *    a warm "Update your app" screen pointing at the new APK;
 *  - offline screen: if the site cannot be reached, offer a retry;
 *  - Google sign-in: popups do not exist in a WebView, so window.open is
 *    redirected into this window; the server callback then bounces back to
 *    the site with #gt=<token>, which the site turns into a session.
 */
public class MainActivity extends Activity {

    private static final String SITE_URL = "https://jexi-web.vercel.app";
    private static final String VERSION_URL = "https://jexi-server.vercel.app/api/version";
    private static final String SHELL_VERSION = "1.4.0";
    private static final String BG = "#0c0b09";

    private WebView web;
    private View overlay;   // update / offline screen currently covering the webview
    private final Handler ui = new Handler(Looper.getMainLooper());

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        Window w = getWindow();
        w.setStatusBarColor(Color.parseColor(BG));
        w.setNavigationBarColor(Color.parseColor(BG));

        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setSupportZoom(false);
        s.setMediaPlaybackRequiresUserGesture(false);
        // Look like Chrome, not a WebView: keeps Google sign-in happy.
        String ua = s.getUserAgentString();
        if (ua != null) {
            ua = ua.replace("; wv)", ")").replace("Version/4.0 ", "");
            s.setUserAgentString(ua);
        }
        CookieManager cm = CookieManager.getInstance();
        cm.setAcceptCookie(true);
        cm.setAcceptThirdPartyCookies(web, true);

        web.setBackgroundColor(Color.parseColor(BG));
        web.setOverScrollMode(View.OVER_SCROLL_NEVER);

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest req) {
                Uri u = req.getUrl();
                String scheme = u.getScheme() == null ? "" : u.getScheme();
                String host = u.getHost() == null ? "" : u.getHost();
                boolean inApp = "https".equals(scheme) && (
                        host.equals("jexi-web.vercel.app")
                        || host.equals("jexi-server.vercel.app")
                        || host.endsWith(".vercel.app")
                        || host.equals("accounts.google.com"));
                if (inApp) return false;
                if ("http".equals(scheme) || "https".equals(scheme)) {
                    try {
                        startActivity(new Intent(Intent.ACTION_VIEW, u));
                    } catch (Exception ignored) {
                    }
                    return true;
                }
                return false;
            }

            @Override
            public void onReceivedError(WebView v, WebResourceRequest req, WebResourceError err) {
                if (req.isForMainFrame()) {
                    ui.post(() -> showOverlay(buildMessageScreen(
                            "No internet",
                            "Jexi needs a connection to open. Check Wi-Fi or data, then try again.",
                            "Try again", v1 -> {
                                hideOverlay();
                                setContentView(web);
                                web.reload();
                            })));
                }
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onCreateWindow(WebView view, boolean isDialog,
                                          boolean isUserGesture, Message resultMsg) {
                // No popups in a WebView: load the target in the main window
                // instead. Used by Google sign-in (full-page OAuth flow).
                WebView temp = new WebView(view.getContext());
                temp.setWebViewClient(new WebViewClient() {
                    @Override
                    public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest req) {
                        Uri u = req.getUrl();
                        if (u.toString().startsWith("about:")) return false;
                        web.loadUrl(u.toString());
                        return true;
                    }
                });
                WebView.WebViewTransport t = (WebView.WebViewTransport) resultMsg.obj;
                t.setWebView(temp);
                resultMsg.sendToTarget();
                return true;
            }
        });

        if (savedInstanceState != null) {
            web.restoreState(savedInstanceState);
        } else {
            web.loadUrl(SITE_URL);
        }
        setContentView(web);

        checkVersion();
    }

    // ---------------- update gate ----------------

    private void checkVersion() {
        new Thread(() -> {
            String minRequired = null, notes = "", downloadUrl = "";
            try {
                HttpURLConnection c = (HttpURLConnection) new URL(VERSION_URL).openConnection();
                c.setConnectTimeout(8000);
                c.setReadTimeout(8000);
                c.setRequestProperty("Accept", "application/json");
                StringBuilder sb = new StringBuilder();
                try (BufferedReader r = new BufferedReader(
                        new InputStreamReader(c.getInputStream(), StandardCharsets.UTF_8))) {
                    String line;
                    while ((line = r.readLine()) != null) sb.append(line);
                }
                JSONObject j = new JSONObject(sb.toString());
                minRequired = j.optString("minRequired", null);
                notes = j.optString("notes", "");
                downloadUrl = j.optString("url", "");
            } catch (Exception ignored) {
                return; // server unreachable: the site itself will show an error state
            }
            if (minRequired != null && !minRequired.isEmpty()
                    && semverLt(SHELL_VERSION, minRequired) && !downloadUrl.isEmpty()) {
                final String dl = downloadUrl, nt = notes;
                ui.post(() -> {
                    if (isFinishing()) return;
                    showOverlay(buildMessageScreen(
                            "Update your app",
                            nt.isEmpty() ? "A newer version of the Jexi app is ready. Get it to keep going."
                                         : nt + "\n\nGet the latest version to keep going.",
                            "Get the latest version",
                            v -> {
                                try {
                                    startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(dl)));
                                } catch (Exception ignored) {
                                }
                            }));
                });
            }
        }).start();
    }

    static boolean semverLt(String a, String b) {
        try {
            String[] pa = a.split("\\."), pb = b.split("\\.");
            int n = Math.max(pa.length, pb.length);
            for (int i = 0; i < n; i++) {
                int x = i < pa.length ? Integer.parseInt(pa[i].replaceAll("[^0-9].*$", "")) : 0;
                int y = i < pb.length ? Integer.parseInt(pb[i].replaceAll("[^0-9].*$", "")) : 0;
                if (x != y) return x < y;
            }
        } catch (Exception ignored) {
        }
        return false;
    }

    // ---------------- warm native screens ----------------

    private View buildMessageScreen(String title, String body, String buttonText, View.OnClickListener onClick) {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER);
        root.setBackgroundColor(Color.parseColor(BG));
        int pad = (int) (32 * getResources().getDisplayMetrics().density);
        root.setPadding(pad, pad, pad, pad);

        TextView mark = new TextView(this);
        mark.setText("Jexi");
        mark.setTextColor(Color.parseColor("#ff7a3d"));
        mark.setTextSize(30);
        mark.setTypeface(Typeface.DEFAULT_BOLD);
        mark.setGravity(Gravity.CENTER);
        mark.setPadding(0, 0, 0, (int) (10 * getResources().getDisplayMetrics().density));
        root.addView(mark);

        TextView t = new TextView(this);
        t.setText(title);
        t.setTextColor(Color.parseColor("#f3eee6"));
        t.setTextSize(24);
        t.setTypeface(Typeface.DEFAULT_BOLD);
        t.setGravity(Gravity.CENTER);
        root.addView(t);

        TextView b = new TextView(this);
        b.setText(body);
        b.setTextColor(Color.parseColor("#a99f90"));
        b.setTextSize(15);
        b.setLineSpacing(0, 1.25f);
        b.setGravity(Gravity.CENTER);
        b.setPadding(0, (int) (12 * getResources().getDisplayMetrics().density), 0,
                (int) (24 * getResources().getDisplayMetrics().density));
        root.addView(b);

        Button btn = new Button(this);
        btn.setText(buttonText);
        btn.setAllCaps(false);
        btn.setTextSize(16);
        btn.setTypeface(Typeface.DEFAULT_BOLD);
        btn.setTextColor(Color.parseColor("#141210"));
        GradientDrawable gd = new GradientDrawable();
        gd.setColor(Color.parseColor("#ff7a3d"));
        gd.setCornerRadius(24 * getResources().getDisplayMetrics().density);
        btn.setBackground(gd);
        btn.setPadding(pad, (int) (14 * getResources().getDisplayMetrics().density), pad,
                (int) (14 * getResources().getDisplayMetrics().density));
        btn.setOnClickListener(onClick);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        root.addView(btn, lp);
        return root;
    }

    private void showOverlay(View v) {
        overlay = v;
        setContentView(overlay);
    }

    private void hideOverlay() {
        overlay = null;
    }

    // ---------------- lifecycle ----------------

    @Override
    public void onBackPressed() {
        if (overlay != null) {
            // update/offline screen: let the user leave normally
            super.onBackPressed();
        } else if (web != null && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        if (web != null) {
            web.saveState(outState);
        }
    }
}
