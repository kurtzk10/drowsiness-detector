package com.drowsiness.alert;

import android.util.Log;

import org.json.JSONException;
import org.json.JSONObject;

import java.util.HashMap;
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

    /**
     * Read the request body.
     *
     * NanoHTTPD hands the body over through parseBody(), which stores a raw
     * (non-form) payload under "postData". Reading getInputStream() directly
     * does not work — NanoHTTPD has already buffered past the header boundary,
     * so the reader saw nothing and blocked on readLine() until the socket
     * timed out. Every /alert then reached handleAlert() with an empty string,
     * failed JSON parsing, and returned 400: the alarm never fired, and each
     * request cost ~5s first.
     */
    private String readBody(IHTTPSession session) {
        try {
            Map<String, String> files = new HashMap<>();
            session.parseBody(files);

            String body = files.get("postData");
            if (body != null && !body.isEmpty()) {
                return body;
            }

            // A form-encoded sender lands in parms instead of postData.
            Map<String, String> parms = session.getParms();
            String queued = parms.get("postData");
            if (queued != null && !queued.isEmpty()) {
                return queued;
            }
            return "";
        } catch (Exception e) {
            Log.e(TAG, "Error reading body", e);
            return "";
        }
    }

    private Response handleAlert(String body) {
        // An unreadable body must not silence the alarm. The PC only posts
        // here when it has already decided the driver is drowsy, so a payload
        // we cannot parse still raises the alert under the default type —
        // failing loud beats failing silent in this direction.
        String type = "drowsy";
        try {
            type = new JSONObject(body).optString("type", "drowsy");
        } catch (JSONException e) {
            Log.w(TAG, "Unparseable /alert body, alerting as drowsy: " + body);
        }

        long timestamp = System.currentTimeMillis();
        if (callback != null) {
            callback.onAlert(type, timestamp);
        }
        Log.i(TAG, "Alert: " + type);
        return newFixedLengthResponse(Response.Status.OK, "text/plain", "OK");
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
