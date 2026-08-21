# NanoHTTPD resolves request handlers and its own internals reflectively, so
# R8 cannot see those call sites and would strip or rename them. Without this
# the release APK builds cleanly and then fails at runtime the first time the
# PC posts an alert — the exact path this app exists to serve.
-keep class org.nanohttpd.** { *; }
-dontwarn org.nanohttpd.**

# The alert server subclasses NanoHTTPD and overrides serve(); keep the whole
# app package so the service, activities, and the discovery broadcaster keep
# the names the manifest and the PC-side JSON protocol expect.
-keep class com.drowsiness.alert.** { *; }
