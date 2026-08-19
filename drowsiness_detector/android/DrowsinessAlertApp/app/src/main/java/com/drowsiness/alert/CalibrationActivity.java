package com.drowsiness.alert;

import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.ServiceConnection;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.view.View;
import android.widget.Button;
import android.widget.ImageView;
import android.widget.TextView;

import androidx.appcompat.app.AppCompatActivity;

import org.json.JSONObject;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;

public class CalibrationActivity extends AppCompatActivity {

    private static final int CALIBRATION_PORT = 8080;

    private ImageView videoFeed;
    private TextView statusText, calibrationOverlay;
    private Button calibrateButton;

    private AlertService alertService;
    private boolean bound = false;
    private String pcIp = null;
    private MjpegStreamReader streamReader;
    private final Handler handler = new Handler();

    private final ServiceConnection connection = new ServiceConnection() {
        @Override
        public void onServiceConnected(ComponentName name, IBinder service) {
            AlertService.LocalBinder binder = (AlertService.LocalBinder) service;
            alertService = binder.getService();
            alertService.setPcDiscoveredListener(CalibrationActivity.this::onPcDiscovered);
            bound = true;
            String existingIp = alertService.getPcIp();
            if (existingIp != null) {
                onPcDiscovered(existingIp);
            }
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
        setContentView(R.layout.activity_calibration);

        videoFeed = findViewById(R.id.videoFeed);
        statusText = findViewById(R.id.statusText);
        calibrationOverlay = findViewById(R.id.calibrationOverlay);
        calibrateButton = findViewById(R.id.calibrateButton);

        Intent intent = new Intent(this, AlertService.class);
        startForegroundService(intent);
        bindService(intent, connection, Context.BIND_AUTO_CREATE);

        calibrateButton.setOnClickListener(v -> startCalibration());

        Button settingsButton = findViewById(R.id.settingsButton);
        settingsButton.setOnClickListener(v -> {
            Intent settingsIntent = new Intent(CalibrationActivity.this, SettingsActivity.class);
            startActivity(settingsIntent);
        });
    }

    @Override
    protected void onDestroy() {
        if (bound) {
            if (alertService != null) {
                alertService.setPcDiscoveredListener(null);
            }
            unbindService(connection);
            bound = false;
        }
        stopStream();
        super.onDestroy();
    }

    private void onPcDiscovered(String ip) {
        pcIp = ip;
        runOnUiThread(() -> {
            statusText.setText("Connected - PC IP: " + ip);
            calibrateButton.setEnabled(true);
        });
        startStream();
    }

    private void startStream() {
        stopStream();
        if (pcIp == null) return;
        String url = "http://" + pcIp + ":" + CALIBRATION_PORT + "/video_feed";
        streamReader = new MjpegStreamReader(url, videoFeed, handler, () ->
                runOnUiThread(() -> statusText.setText("Live feed connected"))
        );
        streamReader.start();
    }

    private void stopStream() {
        if (streamReader != null) {
            streamReader.stop();
            streamReader = null;
        }
    }

    private void startCalibration() {
        if (pcIp == null) return;

        calibrateButton.setEnabled(false);
        calibrateButton.setText("CALIBRATING...");
        calibrationOverlay.setVisibility(View.VISIBLE);
        calibrationOverlay.setText("Calibrating...");
        statusText.setText("Calibration in progress...");

        new Thread(() -> {
            try {
                URL url = new URL("http://" + pcIp + ":" + CALIBRATION_PORT + "/calibrate");
                HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("POST");
                conn.setDoOutput(true);
                conn.setConnectTimeout(5000);
                conn.setReadTimeout(20000);
                conn.setRequestProperty("Content-Type", "application/json");
                conn.connect();

                try (OutputStream os = conn.getOutputStream()) {
                    os.write("{}".getBytes());
                }

                int responseCode = conn.getResponseCode();
                conn.disconnect();

                if (responseCode == 200) {
                    runOnUiThread(() -> {
                        calibrationOverlay.setText("Calibration complete!");
                        statusText.setText("Calibration successful");
                    });
                    Thread.sleep(800);
                    navigateToMain();
                } else {
                    runOnUiThread(() -> {
                        calibrationOverlay.setText("Calibration failed");
                        statusText.setText("Error: " + responseCode);
                        calibrateButton.setEnabled(true);
                        calibrateButton.setText("RETRY");
                    });
                }
            } catch (Exception e) {
                runOnUiThread(() -> {
                    calibrationOverlay.setText("Connection error");
                    statusText.setText("Error: " + e.getMessage());
                    calibrateButton.setEnabled(true);
                    calibrateButton.setText("RETRY");
                });
            }
        }).start();
    }

    private void navigateToMain() {
        stopStream();
        Intent intent = new Intent(this, MainActivity.class);
        intent.setFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_NEW_TASK);
        startActivity(intent);
        finish();
    }
}
