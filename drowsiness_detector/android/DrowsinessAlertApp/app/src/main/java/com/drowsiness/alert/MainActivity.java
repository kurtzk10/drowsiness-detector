package com.drowsiness.alert;

import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.ServiceConnection;
import android.content.pm.PackageManager;
import android.Manifest;
import android.os.Bundle;
import android.provider.Settings;
import android.os.IBinder;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
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


    // Current alert state
    private String currentAlertType = null;
    private long currentAlertStart = 0;
    private boolean alarmDismissed = false;

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

        Button recalibrateButton = findViewById(R.id.recalibrateButton);
        recalibrateButton.setOnClickListener(v -> {
            if (alertService != null) {
                alertService.dismissAlarm();
            }
            Intent calIntent = new Intent(MainActivity.this, CalibrationActivity.class);
            calIntent.setFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(calIntent);
            finish();
        });

        Button settingsButton = findViewById(R.id.settingsButton);
        settingsButton.setOnClickListener(v -> {
            Intent settingsIntent = new Intent(MainActivity.this, SettingsActivity.class);
            startActivity(settingsIntent);
        });
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
        // Nothing to tear down: the alarm belongs to AlertService now, and
        // must keep sounding after this activity goes away.
        super.onDestroy();
    }

    // ── Called from AlertService ─────────────────────────────────

    public void showAlert(String type, long timestamp) {
        boolean isNewType = !type.equals(currentAlertType);

        if (!isNewType && alarmDismissed) return;

        if (isNewType) {
            alarmDismissed = false;

            if (currentAlertType != null && !events.isEmpty()) {
                Event last = events.get(events.size() - 1);
                if (last.getType().equals(currentAlertType) && last.getEndTimestamp() == 0) {
                    last.setEndTimestamp(timestamp);
                    eventAdapter.notifyItemChanged(events.size() - 1);
                }
            }

            currentAlertType = type;
            currentAlertStart = timestamp;

            Event event = new Event(type, timestamp);
            events.add(event);
            if (events.size() > 100) {
                events.remove(0);
            }
            eventAdapter.notifyItemInserted(events.size() - 1);
            eventLog.smoothScrollToPosition(events.size() - 1);
            updateCounts();
        }

        String title;
        int bgColor;
        switch (type) {
            case Event.TYPE_DROWSY:
            case "perclos":
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

        // Sound and vibration already started in AlertService, which
        // raises them whether or not this activity exists.
    }

    public void clearAlert(long timestamp) {
        if (currentAlertType == null) return;

        alarmDismissed = false;

        if (!events.isEmpty()) {
            Event last = events.get(events.size() - 1);
            if (last.getType().equals(currentAlertType) && last.getEndTimestamp() == 0) {
                last.setEndTimestamp(timestamp);
                eventAdapter.notifyItemChanged(events.size() - 1);
            }
        }

        currentAlertType = null;
        currentAlertStart = 0;

        alertContainer.setBackgroundColor(getColor(R.color.normal_bg));
        alertTitle.setText(getString(R.string.no_alarm));
        alertTimestamp.setText("");
        alertDuration.setText("");

        updateCounts();
    }

    // ── Hardware button ─────────────────────────────────────────

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_VOLUME_DOWN && currentAlertType != null) {
            // Only reached while this window has focus; AlarmController's
            // MediaSession covers the screen-off and background cases.
            if (alertService != null) {
                alertService.dismissAlarm();
            }
            onAlarmDismissedExternally();
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    // ── Helpers ──────────────────────────────────────────────────

    private void updateCounts() {
        int d = 0, y = 0, n = 0;
        for (Event e : events) {
            switch (e.getType()) {
                case Event.TYPE_DROWSY:
                case "perclos": d++; break;
                case Event.TYPE_YAWNING: y++; break;
                case Event.TYPE_NOT_LOOKING: n++; break;
            }
        }
        countDrowsy.setText("DROWSY: " + d);
        countYawning.setText("YAWN: " + y);
        countNotLooking.setText("LOOK: " + n);
    }

    /** Called by AlertService once the alarm has actually been silenced. */
    public void onAlarmDismissedExternally() {
        alarmDismissed = true;
        alertContainer.setBackgroundColor(getColor(R.color.normal_bg));
        alertTitle.setText("DISMISSED");
        alertTimestamp.setText("");
        alertDuration.setText("");
    }
}
