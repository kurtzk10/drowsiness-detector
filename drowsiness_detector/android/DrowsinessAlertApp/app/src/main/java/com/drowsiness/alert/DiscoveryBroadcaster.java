package com.drowsiness.alert;

import android.util.Log;

import org.json.JSONObject;

import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;

public class DiscoveryBroadcaster {

    private static final String TAG = "DiscoveryBroadcaster";
    private static final int DISCOVERY_PORT = 9876;
    private static final long INTERVAL_MS = 2000;

    private final int alertPort;
    private Thread thread;
    private volatile boolean running = false;

    public DiscoveryBroadcaster(int alertPort) {
        this.alertPort = alertPort;
    }

    public void start() {
        if (running) return;
        running = true;
        thread = new Thread(this::run);
        thread.setDaemon(true);
        thread.start();
        Log.i(TAG, "Broadcaster started");
    }

    public void stop() {
        running = false;
        if (thread != null) {
            thread.interrupt();
            thread = null;
        }
        Log.i(TAG, "Broadcaster stopped");
    }

    private void run() {
        try {
            JSONObject payload = new JSONObject();
            payload.put("service", "drowsiness-alert");
            payload.put("port", alertPort);
            byte[] data = payload.toString().getBytes("UTF-8");

            DatagramSocket socket = new DatagramSocket();
            socket.setBroadcast(true);
            InetAddress broadcastAddr = InetAddress.getByName("255.255.255.255");

            while (running) {
                try {
                    DatagramPacket packet = new DatagramPacket(
                            data, data.length, broadcastAddr, DISCOVERY_PORT
                    );
                    socket.send(packet);
                } catch (Exception e) {
                    Log.e(TAG, "Send failed", e);
                }

                try {
                    Thread.sleep(INTERVAL_MS);
                } catch (InterruptedException e) {
                    break;
                }
            }

            socket.close();
        } catch (Exception e) {
            Log.e(TAG, "Broadcaster error", e);
        }
    }
}
