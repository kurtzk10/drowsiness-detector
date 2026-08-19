import time


def trigger_alert(alert_type, http_client=None):
    """
    Fire alert by sending HTTP POST to the phone.
    If http_client is None, only prints to console (e.g. during testing).
    """
    if http_client is not None:
        http_client.send_alert(alert_type, time.time())
    else:
        print(f"[ALERT] {alert_type}")


def clear_alert(http_client=None):
    """
    Send clear signal to phone — driver is alert again.
    """
    if http_client is not None:
        http_client.send_clear()
    else:
        print("[ALERT] Clear")
