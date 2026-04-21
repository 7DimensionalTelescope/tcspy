
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
                      match_tolerance_minutes: int = 5):
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
        
        """
        print("Starting automatic alert monitoring with multithreading.")
        active_threads = []

        while True:
            try:
                # Check for new alerts in email
                print(f"[{datetime.datetime.now()}] Checking for new email alerts...")
                self.check_new_mail(
                    since_days=since_days, 
                    max_numbers=max_email_alerts, 
                    match_to_tiles=match_to_tiles, 
                    match_tolerance_minutes=match_tolerance_minutes
                )

                # Check for new alerts in Google Sheets
                print(f"[{datetime.datetime.now()}] Checking for new Google Sheets alerts...")
                self.check_new_sheet(max_numbers=max_sheet_alerts,
                                     match_to_tiles = match_to_tiles,
                                     match_tolerance_minutes = match_tolerance_minutes)

                # Process alerts in the queue
                while not self.alert_queue.empty():
                    alert = self.alert_queue.get()
                    print(f"[{datetime.datetime.now()}] New alert received: {alert.key}. Starting a new thread.")

                    # Start a new thread for the alert
                    alert_thread = threading.Thread(
                        target=self.trigger_alert, 
                        args=(alert, send_slack, send_email)
                    )
                    alert_thread.start()

                    # Update the thread information in self.active_alerts
                    self.active_alerts[alert.key] = {}
                    self.active_alerts[alert.key]["alert"] = alert
                    self.active_alerts[alert.key]["status"] = "Processing"
                    self.active_alerts[alert.key]["thread"] = alert_thread
                    active_threads.append(alert_thread)
                    time.sleep(5)

                # Remove finished threads from the active list and update alert statuses
                active_threads = [t for t in active_threads if t.is_alive()]
                for alert_key, alert_data in list(self.active_alerts.items()):
                    if alert_data["thread"] and not alert_data["thread"].is_alive():
                        alert_data["status"] = "Completed"
                        print(f"[{datetime.datetime.now()}] Alert {alert_key} processing completed.")
                        del self.active_alerts[alert_key]  # Remove completed alerts from self.active_alerts

            except Exception as e:
                print(f"An error occurred during automatic alert monitoring: {e}")
            
        
            # Wait before checking for new alerts again
            print(f"[{datetime.datetime.now()}] Waiting for {check_interval} seconds before the next check.")
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
        tonight_str = "UTC " + datetime.datetime.now().strftime("%Y-%m-%d")
        alert.statuspath = os.path.join(self.config['ALERTBROKER_STATUSPATH'], os.path.basename(alert.historypath))
        print(f"[{datetime.datetime.now()}] Inserting alert into the database.")
        alert = self.alertbroker.input_alert(alert)
        self.update_alertstatus(alert, alert.statuspath)
        self.alertbroker.save_alerthistory(alert = alert, history_path = alert.historypath)
        print(f"[{datetime.datetime.now()}] Alert inserted and history saved.")

        # Send the alert via Slack
        if send_slack:
            print(f"[{datetime.datetime.now()}] Sending alert notification to Slack.")
            slack_message_ts = self.alertbroker.send_alertslack(alert, scheduled_time=tonight_str)

        # Send the alert via email
        if send_email:
            print(f"[{datetime.datetime.now()}] Sending alert notification via email.")
            self.alertbroker.send_alertmail(alert, 
                                            users=self.users['authorized'] + self.users['normal'], 
                                            scheduled_time=tonight_str, 
                                            attachment=os.path.join(alert.historypath, 'alert_formatted.ascii_fixed_width'))

        # Monitor the alert for observation
        print(f"[{datetime.datetime.now()}] Monitoring alert status for observability.")
        alert_targets = alert.formatted_data
        alert_observable_targets = alert_targets[alert_targets['is_observable'].astype(str) == 'True']
        DB_status_path = os.path.join(self.config['DB_STATUSPATH'], f'DB_Dynamic.{self.config["DB_STATUSFORMAT"]}')
        observation_status = Table.read(DB_status_path, format=self.config['DB_STATUSFORMAT'])
        alert_observation_status = observation_status[np.isin(observation_status['id'], alert_observable_targets['id'])]
        
        # Set the maximum waiting time for the alert to be observed
        maximum_waiting_time = 86400  # Maximum waiting time in seconds (48 hours)
        is_alert_observed = False
        print(f"[{datetime.datetime.now()}] Waiting for the alert to be observed. Maximum wait: 48 hours.")

        while maximum_waiting_time > 0:
            time.sleep(15)
            observation_status = self.DB_dynamic.data
            #observation_status = Table.read(DB_status_path, format=self.config['DB_STATUSFORMAT'])
            alert_observation_status = observation_status[np.isin(observation_status['id'], alert_observable_targets['id'])]
            is_observed_each_target = [status.lower() == 'observed' for status in alert_observation_status['status']]
            is_alert_observed = all(is_observed_each_target)
            alert.num_observed_targets = sum(is_observed_each_target)
            print(f"[{datetime.datetime.now()}] {alert.num_observed_targets}/{len(alert_observable_targets)} targets observed.")
            
            if is_alert_observed:
                observed_time = alert_observation_status['obs_endtime'][0]
                print(f"[{datetime.datetime.now()}] All targets observed at {observed_time}.")
                break

            maximum_waiting_time -= 15

        alert.is_observed = is_alert_observed
        self.alertbroker.save_alerthistory(alert = alert, history_path = alert.historypath)
        self.update_alertstatus(alert, alert.statuspath)

        # Send final notifications based on observation result
        requester = alert.alert_sender if alert.alert_sender != '7dt.observation.broker@gmail.com' else None
        if is_alert_observed:
            print(f"[{datetime.datetime.now()}] Observation successful. Sending observed notifications.")
            if requester:
                self.alertbroker.send_observedmail(alert=alert, users=requester, cc_users=self.users['admin'], observed_time=observed_time)
            else:
                self.alertbroker.send_observedmail(alert=alert, users=self.users['admin'], observed_time=observed_time)
            
            self.alertbroker.send_observedslack(alert=alert, message_ts=slack_message_ts, observed_time=observed_time)
        else:
            print(f"[{datetime.datetime.now()}] Observation failed. Sending failure notifications.")
            if requester:
                self.alertbroker.send_failedmail(alert=alert, users=requester, cc_users=self.users['admin'])
            else:
                self.alertbroker.send_failedmail(alert=alert, users=self.users['admin'])
            self.alertbroker.send_failedslack(alert=alert, message_ts=slack_message_ts)

    def update_alertstatus(self, 
                           alert : Alert,
                           status_path : str):
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
            with open(os.path.join(status_path, 'alert_status.json'), 'w') as f:
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
        if len(alertlist) < 0:
            print("No new mail found")
            return None
        
        for alert in alertlist:
            # If any new alert received, put it in the queue
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
        if len(sheetlist) < 0:
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
                               check_interval = 30,
                               since_days = 3,
                               max_email_alerts = 10,
                               max_sheet_alerts = 5,
                               match_to_tiles = True,
                               match_tolerance_minutes = 3)
# %%
