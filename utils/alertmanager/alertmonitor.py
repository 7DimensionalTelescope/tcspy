
#%%
from tcspy.configuration import mainConfig
from tcspy.utils.alertmanager import AlertBroker
from tcspy.utils.alertmanager import Alert
import queue
import datetime
import os
import time
import numpy as np
from astropy.io import ascii
from astropy.table import Table
import threading
import json
from astropy.time import Time
import shutil
from tcspy.utils.databases import DB_Dynamic

#%%

class AlertMonitor(mainConfig):
    
    def __init__(self):
        super().__init__()
        self.alertbroker = AlertBroker()
        self.alert_queue = queue.Queue()
        self.DB_dynamic = DB_Dynamic(Time.now())
        self.active_alerts = {}
        self.pending_alerts = {}
        self._pending_alerts_lock = threading.Lock()

    def monitor_alert(self,
                      send_slack: bool = True,
                      send_email: bool = True,
                      check_interval: int = 30,  # seconds
                      # Mail configuration
                      since_days : int = 3,
                      max_email_alerts: int = 5,
                      # Google Sheets configuration
                      max_sheet_alerts: int = 5,
                      match_to_tiles: bool = False,
                      match_tolerance_minutes: int = 5,
                      # Push notification options
                      use_push: bool = False,
                      push_poll_interval: int = 1):
        """
        Automatically monitors for new alerts (email and Google Sheets), and
        processes each alert in a separate thread while keeping track of active alerts.
        send_slack: bool = True
        send_email: bool = True
        check_interval: int = 30  # seconds
        # Mail configuration
        since_days : int = 3
        max_email_alerts: int = 5
        # Google Sheets configuration
        max_sheet_alerts: int = 5
        match_to_tiles: bool = False
        match_tolerance_minutes: int = 5
        # Push notification options
        use_push: bool = False           — use Gmail REST API + Pub/Sub instead of timed polling
        push_poll_interval: int = 1      — seconds between Pub/Sub pulls (use_push=True only)
        """
        print("Starting automatic alert monitoring with multithreading.")
        if use_push:
            print("Push notifications enabled. Registering Gmail watch...")
            self.alertbroker.setup_push()
            print("Gmail watch registered. Polling Pub/Sub every %d s." % push_poll_interval)

        # Start shared observation-monitoring thread for all pending alerts
        pending_monitor = threading.Thread(
            target=self._monitor_pending_alerts,
            args=(send_slack, send_email),
            daemon=True
        )
        pending_monitor.start()
        print(f"[{datetime.datetime.now()}] Pending alert monitor thread started.")

        active_threads = []

        def _check_and_dispatch():
            if use_push:
                self.check_new_mail_push(
                    match_to_tiles=match_to_tiles,
                    match_tolerance_minutes=match_tolerance_minutes
                )
            else:
                self.check_new_mail(
                    since_days=since_days,
                    max_numbers=max_email_alerts,
                    match_to_tiles=match_to_tiles,
                    match_tolerance_minutes=match_tolerance_minutes
                )
            while not self.alert_queue.empty():
                alert = self.alert_queue.get()
                print(f"[{datetime.datetime.now()}] New alert received: {alert.key}. Starting a new thread.")
                alert_thread = threading.Thread(
                    target=self.trigger_alert,
                    args=(alert, send_slack, send_email)
                )
                alert_thread.start()
                self.active_alerts[alert.key] = {}
                self.active_alerts[alert.key]["alert"] = alert
                self.active_alerts[alert.key]["status"] = "Processing"
                self.active_alerts[alert.key]["thread"] = alert_thread
                active_threads.append(alert_thread)
                time.sleep(float(self.config.get('ALERTBROKER_DISPATCH_STAGGER', 1)))

        while True:
            try:
                if use_push:
                    has_new = self.alertbroker.poll_pubsub()
                    if has_new:
                        print(f"[{datetime.datetime.now()}] Push notification received — checking mail.")
                        _check_and_dispatch()
                        # Drain duplicate notifications queued for the same event
                        while self.alertbroker.poll_pubsub():
                            pass
                    time.sleep(push_poll_interval)
                else:
                    # Check for new alerts in email
                    print(f"[{datetime.datetime.now()}] Checking for new email alerts...")
                    _check_and_dispatch()

                    # Check for new alerts in Google Sheets
                    # print(f"[{datetime.datetime.now()}] Checking for new Google Sheets alerts...")
                    # self.check_new_sheet(max_numbers=max_sheet_alerts,
                    #                      match_to_tiles = match_to_tiles,
                    #                      match_tolerance_minutes = match_tolerance_minutes)

                    # Wait before checking for new alerts again
                    print(f"[{datetime.datetime.now()}] Waiting for {check_interval} seconds before the next check.")
                    time.sleep(check_interval)

                # Remove finished threads from the active list and update alert statuses
                active_threads = [t for t in active_threads if t.is_alive()]
                for alert_key, alert_data in list(self.active_alerts.items()):
                    if alert_data["thread"] and not alert_data["thread"].is_alive():
                        alert_data["status"] = "Completed"
                        print(f"[{datetime.datetime.now()}] Alert {alert_key} processing completed.")
                        del self.active_alerts[alert_key]

            except Exception as e:
                print(f"An error occurred during automatic alert monitoring: {e}")
                time.sleep(check_interval)
    
    def trigger_alert(self,
                      alert: Alert,
                      send_slack: bool = True,
                      send_email: bool = True):
        """
        Process an alert, manage its lifecycle, and send notifications.

        This function triggers an alert, manages its insertion into the database,
        monitors its status until observation is complete, and sends notifications
        (Slack and email) based on the result.

        Parameters:
        ----------
        alert : Alert
            The alert object containing details of the observation.
        send_slack : bool, optional
            Whether to send the alert notification via Slack (default is True).
        send_email : bool, optional
            Whether to send the alert notification via email (default is True).
        """
        now_str = "UTC " + datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        # DB insert comes first: it is the only step the observation loop depends on,
        # so nothing (observability computation, Slack, email) may precede it.
        alert.statuspath = os.path.join(self.config['ALERTBROKER_STATUSPATH'], os.path.basename(alert.historypath))
        print(f"[{datetime.datetime.now()}] Inserting alert into the database.")
        alert = self.alertbroker.input_alert(alert)
        self.update_alertstatus(alert, alert.statuspath)
        self.alertbroker.save_alerthistory(alert = alert, history_path = alert.historypath)
        print(f"[{datetime.datetime.now()}] Alert inserted and history saved.")

        # Determine the scheduled/observable time for the message.
        # Priority: explicit requested obs_starttime > computed observability-based time > now.
        # If observability can be determined synchronously, the exact start time (or
        # "not observable tonight") is stated directly on the alert message; otherwise a
        # thread message is posted later as a fallback (see below).
        scheduled_time = now_str
        observability_determined = True
        requested_time = None
        if alert.formatted_data and 'obs_starttime' in alert.formatted_data.colnames:
            val = str(alert.formatted_data['obs_starttime'][0]).strip()
            if val and val.lower() not in ('', '0', 'none'):
                requested_time = val

        if requested_time:
            scheduled_time = requested_time
        else:
            try:
                computed = self._compute_scheduled_time(alert)
                if computed:
                    scheduled_time = computed
                else:
                    observability_determined = False
            except Exception as e:
                print(f"[{datetime.datetime.now()}] Failed to compute observable time: {e}")
                observability_determined = False

        # Send the alert via Slack
        slack_message_ts = None
        if send_slack:
            print(f"[{datetime.datetime.now()}] Sending alert notification to Slack.")
            slack_message_ts = self.alertbroker.send_alertslack(alert, scheduled_time=scheduled_time)
            if slack_message_ts:
                self.update_alertstatus(alert, alert.statuspath, slack_ts=slack_message_ts)

        # Send the alert via email
        if send_email:
            print(f"[{datetime.datetime.now()}] Sending alert notification via email.")
            self.alertbroker.send_alertmail(alert,
                                            users=self.users['authorized'] + self.users['normal'],
                                            scheduled_time=scheduled_time,
                                            attachment=os.path.join(alert.historypath, 'alert_formatted.ascii_fixed_width'))

        # Warn if current weather is unsafe
        if send_slack and slack_message_ts:
            try:
                is_safe = self._is_safe()
                if is_safe is False:
                    self.alertbroker._set_slack()
                    self.alertbroker.slack.post_thread_message(
                        slack_message_ts,
                        ':rain_cloud: *Current weather is unsafe* — ToO observation is queued and will start automatically when weather clears.'
                    )
            except Exception as e:
                print(f"[{datetime.datetime.now()}] Failed to post weather warning to Slack: {e}")

        # Fallback: if observability could not be determined synchronously, post it in a thread
        if send_slack and slack_message_ts and not requested_time and not observability_determined:
            try:
                computed = self._compute_scheduled_time(alert)
                self.alertbroker._set_slack()
                if computed and computed.startswith('UTC'):
                    self.alertbroker.slack.post_thread_message(
                        slack_message_ts,
                        f':telescope: *Observability* — observation can start at `{computed}`.'
                    )
                elif computed:
                    self.alertbroker.slack.post_thread_message(
                        slack_message_ts,
                        f':no_entry: *Observability* — {computed}.'
                    )
                else:
                    self.alertbroker.slack.post_thread_message(
                        slack_message_ts,
                        ':grey_question: *Observability* — could not be determined automatically; please check manually.'
                    )
            except Exception as e:
                print(f"[{datetime.datetime.now()}] Failed to post observability info to Slack: {e}")

        # Hand off to the shared observation monitor — no per-alert blocking loop
        with self._pending_alerts_lock:
            self.pending_alerts[alert.key] = {
                'alert': alert,
                'slack_ts': slack_message_ts,
                'deadline': time.time() + 86400 * 2,
                'last_num_observed': -1,
            }
        print(f"[{datetime.datetime.now()}] Alert {alert.key} registered for observation monitoring (48-hour window).")

    def _monitor_pending_alerts(self, send_slack: bool, send_email: bool):
        """Single shared thread: polls DB for all registered alerts and dispatches completion/failure notifications."""
        print(f"[{datetime.datetime.now()}] Pending alert monitor started.")
        while True:
            check_interval = 60 if self._is_nighttime() else 300
            time.sleep(check_interval)

            with self._pending_alerts_lock:
                if not self.pending_alerts:
                    continue
                pending_snapshot = dict(self.pending_alerts)

            try:
                observation_status = self.DB_dynamic.data
            except Exception as e:
                print(f"[{datetime.datetime.now()}] [PendingMonitor] DB query failed: {e}")
                continue

            now = time.time()
            phase = "night" if self._is_nighttime() else "day"

            for alert_key, entry in pending_snapshot.items():
                alert = entry['alert']
                try:
                    # 48-hour deadline
                    if now > entry['deadline']:
                        print(f"[{datetime.datetime.now()}] [{phase}] Alert {alert_key} expired (48 h).")
                        requester = alert.alert_sender if alert.alert_sender != '7dt.observation.broker@gmail.com' else None
                        if send_slack:
                            self.alertbroker.send_failedslack(alert=alert, message_ts=entry['slack_ts'])
                        if send_email:
                            if requester:
                                self.alertbroker.send_failedmail(alert=alert, users=requester, cc_users=self.users['admin'])
                            else:
                                self.alertbroker.send_failedmail(alert=alert, users=self.users['admin'])
                        alert.is_observed = False
                        self.alertbroker.save_alerthistory(alert=alert, history_path=alert.historypath)
                        self.update_alertstatus(alert, alert.statuspath)
                        with self._pending_alerts_lock:
                            self.pending_alerts.pop(alert_key, None)
                        continue

                    # Check observation progress
                    alert_targets = alert.formatted_data
                    alert_observable_targets = alert_targets[alert_targets['is_observable'].astype(str) == 'True']
                    if len(alert_observable_targets) == 0:
                        continue

                    alert_obs_status = observation_status[np.isin(observation_status['id'], alert_observable_targets['id'])]
                    is_observed_each = [s.lower() == 'observed' for s in alert_obs_status['status']]
                    num_observed = sum(is_observed_each)
                    is_all_observed = bool(is_observed_each) and all(is_observed_each)
                    alert.num_observed_targets = num_observed

                    # Log only on count change
                    if num_observed != entry['last_num_observed']:
                        remaining_h = (entry['deadline'] - now) / 3600
                        print(f"[{datetime.datetime.now()}] [{phase}] Alert {alert_key}: "
                              f"{num_observed}/{len(alert_observable_targets)} observed. "
                              f"Remaining: {remaining_h:.1f} h.")
                        with self._pending_alerts_lock:
                            if alert_key in self.pending_alerts:
                                self.pending_alerts[alert_key]['last_num_observed'] = num_observed

                    if is_all_observed:
                        observed_time = alert_obs_status['obs_endtime'][0]
                        print(f"[{datetime.datetime.now()}] Alert {alert_key} fully observed at {observed_time}.")
                        alert.is_observed = True
                        self.alertbroker.save_alerthistory(alert=alert, history_path=alert.historypath)
                        self.update_alertstatus(alert, alert.statuspath)
                        requester = alert.alert_sender if alert.alert_sender != '7dt.observation.broker@gmail.com' else None
                        if send_slack:
                            self.alertbroker.send_observedslack(alert=alert, message_ts=entry['slack_ts'], observed_time=observed_time)
                        if send_email:
                            if requester:
                                self.alertbroker.send_observedmail(alert=alert, users=requester, cc_users=self.users['admin'], observed_time=observed_time)
                            else:
                                self.alertbroker.send_observedmail(alert=alert, users=self.users['admin'], observed_time=observed_time)
                        with self._pending_alerts_lock:
                            self.pending_alerts.pop(alert_key, None)

                except Exception as e:
                    print(f"[{datetime.datetime.now()}] [PendingMonitor] Error processing alert {alert_key}: {e}")

    def _is_safe(self):
        """Return True/False based on weather or safetymonitor. Returns None if status is unavailable."""
        try:
            safe_type = self.config.get('NIGHTOBS_SAFETYPE', 'safetymonitor').lower()
            if safe_type == 'weather':
                from tcspy.devices.weather import mainWeather
                if not hasattr(self, '_weather_inst'):
                    self._weather_inst = mainWeather()
                status = self._weather_inst.get_status()
            else:
                from tcspy.devices.safetymonitor import mainSafetyMonitor
                if not hasattr(self, '_safetymonitor_inst'):
                    self._safetymonitor_inst = mainSafetyMonitor()
                status = self._safetymonitor_inst.get_status()
            is_safe = status.get('is_safe', None)
            return bool(is_safe) if is_safe is not None else None
        except Exception as e:
            print(f"[{datetime.datetime.now()}] Weather/safety check failed: {e}")
            return None

    def _compute_scheduled_time(self, alert: Alert):
        """Determine when the ToO target(s) can be observed tonight.

        Returns a human-readable string for the 'scheduled at(on)' line:
        - "UTC YYYY-MM-DD HH:MM:SS (now)"   — observable at the current time
        - "UTC YYYY-MM-DD HH:MM:SS"         — earliest time it rises into the observable window tonight
        - "Not observable tonight"          — never observable during tonight's window
        Returns None if observability cannot be determined (caller falls back to a thread message).
        """
        import astropy.units as u
        from tcspy.utils.target import MultiTargets
        from tcspy.utils import NightSession

        targets = alert.formatted_data
        if not targets or len(targets) == 0:
            return None

        # Whether each target is ever observable tonight (computed at decode time)
        observable_tonight = np.array([str(x).strip().lower() == 'true' for x in targets['is_observable']])
        if not observable_tonight.any():
            return 'Not observable tonight'

        ra = np.array([float(r) for r in targets['RA']])
        dec = np.array([float(d) for d in targets['De']])
        M = MultiTargets(targets_ra=ra, targets_dec=dec)

        session = NightSession()
        night_start = session.obsnight_utc.sunset_observation
        night_end = session.obsnight_utc.sunrise_observation
        now = Time.now()
        window_start = now if now > night_start else night_start

        if window_start >= night_end:
            return 'Not observable tonight'

        min_alt = float(self.config.get('TARGET_MINALT', 30))
        max_alt = float(self.config.get('TARGET_MAXALT', 90))

        # Observable right now? (altitude within the configured window)
        try:
            alt_now = np.atleast_1d(M.altaz(window_start).alt.deg)
            observable_now = (alt_now >= min_alt) & (alt_now <= max_alt) & observable_tonight
            if observable_now.any():
                return "UTC " + window_start.datetime.strftime('%Y-%m-%d %H:%M:%S') + " (now)"
        except Exception:
            pass

        # Otherwise, earliest rise into the observable window for the rest of tonight
        try:
            rise_times = M.risetime(window_start, mode='next', horizon=min_alt)
            if getattr(rise_times, 'isscalar', False):
                rise_times = rise_times.reshape(1)
        except Exception:
            return None

        earliest = None
        for rt, ok in zip(rise_times, observable_tonight):
            if not ok:
                continue
            try:
                if rt is None or getattr(rt, 'mask', False) or np.isnan(rt.jd):
                    continue
                if rt < night_end and (earliest is None or rt < earliest):
                    earliest = rt
            except Exception:
                continue

        if earliest is not None:
            return "UTC " + earliest.datetime.strftime('%Y-%m-%d %H:%M:%S')

        # Observable tonight overall, but no rise remaining in the window (e.g. already set)
        return 'Not observable for the rest of tonight'

    def _is_nighttime(self) -> bool:
        from tcspy.devices.observer import mainObserver
        if not hasattr(self, '_observer_inst'):
            self._observer_inst = mainObserver()
        return bool(self._observer_inst.is_night(Time.now()))

    @staticmethod
    def _alert_target_names(alert : Alert):
        """Return the ToO target name(s) as embedded in the image folder/tar names.

        Mirrors mainImage.save(): prefer 'note' (real target name for tile-matched
        targets, where 'objname' holds the tile id) and fall back to 'objname'.
        """
        names = []
        if not alert.formatted_data:
            return names
        cols = alert.formatted_data.colnames
        for row in alert.formatted_data:
            name = ''
            if 'note' in cols:
                name = str(row['note'] or '').strip()
            if name.lower() in ('', 'none', 'nan'):
                name = ''
            if not name and 'objname' in cols:
                name = str(row['objname'] or '').strip()
            name = name.replace(' ', '_')
            if name:
                names.append(name)
        return names

    def update_alertstatus(self,
                           alert : Alert,
                           status_path : str,
                           slack_ts : str = None):
        if alert.is_observed == False:
            if not alert.alert_data:
                raise ValueError('The alert data is not read or received yet')

            if not os.path.exists(status_path):
                os.makedirs(status_path)

            # Save formatted_data (Optional)
            if alert.formatted_data:
                alert.formatted_data.write(os.path.join(status_path, 'alert_formatted.ascii_fixed_width'), format = 'ascii.fixed_width', overwrite = True)

            # Save alert_data
            with open(os.path.join(status_path, 'alert_rawdata.json'), 'w') as f:
                json.dump(alert.alert_data, f, indent = 4)

            # Load existing status to preserve slack_ts if not provided
            status_file = os.path.join(status_path, 'alert_status.json')
            existing_slack_ts = None
            if os.path.exists(status_file):
                try:
                    with open(status_file) as f:
                        existing = json.load(f)
                    existing_slack_ts = existing.get('slack_ts')
                except Exception:
                    pass

            # Save the alert status as json
            alert_status = dict()
            alert_status['alert_type'] = alert.alert_type
            alert_status['alert_sender'] = alert.alert_sender
            alert_status['is_inputted'] = alert.is_inputted
            alert_status['is_observed'] = alert.is_observed
            alert_status['num_observed_targets'] = alert.num_observed_targets
            alert_status['is_matched_to_tiles'] = alert.is_matched_to_tiles
            alert_status['distance_to_tile_boundary'] = alert.distance_to_tile_boundary
            alert_status['update_time'] = Time.now().isot
            alert_status['key'] = alert.key
            # Store the ToO target name(s) so the data-transfer notification can be matched
            # to the correct alert thread (folder/tar names embed this name).
            alert_status['target_names'] = self._alert_target_names(alert)
            alert_status['slack_ts'] = slack_ts if slack_ts is not None else existing_slack_ts
            with open(status_file, 'w') as f:
                json.dump(alert_status, f, indent = 4)

            print(f'Alert status is saved: {status_path}')
        else:
            if os.path.exists(status_path):
                shutil.rmtree(status_path)
                print(f"Alert status is removed: {status_path}")
            
    def check_new_mail(self,
                       mailbox = 'inbox',
                       since_days : int = 3,
                       max_numbers : int = 5,
                       match_to_tiles : bool = False,
                       match_tolerance_minutes : int = 5
                       ):
        """
        mailbox = 'inbox'
        since_days : int = 3
        max_numbers : int = 5
        match_to_tiles : bool = False
        match_tolerance_minutes : int = 5
        """
        
        alertlist = self.alertbroker.read_mail(mailbox = mailbox, since_days = since_days, max_numbers = max_numbers, match_to_tiles = match_to_tiles, match_tolerance_minutes = match_tolerance_minutes)
        if not alertlist:
            print("No new mail found")
            return None
        
        for alert in alertlist:
            # If any new alert received, put it in the queue
            if alert.alert_sender in self.users['authorized']:
                if alert.is_inputted == False:
                    self.alert_queue.put(alert)                
                    
    def check_new_mail_push(self,
                            match_to_tiles: bool = False,
                            match_tolerance_minutes: int = 5):
        alertlist = self.alertbroker.read_mail_push(
            match_to_tiles=match_to_tiles,
            match_tolerance_minutes=match_tolerance_minutes
        )
        if not alertlist:
            print("No new mail found")
            return None
        for alert in alertlist:
            if alert.alert_sender in self.users['authorized']:
                if alert.is_inputted == False:
                    self.alert_queue.put(alert)

    def check_new_sheet(self,
                        max_numbers : int = 5,
                        match_to_tiles : bool = False,
                        match_tolerance_minutes : int = 5
                       ):
        self.alertbroker._set_googlesheet()
        sheetlist = self.alertbroker.googlesheet.get_sheet_list()
        # Remove the sheet that contains "format" or "readme" in the name
        sheetlist = [sheet_name for sheet_name in sheetlist if "format" not in sheet_name.lower() and "readme" not in sheet_name.lower()]
        sheetlist = [sheet_name for sheet_name in sheetlist if sheet_name.endswith('ToO')]
        if not sheetlist:
            print("No new sheet found")
            return None
        # From the most recent sheet
        sheetlist.reverse()
        for sheet_name in sheetlist[:max_numbers]:
            # If any new alert received, put it in the queue
            alert = self.alertbroker.read_sheet(sheet_name = sheet_name, match_to_tiles = match_to_tiles, match_tolerance_minutes = match_tolerance_minutes)
            if alert.is_inputted == False:
                self.alert_queue.put(alert)                
    
    @property
    def users(self):
        users_dict = dict()
        users_dict['authorized'] = self.config['ALERTBROKER_AUTHUSERS']
        users_dict['normal'] = self.config['ALERTBROKER_NORMUSERS']
        users_dict['admin'] = self.config['ALERTBROKER_ADMINUSERS']
        return users_dict
# %%
if __name__ == "__main__":
    alertmonitor = AlertMonitor()
#%%
if __name__ == "__main__":
    alertmonitor.monitor_alert(send_slack = True,
                               send_email = True,
                               check_interval = 10,
                               since_days = 3,
                               max_email_alerts = 10,
                               max_sheet_alerts = 5,
                               match_to_tiles = True,
                               match_tolerance_minutes = 3)
# %%
