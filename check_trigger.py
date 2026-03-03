import imaplib
import os

EMAIL = os.environ.get("EMAIL_SENDER", "")
PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
TRIGGER_SUBJECT = "run keno radar"  # Send an email with this subject to trigger


def check_for_trigger():
    triggered = False
    try:
        print("[Trigger] Connecting to Gmail IMAP...")
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(EMAIL, PASSWORD)
        mail.select("inbox")

        # Search for unread emails matching the trigger subject
        _, msgs = mail.search(None, f'(UNSEEN SUBJECT "{TRIGGER_SUBJECT}")')
        msg_ids = msgs[0].split()

        if msg_ids:
            print(f"[Trigger] Found {len(msg_ids)} trigger email(s). Will run analysis.")
            # Mark them all as read so they don't trigger again
            for mid in msg_ids:
                mail.store(mid, "+FLAGS", "\\Seen")
            triggered = True
        else:
            print("[Trigger] No trigger email found. Standing by.")

        mail.close()
        mail.logout()

    except Exception as e:
        print(f"[Trigger] Error checking email: {e}")

    # Write result to file so the workflow can read it
    with open(".trigger", "w") as f:
        f.write("true" if triggered else "false")


if __name__ == "__main__":
    check_for_trigger()
