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

    public interface PcDiscoveredListener {
        void onPcDiscovered(String ip);
    }

    private final int alertPort;
    private PcDiscoveredListener listener;
    private Thread thread;
    private volatile boolean running = false;
    private String discoveredPcIp = null;

    public DiscoveryBroadcaster(int alertPort) {
        this.alertPort = alertPort;
    }

    public void setPcDiscoveredListener(PcDiscoveredListener listener) {
        this.listener = listener;
    }

    public String getPcIp() {
        return discoveredPcIp;
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
            socket.setSoTimeout(1000);
            InetAddress broadcastAddr = InetAddress.getByName("255.255.255.255");
            byte[] receiveBuf = new byte[1024];
            DatagramPacket receivePacket = new DatagramPacket(receiveBuf, receiveBuf.length);

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
                    socket.receive(receivePacket);
                    String reply = new String(receivePacket.getData(), 0, receivePacket.getLength(), "UTF-8");
                    JSONObject json = new JSONObject(reply);
                    if ("drowsiness-alert-reply".equals(json.optString("service"))) {
                        String pcIp = json.optString("pc_ip", null);
                        if (pcIp != null && !pcIp.equals(discoveredPcIp)) {
                            discoveredPcIp = pcIp;
                            Log.i(TAG, "PC discovered at " + pcIp);
                            if (listener != null) {
                                listener.onPcDiscovered(pcIp);
                            }
                        }
                    }
                } catch (Exception e) {
                    // Timeout or bad packet — expected
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
