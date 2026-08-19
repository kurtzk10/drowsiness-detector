package com.drowsiness.alert;

import android.util.Log;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.util.Map;

import fi.iki.elonen.NanoHTTPD;

public class NanoHTTPDServer extends NanoHTTPD {

    private static final String TAG = "NanoHTTPDServer";
    private final AlertCallback callback;

    public interface AlertCallback {
        void onAlert(String type, long timestamp);
        void onClear(long timestamp);
    }

    public NanoHTTPDServer(int port, AlertCallback callback) {
        super(port);
        this.callback = callback;
    }

    @Override
    public Response serve(IHTTPSession session) {
        String uri = session.getUri();
        Method method = session.getMethod();

        if (Method.POST.equals(method)) {
            String body = readBody(session);

            if ("/alert".equals(uri)) {
                return handleAlert(body);
            } else if ("/clear".equals(uri)) {
                return handleClear(body);
            }
        }

        return newFixedLengthResponse(Response.Status.NOT_FOUND, "text/plain", "Not found");
    }

    private String readBody(IHTTPSession session) {
        try {
            Integer contentLength = Integer.parseInt(
                    session.getHeaders().getOrDefault("content-length", "0"));
            if (contentLength == 0) return "";

            Map<String, String> bodyMap = session.getParms();
            if (!bodyMap.isEmpty()) {
                // Form-encoded fallback
                return bodyMap.toString();
            }

            BufferedReader reader = new BufferedReader(
                    new InputStreamReader(session.getInputStream()));
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) {
                sb.append(line);
            }
            return sb.toString();
        } catch (Exception e) {
            Log.e(TAG, "Error reading body", e);
            return "";
        }
    }

    private Response handleAlert(String body) {
        try {
            JSONObject json = new JSONObject(body);
            String type = json.optString("type", "drowsy");
            long timestamp = System.currentTimeMillis();
            if (callback != null) {
                callback.onAlert(type, timestamp);
            }
            Log.i(TAG, "Alert: " + type);
            return newFixedLengthResponse(Response.Status.OK, "text/plain", "OK");
        } catch (JSONException e) {
            Log.e(TAG, "Bad JSON in /alert", e);
            return newFixedLengthResponse(Response.Status.BAD_REQUEST, "text/plain", "Bad JSON");
        }
    }

    private Response handleClear(String body) {
        long timestamp = System.currentTimeMillis();

        if (callback != null) {
            callback.onClear(timestamp);
        }
        Log.i(TAG, "Clear");
        return newFixedLengthResponse(Response.Status.OK, "text/plain", "OK");
    }
}
