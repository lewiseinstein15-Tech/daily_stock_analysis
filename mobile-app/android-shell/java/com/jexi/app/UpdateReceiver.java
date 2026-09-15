package com.jexi.app;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInstaller;
import android.os.Bundle;
import android.provider.Settings;

/**
 * Receives the package-installer session status for in-app updates.
 * When Android needs the user to confirm the install, it launches the
 * confirmation dialog. If install is blocked (unknown sources), it opens the
 * relevant settings screen.
 */
public class UpdateReceiver extends BroadcastReceiver {

    @Override
    public void onReceive(Context ctx, Intent intent) {
        Bundle extras = intent.getExtras();
        if (extras == null) return;
        int status = extras.getInt(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);

        if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
            @SuppressWarnings("deprecation")
            Intent confirm = (Intent) extras.getParcelable(Intent.EXTRA_INTENT);
            if (confirm != null) {
                confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                try {
                    ctx.startActivity(confirm);
                    return;
                } catch (Exception ignored) {
                }
            }
            openInstallSettings(ctx);
        } else if (status == PackageInstaller.STATUS_FAILURE_BLOCKED) {
            openInstallSettings(ctx);
        }
        // STATUS_SUCCESS: Android shows its own "App installed" screen.
    }

    private static void openInstallSettings(Context ctx) {
        try {
            ctx.startActivity(new Intent(Settings.ACTION_SECURITY_SETTINGS)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        } catch (Exception ignored) {
        }
    }
}
