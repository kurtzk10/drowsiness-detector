package com.drowsiness.alert;

import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.media.Ringtone;
import android.media.RingtoneManager;
import android.net.Uri;
import android.os.Bundle;
import android.provider.Settings;
import android.widget.Button;
import android.widget.SeekBar;
import android.widget.TextView;

import androidx.appcompat.app.AppCompatActivity;
import androidx.appcompat.widget.SwitchCompat;

public class SettingsActivity extends AppCompatActivity {

    private static final String PREFS_NAME = "alert_settings";

    private static final int RQ_DROWSY = 1;
    private static final int RQ_YAWNING = 2;
    private static final int RQ_NOTLOOKING = 3;

    private static final String KEY_RINGTONE = "ringtone_uri";
    private static final String KEY_VOLUME = "volume";
    private static final String KEY_VIBRATION = "vibration";

    static class ViolationSettings {
        final String prefix;
        final int requestCode;
        Uri ringtoneUri;
        int volumePercent = 100;
        boolean vibrationEnabled = true;

        final TextView ringtoneDisplay;
        final SeekBar volumeSeekBar;
        final TextView volumeLabel;
        final SwitchCompat vibrationSwitch;

        ViolationSettings(String prefix, int requestCode, SettingsActivity activity) {
            this.prefix = prefix;
            this.requestCode = requestCode;
            ringtoneDisplay = activity.findViewById(
                    activity.getResources().getIdentifier("ringtoneDisplay_" + prefix, "id", activity.getPackageName()));
            volumeSeekBar = activity.findViewById(
                    activity.getResources().getIdentifier("volumeSeekBar_" + prefix, "id", activity.getPackageName()));
            volumeLabel = activity.findViewById(
                    activity.getResources().getIdentifier("volumeLabel_" + prefix, "id", activity.getPackageName()));
            vibrationSwitch = activity.findViewById(
                    activity.getResources().getIdentifier("vibrationSwitch_" + prefix, "id", activity.getPackageName()));
        }
    }

    private ViolationSettings drowsy;
    private ViolationSettings yawning;
    private ViolationSettings notLooking;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_settings);

        drowsy = new ViolationSettings("drowsy", RQ_DROWSY, this);
        yawning = new ViolationSettings("yawning", RQ_YAWNING, this);
        notLooking = new ViolationSettings("notlooking", RQ_NOTLOOKING, this);

        loadSettings(drowsy);
        loadSettings(yawning);
        loadSettings(notLooking);

        bindUI(drowsy);
        bindUI(yawning);
        bindUI(notLooking);

        Button ringtoneDrowsy = findViewById(R.id.ringtoneButton_drowsy);
        ringtoneDrowsy.setOnClickListener(v -> openRingtonePicker(RQ_DROWSY, drowsy.ringtoneUri));

        Button ringtoneYawning = findViewById(R.id.ringtoneButton_yawning);
        ringtoneYawning.setOnClickListener(v -> openRingtonePicker(RQ_YAWNING, yawning.ringtoneUri));

        Button ringtoneNotLooking = findViewById(R.id.ringtoneButton_notlooking);
        ringtoneNotLooking.setOnClickListener(v -> openRingtonePicker(RQ_NOTLOOKING, notLooking.ringtoneUri));

        Button doneButton = findViewById(R.id.doneButton);
        doneButton.setOnClickListener(v -> {
            saveSettings(drowsy);
            saveSettings(yawning);
            saveSettings(notLooking);
            finish();
        });
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (resultCode != RESULT_OK || data == null) return;

        Uri uri = data.getParcelableExtra(RingtoneManager.EXTRA_RINGTONE_PICKED_URI);
        if (uri == null) return;

        ViolationSettings vs = null;
        if (requestCode == RQ_DROWSY) vs = drowsy;
        else if (requestCode == RQ_YAWNING) vs = yawning;
        else if (requestCode == RQ_NOTLOOKING) vs = notLooking;

        if (vs != null) {
            vs.ringtoneUri = uri;
            updateRingtoneDisplay(vs);
        }
    }

    private void openRingtonePicker(int requestCode, Uri currentUri) {
        Intent intent = new Intent(RingtoneManager.ACTION_RINGTONE_PICKER);
        intent.putExtra(RingtoneManager.EXTRA_RINGTONE_TYPE, RingtoneManager.TYPE_ALARM);
        intent.putExtra(RingtoneManager.EXTRA_RINGTONE_TITLE, "Select Alarm Sound");
        intent.putExtra(RingtoneManager.EXTRA_RINGTONE_EXISTING_URI, currentUri);
        startActivityForResult(intent, requestCode);
    }

    private void loadSettings(ViolationSettings vs) {
        SharedPreferences prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);
        String uriStr = prefs.getString(vs.prefix + "_" + KEY_RINGTONE,
                Settings.System.DEFAULT_ALARM_ALERT_URI.toString());
        vs.ringtoneUri = Uri.parse(uriStr);
        vs.volumePercent = prefs.getInt(vs.prefix + "_" + KEY_VOLUME, 100);
        vs.vibrationEnabled = prefs.getBoolean(vs.prefix + "_" + KEY_VIBRATION, true);
    }

    private void saveSettings(ViolationSettings vs) {
        SharedPreferences prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);
        prefs.edit()
                .putString(vs.prefix + "_" + KEY_RINGTONE, vs.ringtoneUri.toString())
                .putInt(vs.prefix + "_" + KEY_VOLUME, vs.volumePercent)
                .putBoolean(vs.prefix + "_" + KEY_VIBRATION, vs.vibrationSwitch.isChecked())
                .apply();
    }

    private void bindUI(ViolationSettings vs) {
        updateRingtoneDisplay(vs);
        vs.volumeSeekBar.setProgress(vs.volumePercent - 50);
        vs.volumeLabel.setText(vs.volumePercent + "%");
        vs.vibrationSwitch.setChecked(vs.vibrationEnabled);

        vs.volumeSeekBar.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override
            public void onProgressChanged(SeekBar seekBar, int progress, boolean fromUser) {
                vs.volumePercent = progress + 50;
                vs.volumeLabel.setText(vs.volumePercent + "%");
            }
            @Override
            public void onStartTrackingTouch(SeekBar seekBar) {}
            @Override
            public void onStopTrackingTouch(SeekBar seekBar) {}
        });
    }

    private void updateRingtoneDisplay(ViolationSettings vs) {
        String name = "Default";
        try {
            Ringtone ringtone = RingtoneManager.getRingtone(this, vs.ringtoneUri);
            if (ringtone != null) {
                name = ringtone.getTitle(this);
            }
        } catch (Exception ignored) {}
        vs.ringtoneDisplay.setText(name);
    }

    // ── Static helpers for other activities ─────────────────────

    private static String prefType(String type) {
        if ("not_looking".equals(type)) return "notlooking";
        if ("perclos".equals(type)) return "drowsy";
        return type;
    }

    private static String key(String type, String field) {
        return prefType(type) + "_" + field;
    }

    private static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
    }

    public static String getRingtoneUri(Context context, String type) {
        return prefs(context).getString(key(type, KEY_RINGTONE),
                Settings.System.DEFAULT_ALARM_ALERT_URI.toString());
    }

    public static int getVolumePercent(Context context, String type) {
        return prefs(context).getInt(key(type, KEY_VOLUME), 100);
    }

    public static boolean isVibrationEnabled(Context context, String type) {
        return prefs(context).getBoolean(key(type, KEY_VIBRATION), true);
    }
}
