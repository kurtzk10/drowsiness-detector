package com.drowsiness.alert;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.os.Handler;
import android.util.Log;
import android.widget.ImageView;

import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

public class MjpegStreamReader {

    private static final String TAG = "MjpegStreamReader";

    // The detector sends ~10 frames a second, so a few seconds of silence
    // means the connection is dead even if no error has surfaced.
    private static final int READ_TIMEOUT_MS = 5000;
    private static final long RETRY_DELAY_MS = 2000;

    private final String streamUrl;
    private final ImageView imageView;
    private final Handler handler;
    private final Runnable onConnected;
    private final Runnable onDisconnected;
    private Thread thread;
    private volatile boolean running = false;
    private volatile HttpURLConnection current;

    public MjpegStreamReader(String streamUrl, ImageView imageView,
                             Handler handler, Runnable onConnected,
                             Runnable onDisconnected) {
        this.streamUrl = streamUrl;
        this.imageView = imageView;
        this.handler = handler;
        this.onConnected = onConnected;
        this.onDisconnected = onDisconnected;
    }

    public void start() {
        if (running) return;
        running = true;
        thread = new Thread(this::run);
        thread.setDaemon(true);
        thread.start();
    }

    public void stop() {
        running = false;
        HttpURLConnection c = current;
        if (c != null) {
            c.disconnect();   // unblocks a read() waiting on the socket
        }
        if (thread != null) {
            thread.interrupt();
            thread = null;
        }
    }

    /**
     * Keep the feed alive until stop().
     *
     * This used to connect once and give up on the first error, so a feed
     * opened before the detector was serving — or one dropped when the
     * detector restarted — stayed blank until the screen was reopened.
     */
    private void run() {
        while (running) {
            boolean gotFrame = readStream();
            if (!running) break;
            if (gotFrame && onDisconnected != null) {
                handler.post(onDisconnected);
            }
            try {
                Thread.sleep(RETRY_DELAY_MS);
            } catch (InterruptedException e) {
                break;
            }
        }
    }

    /** Read one connection until it ends. Returns whether any frame arrived. */
    private boolean readStream() {
        HttpURLConnection connection = null;
        boolean gotFrame = false;
        try {
            URL url = new URL(streamUrl);
            connection = (HttpURLConnection) url.openConnection();
            current = connection;
            connection.setConnectTimeout(5000);
            connection.setReadTimeout(READ_TIMEOUT_MS);
            connection.connect();

            InputStream is = new BufferedInputStream(connection.getInputStream(), 131072);
            byte[] buf = new byte[4096];
            ByteArrayOutputStream lineBuf = new ByteArrayOutputStream();
            ByteArrayOutputStream dataBuf = new ByteArrayOutputStream();
            String contentLength = null;
            int mode = 0; // 0 = headers, 1 = jpeg data
            int dataRemaining = 0;

            while (running) {
                int n = is.read(buf);
                if (n == -1) break;

                for (int i = 0; i < n; i++) {
                    int b = buf[i] & 0xFF;

                    if (mode == 0) {
                        if (b == '\n') {
                            String line = lineBuf.toString().trim();
                            lineBuf.reset();

                            String lower = line.toLowerCase();
                            if (lower.startsWith("content-length:")) {
                                contentLength = line.substring("content-length:".length()).trim();
                            } else if (line.isEmpty()) {
                                if (contentLength != null) {
                                    try {
                                        dataRemaining = Integer.parseInt(contentLength);
                                    } catch (Exception ignored) {
                                        dataRemaining = 0;
                                    }
                                    contentLength = null;
                                    mode = 1;
                                    dataBuf.reset();
                                }
                            }
                        } else if (b != '\r') {
                            lineBuf.write(b);
                        }
                    } else {
                        dataBuf.write(b);
                        dataRemaining--;

                        if (dataRemaining <= 0) {
                            byte[] jpegBytes = dataBuf.toByteArray();
                            mode = 0;
                            dataBuf.reset();

                            if (jpegBytes.length > 0) {
                                final Bitmap bitmap = BitmapFactory.decodeByteArray(
                                        jpegBytes, 0, jpegBytes.length);
                                if (bitmap != null) {
                                    // Report "connected" on the first real
                                    // frame, not on the TCP connect: a socket
                                    // can open and still never deliver video.
                                    if (!gotFrame && onConnected != null) {
                                        handler.post(onConnected);
                                    }
                                    gotFrame = true;
                                    handler.post(() -> imageView.setImageBitmap(bitmap));
                                }
                            }
                        }
                    }
                }
            }
        } catch (Exception e) {
            if (running) {
                Log.w(TAG, "Stream error, retrying: " + e.getMessage());
            }
        } finally {
            current = null;
            if (connection != null) {
                connection.disconnect();
            }
        }
        return gotFrame;
    }
}
