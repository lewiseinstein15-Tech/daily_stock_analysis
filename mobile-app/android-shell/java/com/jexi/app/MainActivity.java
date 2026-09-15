package com.jexi.app;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.PendingIntent;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInstaller;
import android.content.pm.PackageManager;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.Message;
import android.provider.Settings;
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
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * Jexi app shell.
 * The app IS the JEXI Market website — it opens https://jexi-web.vercel.app
 * in a full-screen WebView, so the phone always shows exactly what the web
 * shows (same sign-in page, same everything, always current).
 *
 * Native extras:
 *  - NO update screen at startup. The app always opens straight into JEXI.
 *  - App updates live in the site's Settings page: the web detects the shell
 *    version through the "jexiNative" bridge and calls installUpdate(url),
 *    which downloads the APK in-app with a live progress bar and hands it to
 *    Android's installer. On the web the same button downloads normally.
 *  - offline screen with retry;
 *  - Google sign-in: popups do not exist in a WebView, so window.open is
 *    redirected into this window; the server callback bounces back to the
 *    site with #gt=<token>, which the site turns into a session.
 */
public class MainActivity extends Activity {

    private static final String SITE_URL = "https://jexi-web.vercel.app";
    private static final String SHELL_VERSION = "1.6.0";
    private static final String BG = "#0c0b09";
    private static final int REQ_INSTALL_PERM = 4242;

    private WebView web;
    private ProgressBar pageProgress;
    private View overlay;
    private boolean updating = false;
    private String pendingUpdateUrl;   // waiting on the "allow installs" toggle
    private String lastUpdateUrl;      // last gate URL, for retry
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
        // window.open must open a real "window" for the popup bridge below.
        s.setSupportMultipleWindows(true);
        s.setJavaScriptCanOpenWindowsAutomatically(true);
        // Look like Chrome, not a WebView: keeps Google sign-in happy.
        String ua = s.getUserAgentString();
        if (ua != null) {
            ua = ua.replace("; wv)", ")").replace("Version/4.0 ", "");
            s.setUserAgentString(ua);
        }
        CookieManager cm = CookieManager.getInstance();
        cm.setAcceptCookie(true);
        cm.setAcceptThirdPartyCookies(web, true);

        // Bridge used by the site's Settings page ("App update" card).
        web.addJavascriptInterface(new NativeBridge(), "jexiNative");

        // Any .apk link clicked anywhere goes through the in-app updater.
        web.setDownloadListener((url, agent, disposition, mimetype, contentLength) -> {
            if (url != null && url.endsWith(".apk")) {
                startUpdateFlow(url);
            } else if (url != null && (url.startsWith("http://") || url.startsWith("https://"))) {
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
                } catch (Exception ignored) {
                }
            }
        });

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
                if (req.isForMainFrame() && !isFinishing()) {
                    ui.post(() -> {
                        if (overlay != null) return;
                        showOverlay(buildMessageScreen(
                                "No internet",
                                "Jexi needs a connection to open. Check Wi-Fi or data, then try again.",
                                "Try again", v1 -> {
                                    hideOverlay();
                                    setContentView(rootView());
                                    web.reload();
                                }, null, null));
                    });
                }
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onProgressChanged(WebView view, int newProgress) {
                if (pageProgress == null) return;
                if (newProgress >= 100) {
                    pageProgress.setVisibility(View.GONE);
                } else {
                    pageProgress.setVisibility(View.VISIBLE);
                    pageProgress.setProgress(newProgress);
                }
            }

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
        setContentView(rootView());
    }

    private View rootView() {
        FrameLayout root = new FrameLayout(this);
        root.addView(web, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));
        pageProgress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        pageProgress.setProgressTintList(ColorStateList.valueOf(Color.parseColor("#ff7a3d")));
        pageProgress.setProgressBackgroundTintList(ColorStateList.valueOf(Color.parseColor("#282318")));
        FrameLayout.LayoutParams plp = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, dp(3), Gravity.TOP);
        pageProgress.setLayoutParams(plp);
        pageProgress.setVisibility(View.GONE);
        root.addView(pageProgress);
        return root;
    }

    // ---------------- updates (triggered from the site's Settings page) ----------------

    private void startUpdateFlow(String url) {
        if (url == null || url.isEmpty() || updating) return;
        lastUpdateUrl = url;
        // One-time Android permission to let Jexi install updates.
        if (Build.VERSION.SDK_INT >= 26 && !getPackageManager().canRequestPackageInstalls()) {
            pendingUpdateUrl = url;
            try {
                Intent i = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                        Uri.parse("package:" + getPackageName()));
                startActivityForResult(i, REQ_INSTALL_PERM);
            } catch (Exception e) {
                downloadAndInstall(url);
            }
            return;
        }
        downloadAndInstall(url);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_INSTALL_PERM
                && Build.VERSION.SDK_INT >= 26
                && getPackageManager().canRequestPackageInstalls()
                && pendingUpdateUrl != null) {
            String url = pendingUpdateUrl;
            pendingUpdateUrl = null;
            downloadAndInstall(url);
        }
    }

    private ProgressBar updateBar;
    private TextView updateStatus;

    private void downloadAndInstall(String url) {
        if (updating) return;
        updating = true;

        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setGravity(Gravity.CENTER);
        box.setBackgroundColor(Color.parseColor(BG));
        int pad = dp(32);
        box.setPadding(pad, pad, pad, pad);

        TextView mark = new TextView(this);
        mark.setText("Jexi");
        mark.setTextColor(Color.parseColor("#ff7a3d"));
        mark.setTextSize(30);
        mark.setTypeface(Typeface.DEFAULT_BOLD);
        mark.setGravity(Gravity.CENTER);
        mark.setPadding(0, 0, 0, dp(10));
        box.addView(mark);

        TextView t = new TextView(this);
        t.setText("Updating Jexi");
        t.setTextColor(Color.parseColor("#f3eee6"));
        t.setTextSize(24);
        t.setTypeface(Typeface.DEFAULT_BOLD);
        t.setGravity(Gravity.CENTER);
        box.addView(t);

        updateBar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        updateBar.setMax(100);
        updateBar.setProgressTintList(ColorStateList.valueOf(Color.parseColor("#ff7a3d")));
        updateBar.setProgressBackgroundTintList(ColorStateList.valueOf(Color.parseColor("#282318")));
        box.addView(updateBar, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));
        ((LinearLayout.LayoutParams) updateBar.getLayoutParams()).setMargins(0, dp(22), 0, dp(10));

        updateStatus = new TextView(this);
        updateStatus.setText("Preparing…");
        updateStatus.setTextColor(Color.parseColor("#a99f90"));
        updateStatus.setTextSize(15);
        updateStatus.setGravity(Gravity.CENTER);
        box.addView(updateStatus);

        showOverlay(box);

        new Thread(() -> {
            PackageInstaller.Session session = null;
            try {
                HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
                c.setConnectTimeout(15000);
                c.setReadTimeout(30000);
                c.setInstanceFollowRedirects(true);
                c.setRequestProperty("Accept", "application/vnd.android.package-archive,*/*");
                final long len = c.getContentLengthLong();
                InputStream in = c.getInputStream();

                PackageManager pm = getPackageManager();
                PackageInstaller.SessionParams params =
                        new PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL);
                int sessionId = pm.getPackageInstaller().createSession(params);
                session = pm.getPackageInstaller().openSession(sessionId);
                OutputStream out = session.openWrite("jexi-update", 0, len > 0 ? len : -1);

                byte[] buf = new byte[65536];
                long total = 0;
                int n;
                long lastPost = 0;
                while ((n = in.read(buf)) > 0) {
                    out.write(buf, 0, n);
                    total += n;
                    long now = System.currentTimeMillis();
                    if (now - lastPost > 120) {
                        lastPost = now;
                        final int pct = len > 0 ? (int) Math.min(100, total * 100 / len) : -1;
                        final String msg = len > 0
                                ? "Downloading… " + pct + "%"
                                : "Downloading… " + (total / 1024) + " KB";
                        ui.post(() -> {
                            if (pct >= 0) updateBar.setProgress(pct);
                            else updateBar.setIndeterminate(true);
                            updateStatus.setText(msg);
                        });
                    }
                }
                out.flush();
                session.fsync(out);
                in.close();
                out.close();

                ui.post(() -> {
                    updateBar.setProgress(100);
                    updateBar.setIndeterminate(false);
                    updateStatus.setText("Almost there — tap Install when Android asks.");
                });

                Intent statusIntent = new Intent(this, UpdateReceiver.class);
                PendingIntent pi = PendingIntent.getBroadcast(this, sessionId, statusIntent,
                        PendingIntent.FLAG_MUTABLE);
                session.commit(pi.getIntentSender());
                session.close();
                session = null;
            } catch (Exception e) {
                if (session != null) {
                    try {
                        session.abandon();
                    } catch (Exception ignored) {
                    }
                }
                final String why = e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage();
                ui.post(() -> {
                    updating = false;
                    showOverlay(buildMessageScreen(
                            "Update failed",
                            "Could not download the update (" + why + "). Check your connection and try again.",
                            "Try again", v -> {
                                updating = false;
                                startUpdateFlow(lastUpdateUrl);
                            },
                            "Open in browser instead", v -> {
                                try {
                                    startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(lastUpdateUrl)));
                                } catch (Exception ignored) {
                                }
                            }));
                });
                return;
            }
            updating = false;
        }).start();
    }

    /**
     * Small bridge the web Settings page uses: it reads the shell version and
     * asks the app to download + install an update in place (progress bar,
     * then Android's installer). Only methods annotated @JavascriptInterface
     * are exposed, and only our own site is allowed to load in this WebView.
     */
    private class NativeBridge {
        @android.webkit.JavascriptInterface
        public String appVersion() {
            return SHELL_VERSION;
        }

        @android.webkit.JavascriptInterface
        public void installUpdate(String url) {
            if (url == null || !url.startsWith("https://")) return;
            ui.post(() -> startUpdateFlow(url));
        }
    }

    static boolean semverLt(String a, String b) {
        // Kept for future use (server-driven minimums); not used for gating anymore.
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

    private View buildMessageScreen(String title, String body,
                                    String primaryText, View.OnClickListener primaryClick,
                                    String secondaryText, View.OnClickListener secondaryClick) {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER);
        root.setBackgroundColor(Color.parseColor(BG));
        int pad = dp(32);
        root.setPadding(pad, pad, pad, pad);

        TextView mark = new TextView(this);
        mark.setText("Jexi");
        mark.setTextColor(Color.parseColor("#ff7a3d"));
        mark.setTextSize(30);
        mark.setTypeface(Typeface.DEFAULT_BOLD);
        mark.setGravity(Gravity.CENTER);
        mark.setPadding(0, 0, 0, dp(10));
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
        b.setPadding(0, dp(12), 0, dp(24));
        root.addView(b);

        Button btn = new Button(this);
        btn.setText(primaryText);
        btn.setAllCaps(false);
        btn.setTextSize(16);
        btn.setTypeface(Typeface.DEFAULT_BOLD);
        btn.setTextColor(Color.parseColor("#141210"));
        GradientDrawable gd = new GradientDrawable();
        gd.setColor(Color.parseColor("#ff7a3d"));
        gd.setCornerRadius(dp(24));
        btn.setBackground(gd);
        btn.setPadding(pad, dp(14), pad, dp(14));
        btn.setOnClickListener(primaryClick);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        root.addView(btn, lp);

        if (secondaryText != null) {
            TextView sec = new TextView(this);
            sec.setText(secondaryText);
            sec.setTextColor(Color.parseColor("#7a7163"));
            sec.setTextSize(13);
            sec.setGravity(Gravity.CENTER);
            sec.setPadding(0, dp(16), 0, 0);
            sec.setOnClickListener(secondaryClick);
            root.addView(sec);
        }
        return root;
    }

    private void showOverlay(View v) {
        overlay = v;
        setContentView(overlay);
    }

    private void hideOverlay() {
        overlay = null;
    }

    private int dp(int v) {
        return (int) (v * getResources().getDisplayMetrics().density);
    }

    // ---------------- lifecycle ----------------

    @Override
    public void onBackPressed() {
        if (overlay != null && !updating) {
            // update/offline screens: let the user leave normally
            super.onBackPressed();
        } else if (updating) {
            // don't back out mid-update
        } else if (web != null && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        // Persist session cookies so sign-in survives the app closing.
        CookieManager.getInstance().flush();
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        if (web != null) {
            web.saveState(outState);
        }
    }
}
