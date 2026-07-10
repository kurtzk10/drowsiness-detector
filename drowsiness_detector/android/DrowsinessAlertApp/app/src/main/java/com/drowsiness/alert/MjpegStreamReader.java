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

    private final String streamUrl;
    private final ImageView imageView;
    private final Handler handler;
    private final Runnable onConnected;
    private Thread thread;
    private volatile boolean running = false;

    public MjpegStreamReader(String streamUrl, ImageView imageView,
                             Handler handler, Runnable onConnected) {
        this.streamUrl = streamUrl;
        this.imageView = imageView;
        this.handler = handler;
        this.onConnected = onConnected;
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
        if (thread != null) {
            thread.interrupt();
            thread = null;
        }
    }

    private void run() {
        HttpURLConnection connection = null;
        try {
            URL url = new URL(streamUrl);
            connection = (HttpURLConnection) url.openConnection();
            connection.setConnectTimeout(5000);
            connection.setReadTimeout(0);
            connection.connect();

            if (onConnected != null) {
                handler.post(onConnected);
            }

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
                                    handler.post(() -> imageView.setImageBitmap(bitmap));
                                }
                            }
                        }
                    }
                }
            }
        } catch (Exception e) {
            Log.e(TAG, "Stream error", e);
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }
}
