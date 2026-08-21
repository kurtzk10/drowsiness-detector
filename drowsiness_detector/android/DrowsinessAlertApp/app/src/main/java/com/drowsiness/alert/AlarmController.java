package com.drowsiness.alert;

import android.content.Context;
import android.media.AudioAttributes;
import android.media.MediaPlayer;
import android.media.RingtoneManager;
import android.media.VolumeProvider;
import android.media.session.MediaSession;
import android.media.session.PlaybackState;
import android.net.Uri;
import android.os.Build;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.text.TextUtils;
import android.util.Log;

/**
 * Owns alarm playback — sound, vibration, and the volume-key dismiss.
 *
 * This used to live in MainActivity, which meant the alarm only existed while
 * that activity did. AlertService forwarded alerts to a bound activity and
 * dropped them outright when there wasn't one, so backgrounding the app or
 * letting the screen go off silently disabled every alert — exactly the
 * situation a drowsy driver is in.
 */
class AlarmController {

    private static final String TAG = "AlarmController";
    private static final long[] VIBRATE_PATTERN = {0, 400, 200, 400};

    interface DismissListener {
        void onAlarmDismissed();
    }

    private final Context context;
    private final Vibrator vibrator;
    private DismissListener dismissListener;

    private MediaPlayer player;
    private MediaSession session;
    private volatile boolean playing = false;
    private volatile String activeType = null;

    AlarmController(Context context) {
        this.context = context.getApplicationContext();
        this.vibrator = (Vibrator) this.context.getSystemService(Context.VIBRATOR_SERVICE);
    }

    void setDismissListener(DismissListener listener) {
        this.dismissListener = listener;
    }

    boolean isPlaying() {
        return playing;
    }

    String getActiveType() {
        return activeType;
    }

    synchronized void start(String type) {
        stopInternal();
        activeType = type;
        playSound(type);
        vibrate(type);
        captureVolumeKeys();
        playing = true;
    }

    synchronized void stop() {
        stopInternal();
        activeType = null;
    }

    /** Dismiss triggered by the user — volume key, notification, or activity. */
    void dismiss() {
        stop();
        DismissListener listener = dismissListener;
        if (listener != null) {
            listener.onAlarmDismissed();
        }
    }

    private void stopInternal() {
        playing = false;
        releaseVolumeKeys();
        if (player != null) {
            try {
                player.stop();
            } catch (Exception ignored) {
                // stop() throws if the player was never started; nothing to do.
            }
            try {
                player.release();
            } catch (Exception ignored) {
            }
            player = null;
        }
        if (vibrator != null) {
            vibrator.cancel();
        }
    }

    // ── Sound ────────────────────────────────────────────────────

    private void playSound(String type) {
        try {
            Uri alertUri = null;
            String uriStr = SettingsActivity.getRingtoneUri(context, type);
            if (!TextUtils.isEmpty(uriStr)) {
                alertUri = Uri.parse(uriStr);
            }
            if (alertUri == null) {
                alertUri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM);
            }

            int vol = SettingsActivity.getVolumePercent(context, type);
            float volFloat = Math.max(0.5f, vol / 100f);

            player = new MediaPlayer();
            // USAGE_ALARM routes to the alarm stream, which keeps playing when
            // the phone is on silent and is exempt from Do Not Disturb.
            player.setAudioAttributes(new AudioAttributes.Builder()
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .setUsage(AudioAttributes.USAGE_ALARM)
                    .build());
            player.setDataSource(context, alertUri);
            player.setLooping(true);
            player.setVolume(volFloat, volFloat);
            player.prepare();
            player.start();
        } catch (Exception e) {
            Log.w(TAG, "Could not start alarm sound", e);
        }
    }

    private void vibrate(String type) {
        if (!SettingsActivity.isVibrationEnabled(context, type)) return;
        if (vibrator == null || !vibrator.hasVibrator()) return;
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                vibrator.vibrate(VibrationEffect.createWaveform(VIBRATE_PATTERN, 0));
            } else {
                vibrator.vibrate(VIBRATE_PATTERN, 0);
            }
        } catch (Exception e) {
            Log.w(TAG, "Could not vibrate", e);
        }
    }

    // ── Volume-key dismiss ───────────────────────────────────────

    /**
     * Route volume-key presses to this alarm.
     *
     * MainActivity.onKeyDown only sees them while that activity holds window
     * focus, so with the screen off or the app in the background there was no
     * way to silence the alarm. An active MediaSession reporting *remote*
     * playback receives the key events instead, whatever is on screen — the
     * same mechanism a cast session uses to take over the volume rocker.
     */
    private void captureVolumeKeys() {
        try {
            session = new MediaSession(context, "DrowsinessAlarm");
            session.setPlaybackState(new PlaybackState.Builder()
                    .setState(PlaybackState.STATE_PLAYING, 0, 1.0f)
                    .setActions(PlaybackState.ACTION_STOP)
                    .build());
            session.setPlaybackToRemote(new VolumeProvider(
                    VolumeProvider.VOLUME_CONTROL_RELATIVE, 100, 50) {
                @Override
                public void onAdjustVolume(int direction) {
                    // direction < 0 is volume-down; up and neutral are ignored
                    // so the driver cannot dismiss by reaching for volume-up.
                    if (direction < 0) {
                        dismiss();
                    }
                }
            });
            session.setCallback(new MediaSession.Callback() {
                @Override
                public void onStop() {
                    dismiss();
                }
            });
            session.setActive(true);
        } catch (Exception e) {
            Log.w(TAG, "Volume-key capture unavailable", e);
        }
    }

    private void releaseVolumeKeys() {
        if (session == null) return;
        try {
            session.setActive(false);
            session.release();
        } catch (Exception ignored) {
        }
        session = null;
    }
}
