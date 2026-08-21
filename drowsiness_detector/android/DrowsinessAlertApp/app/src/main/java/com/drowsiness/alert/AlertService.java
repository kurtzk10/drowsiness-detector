package com.drowsiness.alert;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;
import android.util.Log;

import androidx.core.app.NotificationCompat;

import java.io.IOException;

public class AlertService extends Service
        implements NanoHTTPDServer.AlertCallback, AlarmController.DismissListener {

    private static final String TAG = "AlertService";

    private static final int NOTIFICATION_ID = 1001;
    private static final int ALARM_NOTIFICATION_ID = 1002;
    private static final String CHANNEL_ID = "alert_service_channel";
    private static final String ALARM_CHANNEL_ID = "alarm_channel";

    public static final String ACTION_DISMISS = "com.drowsiness.alert.DISMISS";

    private NanoHTTPDServer server;
    private DiscoveryBroadcaster broadcaster;
    private MainActivity boundActivity;
    private DiscoveryBroadcaster.PcDiscoveredListener pcListener;

    private AlarmController alarm;
    private PowerManager.WakeLock wakeLock;
    private WifiManager.WifiLock wifiLock;

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
        createNotificationChannels();
        alarm = new AlarmController(this);
        alarm.setDismissListener(this);
        acquireLocks();
        startForegroundWithTypes();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_DISMISS.equals(intent.getAction())) {
            alarm.dismiss();
            return START_STICKY;
        }
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
        if (alarm != null) {
            alarm.stop();
        }
        if (server != null) {
            server.stop();
            server = null;
        }
        if (broadcaster != null) {
            broadcaster.stop();
            broadcaster = null;
        }
        releaseLocks();
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

    /** Dismiss the alarm from the UI (volume key while the activity is focused). */
    public void dismissAlarm() {
        if (alarm != null) {
            alarm.dismiss();
        }
    }

    public boolean isAlarmPlaying() {
        return alarm != null && alarm.isPlaying();
    }

    // ── Wake / Wi-Fi locks ───────────────────────────────────────

    /**
     * Keep the CPU and the Wi-Fi radio alive for as long as the service runs.
     *
     * Without the Wi-Fi lock Android powers the radio down once the screen has
     * been off for a while, and the PC's alert POST never arrives — the app
     * looks alive in the notification tray while being unreachable. The
     * partial wake lock keeps the HTTP server and the discovery broadcaster
     * scheduled through Doze; it does not turn the screen on.
     */
    private void acquireLocks() {
        try {
            PowerManager pm = (PowerManager) getSystemService(Context.POWER_SERVICE);
            if (pm != null) {
                wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,
                        "DrowsinessAlert::ServiceWakeLock");
                wakeLock.setReferenceCounted(false);
                wakeLock.acquire();
            }
        } catch (Exception e) {
            Log.w(TAG, "Could not acquire wake lock", e);
        }
        try {
            WifiManager wm = (WifiManager) getApplicationContext()
                    .getSystemService(Context.WIFI_SERVICE);
            if (wm != null) {
                // HIGH_PERF is deprecated from Q onward; LOW_LATENCY is its
                // replacement and keeps the radio out of power-save the same way.
                int mode = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q
                        ? WifiManager.WIFI_MODE_FULL_LOW_LATENCY
                        : WifiManager.WIFI_MODE_FULL_HIGH_PERF;
                wifiLock = wm.createWifiLock(mode, "DrowsinessAlert::WifiLock");
                wifiLock.setReferenceCounted(false);
                wifiLock.acquire();
            }
        } catch (Exception e) {
            Log.w(TAG, "Could not acquire wifi lock", e);
        }
    }

    private void releaseLocks() {
        try {
            if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
        } catch (Exception ignored) {
        }
        wakeLock = null;
        try {
            if (wifiLock != null && wifiLock.isHeld()) wifiLock.release();
        } catch (Exception ignored) {
        }
        wifiLock = null;
    }

    // ── Alert callbacks ──────────────────────────────────────────

    @Override
    public void onAlert(String type, long timestamp) {
        // Sound and vibration are raised here, not in the activity, so an
        // alert still fires with the app backgrounded or the screen off.
        alarm.start(type);
        showAlarmNotification(type);

        MainActivity activity = boundActivity;
        if (activity != null) {
            activity.runOnUiThread(() -> activity.showAlert(type, timestamp));
        }
    }

    @Override
    public void onClear(long timestamp) {
        alarm.stop();
        cancelAlarmNotification();

        MainActivity activity = boundActivity;
        if (activity != null) {
            activity.runOnUiThread(() -> activity.clearAlert(timestamp));
        }
    }

    @Override
    public void onAlarmDismissed() {
        cancelAlarmNotification();
        MainActivity activity = boundActivity;
        if (activity != null) {
            activity.runOnUiThread(activity::onAlarmDismissedExternally);
        }
    }

    // ── Notifications ────────────────────────────────────────────

    private void createNotificationChannels() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return;
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager == null) return;

        manager.createNotificationChannel(new NotificationChannel(
                CHANNEL_ID,
                getString(R.string.service_channel),
                NotificationManager.IMPORTANCE_LOW));

        // HIGH importance with no sound of its own: AlarmController owns the
        // audio, and a channel sound would play a second tone over it.
        NotificationChannel alarmChannel = new NotificationChannel(
                ALARM_CHANNEL_ID,
                getString(R.string.alarm_channel),
                NotificationManager.IMPORTANCE_HIGH);
        alarmChannel.setSound(null, null);
        alarmChannel.enableVibration(false);
        alarmChannel.setBypassDnd(true);
        manager.createNotificationChannel(alarmChannel);
    }

    private void startForegroundWithTypes() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(NOTIFICATION_ID, buildNotification(),
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
                            | ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK);
        } else {
            startForeground(NOTIFICATION_ID, buildNotification());
        }
    }

    private Notification buildNotification() {
        Intent open = new Intent(this, MainActivity.class);
        PendingIntent contentIntent = PendingIntent.getActivity(this, 0, open,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);

        return new NotificationCompat.Builder(this, CHANNEL_ID)
                .setContentTitle(getString(R.string.app_name))
                .setContentText(getString(R.string.service_running))
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .setContentIntent(contentIntent)
                .setOngoing(true)
                .build();
    }

    /**
     * Full-screen alarm notification.
     *
     * The full-screen intent is what wakes the screen and puts MainActivity in
     * front of the lock screen, the way a clock app's alarm does. It also
     * hands the activity window focus, so its own volume-key handler works as
     * a second route to dismiss alongside the MediaSession.
     */
    private void showAlarmNotification(String type) {
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager == null) return;

        Intent full = new Intent(this, MainActivity.class);
        full.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent fullScreen = PendingIntent.getActivity(this, 1, full,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);

        Intent dismiss = new Intent(this, AlertService.class).setAction(ACTION_DISMISS);
        PendingIntent dismissIntent = PendingIntent.getService(this, 2, dismiss,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);

        Notification notification = new NotificationCompat.Builder(this, ALARM_CHANNEL_ID)
                .setContentTitle(getString(R.string.app_name))
                .setContentText(type.toUpperCase())
                .setSmallIcon(android.R.drawable.ic_dialog_alert)
                .setPriority(NotificationCompat.PRIORITY_MAX)
                .setCategory(NotificationCompat.CATEGORY_ALARM)
                .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
                .setFullScreenIntent(fullScreen, true)
                .setAutoCancel(false)
                .setOngoing(true)
                .addAction(android.R.drawable.ic_menu_close_clear_cancel,
                        getString(R.string.dismiss), dismissIntent)
                .build();

        manager.notify(ALARM_NOTIFICATION_ID, notification);
    }

    private void cancelAlarmNotification() {
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager != null) {
            manager.cancel(ALARM_NOTIFICATION_ID);
        }
    }
}
