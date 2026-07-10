package com.drowsiness.alert;

import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.ServiceConnection;
import android.content.pm.PackageManager;
import android.Manifest;
import android.media.AudioAttributes;
import android.media.AudioManager;
import android.media.MediaPlayer;
import android.media.RingtoneManager;
import android.net.Uri;
import android.os.Bundle;
import android.os.IBinder;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.WindowManager;
import android.widget.TextView;

import androidx.appcompat.app.AppCompatActivity;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import java.util.ArrayList;
import java.util.List;

public class MainActivity extends AppCompatActivity {

    private AlertService alertService;
    private boolean bound = false;

    private View alertContainer;
    private TextView alertTitle, alertTimestamp, alertDuration;
    private TextView countDrowsy, countYawning, countNotLooking;
    private RecyclerView eventLog;
    private EventLogAdapter eventAdapter;
    private final List<Event> events = new ArrayList<>();

    private MediaPlayer mediaPlayer;
    private Vibrator vibrator;

    // Current alert state
    private String currentAlertType = null;
    private long currentAlertStart = 0;

    private final ServiceConnection connection = new ServiceConnection() {
        @Override
        public void onServiceConnected(ComponentName name, IBinder service) {
            AlertService.LocalBinder localBinder = (AlertService.LocalBinder) service;
            alertService = localBinder.getService();
            alertService.setBoundActivity(MainActivity.this);
            bound = true;
        }

        @Override
        public void onServiceDisconnected(ComponentName name) {
            bound = false;
            alertService = null;
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        // Keep screen on, show over lock screen
        getWindow().addFlags(
                WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON
                        | WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                        | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
                        | WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD
        );

        alertContainer = findViewById(R.id.alertContainer);
        alertTitle = findViewById(R.id.alertTitle);
        alertTimestamp = findViewById(R.id.alertTimestamp);
        alertDuration = findViewById(R.id.alertDuration);
        countDrowsy = findViewById(R.id.countDrowsy);
        countYawning = findViewById(R.id.countYawning);
        countNotLooking = findViewById(R.id.countNotLooking);
        eventLog = findViewById(R.id.eventLog);

        eventAdapter = new EventLogAdapter(events);
        eventLog.setLayoutManager(new LinearLayoutManager(this));
        eventLog.setAdapter(eventAdapter);

        vibrator = (Vibrator) getSystemService(Context.VIBRATOR_SERVICE);

        // Request notification permission for Android 13+
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.TIRAMISU) {
            if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 101);
            }
        }

        // Start foreground service
        Intent intent = new Intent(this, AlertService.class);
        startForegroundService(intent);
        bindService(intent, connection, Context.BIND_AUTO_CREATE);
    }

    @Override
    protected void onStart() {
        super.onStart();
        // Re-bind
        Intent intent = new Intent(this, AlertService.class);
        bindService(intent, connection, Context.BIND_AUTO_CREATE);
        if (alertService != null) {
            alertService.setBoundActivity(this);
        }
    }

    @Override
    protected void onStop() {
        super.onStop();
        if (alertService != null) {
            alertService.setBoundActivity(null);
        }
        if (bound) {
            unbindService(connection);
            bound = false;
        }
    }

    @Override
    protected void onDestroy() {
        stopAlertSound();
        if (mediaPlayer != null) {
            mediaPlayer.release();
            mediaPlayer = null;
        }
        super.onDestroy();
    }

    // ── Called from AlertService ─────────────────────────────────

    public void showAlert(String type, long timestamp) {
        // If same alert type is already showing, skip (avoid duplicates)
        if (type.equals(currentAlertType)) return;

        // End previous event if any
        if (currentAlertType != null && !events.isEmpty()) {
            Event last = events.get(events.size() - 1);
            if (last.getType().equals(currentAlertType) && last.getEndTimestamp() == 0) {
                last.setEndTimestamp(timestamp);
            }
        }

        currentAlertType = type;
        currentAlertStart = timestamp;

        // Add to event log
        Event event = new Event(type, timestamp);
        events.add(event);
        if (events.size() > 100) {
            events.remove(0);
        }
        eventAdapter.notifyItemInserted(events.size() - 1);
        eventLog.smoothScrollToPosition(events.size() - 1);
        updateCounts();

        // Update UI
        String title;
        int bgColor;
        switch (type) {
            case Event.TYPE_DROWSY:
                title = getString(R.string.alarm_drowsy);
                bgColor = getColor(R.color.drowsy_bg);
                break;
            case Event.TYPE_YAWNING:
                title = getString(R.string.alarm_yawning);
                bgColor = getColor(R.color.yawning_bg);
                break;
            case Event.TYPE_NOT_LOOKING:
                title = getString(R.string.alarm_not_looking);
                bgColor = getColor(R.color.not_looking_bg);
                break;
            default:
                title = "ALERT";
                bgColor = getColor(R.color.drowsy_bg);
        }

        alertTitle.setText(title);
        alertContainer.setBackgroundColor(bgColor);
        java.text.SimpleDateFormat sdf = new java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.US);
        alertTimestamp.setText(sdf.format(new java.util.Date(timestamp)));
        alertDuration.setText("");

        // Sound + vibrate
        playAlertSound();
        vibrate();
    }

    public void clearAlert(long timestamp) {
        if (currentAlertType == null) return;

        // End current event
        if (!events.isEmpty()) {
            Event last = events.get(events.size() - 1);
            if (last.getType().equals(currentAlertType) && last.getEndTimestamp() == 0) {
                last.setEndTimestamp(timestamp);
                eventAdapter.notifyItemChanged(events.size() - 1);
            }
        }

        currentAlertType = null;
        currentAlertStart = 0;

        // Restore normal UI
        alertContainer.setBackgroundColor(getColor(R.color.normal_bg));
        alertTitle.setText(getString(R.string.no_alarm));
        alertTimestamp.setText("");
        alertDuration.setText("");

        stopAlertSound();
        if (vibrator != null) {
            vibrator.cancel();
        }
        updateCounts();
    }

    // ── Hardware button ─────────────────────────────────────────

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_VOLUME_DOWN && currentAlertType != null) {
            stopAlarm();
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    // ── Helpers ──────────────────────────────────────────────────

    private void updateCounts() {
        int d = 0, y = 0, n = 0;
        for (Event e : events) {
            switch (e.getType()) {
                case Event.TYPE_DROWSY: d++; break;
                case Event.TYPE_YAWNING: y++; break;
                case Event.TYPE_NOT_LOOKING: n++; break;
            }
        }
        countDrowsy.setText("DROWSY: " + d);
        countYawning.setText("YAWN: " + y);
        countNotLooking.setText("LOOK: " + n);
    }

    private void playAlertSound() {
        try {
            stopAlertSound();
            Uri alertUri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM);
            if (alertUri == null) {
                alertUri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION);
            }
            mediaPlayer = new MediaPlayer();
            mediaPlayer.setAudioAttributes(new AudioAttributes.Builder()
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .setUsage(AudioAttributes.USAGE_ALARM)
                    .build());
            mediaPlayer.setDataSource(this, alertUri);
            mediaPlayer.setLooping(true);
            mediaPlayer.prepare();
            mediaPlayer.start();
        } catch (Exception e) {
            // Sound might not work on all devices — not critical
        }
    }

    private void stopAlertSound() {
        if (mediaPlayer != null) {
            try {
                mediaPlayer.stop();
            } catch (Exception ignored) {}
            mediaPlayer.reset();
        }
    }

    private void vibrate() {
        if (vibrator != null && vibrator.hasVibrator()) {
            long[] pattern = {0, 400, 200, 400};
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
                vibrator.vibrate(VibrationEffect.createWaveform(pattern, 0));
            } else {
                vibrator.vibrate(pattern, 0);
            }
        }
    }

    private void stopAlarm() {
        stopAlertSound();
        if (vibrator != null) {
            vibrator.cancel();
        }
        clearAlert(System.currentTimeMillis());
    }
}
