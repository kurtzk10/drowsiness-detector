package com.drowsiness.alert;

import android.os.SystemClock;
import android.util.Log;

import org.json.JSONObject;

import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.net.InterfaceAddress;
import java.net.NetworkInterface;
import java.net.SocketTimeoutException;
import java.util.ArrayList;
import java.util.Enumeration;
import java.util.List;

public class DiscoveryBroadcaster {

    private static final String TAG = "DiscoveryBroadcaster";
    private static final int DISCOVERY_PORT = 9876;
    private static final long INTERVAL_MS = 2000;
    private static final int RECEIVE_TIMEOUT_MS = 500;

    public interface PcDiscoveredListener {
        void onPcDiscovered(String ip);
    }

    private final int alertPort;
    private PcDiscoveredListener listener;
    private Thread thread;
    private volatile boolean running = false;
    private volatile DatagramSocket socket;
    private volatile String discoveredPcIp = null;

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
        // Closing the socket is what actually unblocks a thread parked in
        // receive() — interrupt() alone does not interrupt DatagramSocket I/O.
        DatagramSocket s = socket;
        if (s != null) {
            s.close();
        }
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

            DatagramSocket s = new DatagramSocket();
            s.setBroadcast(true);
            s.setSoTimeout(RECEIVE_TIMEOUT_MS);
            socket = s;

            byte[] receiveBuf = new byte[1024];

            while (running) {
                for (InetAddress target : broadcastTargets()) {
                    try {
                        s.send(new DatagramPacket(
                                data, data.length, target, DISCOVERY_PORT));
                    } catch (Exception e) {
                        // A dead or unroutable interface is normal — keep going
                        // so one bad target cannot starve the others.
                        Log.d(TAG, "Send to " + target.getHostAddress()
                                + " failed: " + e.getMessage());
                    }
                }

                // Stay in receive() for the whole cycle rather than sleeping
                // blind, so a reply is picked up as soon as it lands.
                long deadline = SystemClock.elapsedRealtime() + INTERVAL_MS;
                while (running && SystemClock.elapsedRealtime() < deadline) {
                    // A fresh packet each time: receive() shrinks the packet's
                    // length to the bytes read, so a reused one truncates every
                    // reply after the first.
                    DatagramPacket reply =
                            new DatagramPacket(receiveBuf, receiveBuf.length);
                    try {
                        s.receive(reply);
                        handleReply(reply);
                    } catch (SocketTimeoutException e) {
                        // No reply in this slice — wait out the rest of the cycle.
                    } catch (Exception e) {
                        if (!running) break;
                    }
                }
            }
        } catch (Exception e) {
            if (running) {
                Log.e(TAG, "Broadcaster error", e);
            }
        } finally {
            DatagramSocket s = socket;
            if (s != null) {
                s.close();
                socket = null;
            }
        }
    }

    /**
     * Broadcast addresses to announce on, one per live IPv4 interface.
     *
     * An unbound DatagramSocket is bound to Android's *default* network, which
     * is mobile data while the phone is acting as a hotspot — so a lone
     * 255.255.255.255 packet leaves over rmnet and never reaches the tethered
     * PC. Sending to each interface's own subnet-directed address instead
     * (e.g. 10.106.225.255) makes the kernel route the packet out that
     * interface, with the matching source IP for the PC to reply to.
     *
     * Point-to-point links such as cellular report no broadcast address and
     * drop out of the list on their own.
     */
    private List<InetAddress> broadcastTargets() {
        List<InetAddress> targets = new ArrayList<>();
        try {
            Enumeration<NetworkInterface> ifaces =
                    NetworkInterface.getNetworkInterfaces();
            while (ifaces != null && ifaces.hasMoreElements()) {
                NetworkInterface iface = ifaces.nextElement();
                if (iface.isLoopback() || !iface.isUp()) continue;
                for (InterfaceAddress addr : iface.getInterfaceAddresses()) {
                    InetAddress bcast = addr.getBroadcast();
                    if (bcast != null && !targets.contains(bcast)) {
                        targets.add(bcast);
                    }
                }
            }
        } catch (Exception e) {
            Log.w(TAG, "Interface enumeration failed", e);
        }

        // Only as a genuine last resort. Sent alongside the per-interface
        // addresses it is worse than useless: it leaves over whatever network
        // Android considers default (mobile data while tethering), and on a
        // multi-homed PC it can arrive from a bystander adapter and overwrite
        // the correct address the subnet-directed packet already established.
        if (targets.isEmpty()) {
            try {
                targets.add(InetAddress.getByName("255.255.255.255"));
            } catch (Exception ignored) {
            }
        }

        return targets;
    }

    private void handleReply(DatagramPacket packet) throws Exception {
        String body = new String(
                packet.getData(), 0, packet.getLength(), "UTF-8");
        JSONObject json = new JSONObject(body);
        if (!"drowsiness-alert-reply".equals(json.optString("service"))) return;

        String pcIp = json.optString("pc_ip", null);
        if (pcIp == null || pcIp.isEmpty() || pcIp.equals(discoveredPcIp)) return;

        discoveredPcIp = pcIp;
        Log.i(TAG, "PC discovered at " + pcIp);
        PcDiscoveredListener l = listener;
        if (l != null) {
            l.onPcDiscovered(pcIp);
        }
    }
}
