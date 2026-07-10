package com.drowsiness.alert;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;

import androidx.core.app.NotificationCompat;

import java.io.IOException;

public class AlertService extends Service implements NanoHTTPDServer.AlertCallback {

    private static final int NOTIFICATION_ID = 1001;
    private static final String CHANNEL_ID = "alert_service_channel";

    private NanoHTTPDServer server;
    private DiscoveryBroadcaster broadcaster;
    private MainActivity boundActivity;
    private DiscoveryBroadcaster.PcDiscoveredListener pcListener;

    // Binder for activity binding
    public class LocalBinder extends android.os.Binder {
        public AlertService getService() {
            return AlertService.this;
        }
    }
    private final IBinder binder = new LocalBinder();

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(NOTIFICATION_ID, buildNotification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
        } else {
            startForeground(NOTIFICATION_ID, buildNotification());
        }
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (server == null) {
            server = new NanoHTTPDServer(5000, this);
            try {
                server.start();
            } catch (IOException e) {
                stopSelf();
            }
        }
        if (broadcaster == null) {
            broadcaster = new DiscoveryBroadcaster(5000);
            broadcaster.setPcDiscoveredListener(ip -> {
                if (pcListener != null) {
                    pcListener.onPcDiscovered(ip);
                }
            });
            broadcaster.start();
        }
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        if (server != null) {
            server.stop();
            server = null;
        }
        if (broadcaster != null) {
            broadcaster.stop();
            broadcaster = null;
        }
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return binder;
    }

    public void setBoundActivity(MainActivity activity) {
        this.boundActivity = activity;
    }

    public void setPcDiscoveredListener(DiscoveryBroadcaster.PcDiscoveredListener listener) {
        this.pcListener = listener;
    }

    public String getPcIp() {
        return broadcaster != null ? broadcaster.getPcIp() : null;
    }

    // ── Alert callbacks ──────────────────────────────────────────

    @Override
    public void onAlert(String type, long timestamp) {
        if (boundActivity != null) {
            boundActivity.runOnUiThread(() -> boundActivity.showAlert(type, timestamp));
        }
    }

    @Override
    public void onClear(long timestamp) {
        if (boundActivity != null) {
            boundActivity.runOnUiThread(() -> boundActivity.clearAlert(timestamp));
        }
    }

    // ── Notification ─────────────────────────────────────────────

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                    CHANNEL_ID,
                    getString(R.string.service_channel),
                    NotificationManager.IMPORTANCE_LOW
            );
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) manager.createNotificationChannel(channel);
        }
    }

    private Notification buildNotification() {
        return new NotificationCompat.Builder(this, CHANNEL_ID)
                .setContentTitle(getString(R.string.app_name))
                .setContentText(getString(R.string.service_running))
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .build();
    }
}
