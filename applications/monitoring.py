
import signal
import sys
import threading
import time
import datetime
import os
from tcspy.utils import DataTransferManager
from tcspy.utils.alertmanager import AlertMonitor


# ── Logging setup ─────────────────────────────────────────────────────────────

LOG_DIR = '/home/snu/code/RASA36/log/monitor_log/'

class _TeeOutput:
    """Writes every print() to both the terminal and a rotating daily log file."""
 
    def __init__(self, original_stream):
        self._stream = original_stream
        self._file = None
        self._current_date = None
        self._lock = threading.Lock()
        self._open_file()

    def _log_path(self):
        # Use the same -12 h offset as mainLogger so night logs stay on one date
        date_str = (datetime.datetime.utcnow() - datetime.timedelta(hours=12)).strftime('%Y%m%d')
        return os.path.join(LOG_DIR, f'{date_str}_monitoring.log')

    def _open_file(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        path = self._log_path()
        self._file = open(path, 'a', buffering=1, encoding='utf-8')
        self._current_date = datetime.date.today()

    def _rotate_if_needed(self):
        today = datetime.date.today()
        if today != self._current_date:
            try:
                self._file.close()
            except Exception:
                pass
            self._open_file()

    def write(self, msg):
        with self._lock:
            self._rotate_if_needed()
            self._stream.write(msg)
            self._file.write(msg)

    def flush(self):
        self._stream.flush()
        try:
            self._file.flush()
        except Exception:
            pass

    def fileno(self):
        return self._stream.fileno()


_tee = _TeeOutput(sys.stdout)
sys.stdout = _tee
sys.stderr = _tee

# ── Signal handling ────────────────────────────────────────────────────────────

_stop_event = threading.Event()

def _sighandler(signum, frame):
    print(f"[{datetime.datetime.now()}] Signal {signum} received — stopping.")
    _stop_event.set()

signal.signal(signal.SIGINT,  _sighandler)
signal.signal(signal.SIGTERM, _sighandler)


# ── Thread factories ───────────────────────────────────────────────────────────

def _make_alert_monitor_thread():
    def run():
        try:
            monitor = AlertMonitor()
            monitor.monitor_alert(
                send_slack=True,
                send_email=True,
                use_push=True,
                push_poll_interval=0.3,
                since_days=1,
                max_email_alerts=10,
                match_to_tiles=True,
                match_tolerance_minutes=3,
            )
        except Exception as e:
            print(f"[{datetime.datetime.now()}] AlertMonitor thread crashed: {e}")
    t = threading.Thread(target=run, name='AlertMonitor', daemon=True)
    return t


def _make_data_transfer_thread():
    def run():
        try:
            manager = DataTransferManager()
            manager.start_monitoring(
                ordinary_file_key='image/*',
                ToO_file_key='image/*_ToO',
                inactivity_period=120,
                poll_interval=10,
                tar=True,
                transfer=True,
                move_and_clean=True,
                protocol='hpnscp',
            )
        except Exception as e:
            print(f"[{datetime.datetime.now()}] DataTransfer thread crashed: {e}")
    t = threading.Thread(target=run, name='DataTransfer', daemon=True)
    return t


# ── Gmail token preflight ────────────────────────────────────────────────────────

def _preflight_gmail_token() -> bool:
    """Verify the Gmail push token can refresh BEFORE starting AlertMonitor.

    Running unattended, a dead token would otherwise drop GmailPushReceiver into an
    interactive browser consent flow that can never complete headless — silently
    hanging alert intake. Instead we probe it here (interactive=False), and on failure
    post a loud Slack alert and return False so AlertMonitor is skipped. DataTransfer
    still runs. Re-mint the token with `python configuration/keys/gmail.py`, then
    restart monitoring.py."""
    from tcspy.configuration import mainConfig
    from tcspy.utils.connector.gmailconnector import GmailPushReceiver, GmailTokenExpiredError
    config = mainConfig().config
    try:
        GmailPushReceiver(
            token_path=config['GMAIL_PUSH_TOKEN_PATH'],
            credentials_path=config['GMAIL_CREDENTIALS_PATH'],
            interactive=False,
        )
        return True
    except GmailTokenExpiredError as e:
        msg = (":warning: RASA36 monitoring: Gmail alert token expired — ToO alert intake is DOWN. "
               "Re-mint with `python configuration/keys/gmail.py`, then restart monitoring.py. "
               f"({e})")
        print(f"[{datetime.datetime.now()}] {msg}")
        try:
            from tcspy.utils.connector import SlackConnector
            slack = SlackConnector(token_path=config['SLACK_TOKEN'],
                                   default_channel_id=config['SLACK_ALERT_CHANNEL'])
            slack.post_message(text=msg)
        except Exception as se:
            print(f"[{datetime.datetime.now()}] Failed to post Slack token alert: {se}")
        return False
    except Exception as e:
        # Any other failure (network, missing config) — don't block startup, just warn.
        print(f"[{datetime.datetime.now()}] Gmail token preflight inconclusive ({e}); "
              f"starting AlertMonitor anyway.")
        return True


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print(f"[{datetime.datetime.now()}] Log file: {_tee._log_path()}")

    makers = {
        'AlertMonitor': _make_alert_monitor_thread,
        'DataTransfer': _make_data_transfer_thread,
    }
    threads = {'DataTransfer': _make_data_transfer_thread()}
    if _preflight_gmail_token():
        threads['AlertMonitor'] = _make_alert_monitor_thread()

    for t in threads.values():
        t.start()
    print(f"[{datetime.datetime.now()}] Monitoring started.")

    while not _stop_event.is_set():
        time.sleep(10)
        for name, t in list(threads.items()):
            if not t.is_alive():
                print(f"[{datetime.datetime.now()}] {name} thread died — restarting.")
                new_t = makers[name]()
                new_t.start()
                threads[name] = new_t

    print(f"[{datetime.datetime.now()}] Monitoring stopped.")
