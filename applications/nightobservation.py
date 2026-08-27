#%%
from astropy.time import Time
import astropy.units as u
from multiprocessing import Event, Lock, Process
from threading import Thread
import time
import uuid

from tcspy.action.level1 import *
from tcspy.action.level2 import *
from tcspy.action.level3 import *
from tcspy.configuration import mainConfig
from tcspy.devices import MultiTelescopes
from tcspy.devices import SingleTelescope
from tcspy.devices import TelescopeStatus
from tcspy.applications import Shutdown
from tcspy.utils.databases import DB
from tcspy.utils.error import *
from tcspy.utils.target import SingleTarget
from tcspy.utils.exception import *
from tcspy.utils.nightsession import NightSession
#%%

class NightObservation(mainConfig):

    def __init__(self,
                 MultiTelescopes : MultiTelescopes,
                 abort_action : Event,
                 slack = None,
                 message_ts : str = None,
                 ):
        super().__init__()
        self.multitelescopes = MultiTelescopes
        self.abort_action = abort_action
        self.slack = slack
        self.slack_message_ts = message_ts
        self.DB = DB(utctime = Time.now()).Dynamic
        self.obsnight = NightSession(Time.now()).obsnight_utc
        self.weather = next(iter(self.multitelescopes.devices.values())).devices['weather']
        self.safetymonitor = next(iter(self.multitelescopes.devices.values())).devices['safetymonitor']

        self.autofocus = self.autofocus_config()

        # Loop/abort timing and rapid-ToO policy; defaults preserve legacy behavior
        self.loop_interval = float(self.config.get('NIGHTOBS_LOOP_INTERVAL', 0.5))
        self.abort_poll_interval = float(self.config.get('NIGHTOBS_ABORT_POLL_INTERVAL', 0.2))
        self.abort_timeout = float(self.config.get('NIGHTOBS_ABORT_TIMEOUT', 300))
        self.rapidToO_af_policy = str(self.config.get('NIGHTOBS_RAPIDTOO_AF_POLICY', 'default')).lower()
        self.rapidToO_af_history_duration = float(self.config.get('NIGHTOBS_RAPIDTOO_AF_HISTORY_DURATION', 480))
        self.rapidToO_cooldown = float(self.config.get('NIGHTOBS_RAPIDTOO_COOLDOWN', 600))
        self.rapidToO_cooldown_bypass_new = str(self.config.get('NIGHTOBS_RAPIDTOO_COOLDOWN_BYPASS_NEW', False)).lower() == 'true'
        self._dispatched_rapid_ids = set()

        self.action_queue = list()
        self.tel_queue = dict()
        self.tel_lock = Lock()
        self.action_lock = Lock()
        self.is_running = False
        self.is_obs_triggered = False
        self.is_shutdown_triggered = False
        self.is_rapidToO_triggered = False
        self.last_ToO_trigger_time = Time.now().isot
        self._ToO_abort = Event()
        self._observation_abort = Event()
        self.initialize()
    
    def autofocus_config(self):
        class autofocus_config: 
            def __init__(self):
                self.use_history = True
                self.history_duration = 120 
                self.before_start = True
                self.when_filterchange = True
                self.when_elapsed = True
                self.elapsed_duration = 120
            def __repr__(self):
                txt = ('AUTOFOCUS CONFIGURATION ============\n'+
                       ''.join(f"autofocus.{key} = {value}\n" for key, value in self.__dict__.items())
                        )
                return txt
        return autofocus_config()
        
    def initialize(self):
        
        # Initialize Daily target table
        self.DB.initialize(initialize_all= True)

        # Reset targets left stuck at 'scheduled' by a previous unclean shutdown (crash/kill) —
        # nothing can legitimately hold that status while we are just starting up.
        reset_targets = self.DB.reset_stale_scheduled()
        if reset_targets:
            msg = f'Reset {len(reset_targets)} target(s) stuck at scheduled from a previous session: {", ".join(reset_targets)}'
            self.multitelescopes.log.warning(f'[{type(self).__name__}] {msg}')
            if self.slack:
                try:
                    if self.slack_message_ts:
                        self.slack.post_thread_message(self.slack_message_ts, f':warning: {msg}')
                    else:
                        self.slack.post_message(f':warning: {msg}')
                except Exception:
                    self.multitelescopes.log.warning('Failed to post stale-target reset notice to Slack', exc_info=True)

        # Connect Weather Updater
        Thread(target = self.weather.run, kwargs = dict(abort_action = self.abort_action), daemon = False).start()
        # Connect SafetyMonitor Updater
        Thread(target = self.safetymonitor.run, kwargs = dict(abort_action = self.abort_action), daemon = False).start()

        # Set device for safety check
        if self.config['NIGHTOBS_SAFETYPE'].upper() == 'WEATHER':
            self.is_safe = self._is_weather_safe
        else:
            self.is_safe = self._is_safetymonitor_safe

        # Get status of all telescopes
        status_devices = self.multitelescopes.status
        not_ready_tel = []
        for tel_name, status in status_devices.items():
            if self._is_tel_ready(status):
                self.tel_queue[tel_name] = self.multitelescopes.devices[tel_name]
            else:
                not_ready_tel.append(tel_name)
        if len(not_ready_tel) > 0:
            for tel_name in not_ready_tel:
                self.multitelescopes.log.warning(f'{tel_name} is not ready for observation')
            raise DeviceNotReadyException(f'{not_ready_tel} is not ready for observation')
    
    def run(self):
        if not self.is_running:
            Thread(target = self._process).start()
            self.is_running = True
        else:
            self.multitelescopes.log.critical(f'[{type(self).__name__}] cannot be run twice.')
            
    def dispatch_observation(self, target : SingleTarget, abort_action, observation_status = None):
        kwargs = dict(exptime = target['exptime'], 
                      count = target['count'],
                      filter_ = target['filter_'],
                      colormode = target['colormode'],
                      specmode = target['specmode'],
                      ntelescope = target['ntelescope'],
                      gain = target['gain'],
                      binning = target['binning'], 
                      imgtype = 'Light', 
                      ra = target['RA'],
                      dec = target['De'], 
                      name = target['objname'],
                      objtype = target['objtype'], 
                      id_ = target['id'],
                      note = target['note'],
                      comment = target['comment'],
                      is_ToO = target['is_ToO'],
                      is_rapidToO = target['is_rapidToO'],
                      force_slewing = True,
                      autofocus_use_history = self.autofocus.use_history,
                      autofocus_history_duration = self.autofocus.history_duration,
                      autofocus_before_start = self.autofocus.before_start,
                      autofocus_when_filterchange = self.autofocus.when_filterchange,
                      autofocus_when_elapsed = self.autofocus.when_elapsed,
                      autofocus_elapsed_duration = self.autofocus.elapsed_duration,
                      observation_status = observation_status)
        # Rapid ToO trades focus freshness for shutter latency (NIGHTOBS_RAPIDTOO_AF_POLICY: default/history/skip)
        if bool(target['is_rapidToO']) and self.rapidToO_af_policy != 'default':
            if self.rapidToO_af_policy == 'skip':
                kwargs['autofocus_before_start'] = False
                kwargs['autofocus_when_filterchange'] = False
                kwargs['autofocus_when_elapsed'] = False
            elif self.rapidToO_af_policy == 'history':
                kwargs['autofocus_before_start'] = True
                kwargs['autofocus_when_filterchange'] = False
                kwargs['autofocus_when_elapsed'] = False
                kwargs['autofocus_use_history'] = True
                kwargs['autofocus_history_duration'] = self.rapidToO_af_history_duration
            self.multitelescopes.log.info(f'Rapid ToO: autofocus policy [{self.rapidToO_af_policy}] applied for {target["objname"]}')
        # Check observability when observation_status is given (when observationn is resumed)
        is_observable = True
        if observation_status:
            singletarget = SingleTarget(observer = self.multitelescopes.observer, 
                                        ra = target['RA'], 
                                        dec = target['De'], 
                                        exptime = target['exptime'], 
                                        count = target['count'], 
                                        filter_ = target['filter_'], 
                                        binning = target['binning'], 
                                        specmode = target['specmode'],
                                        colormode = target['colormode'])
            is_observable = singletarget.is_observable(utctime= Time.now() + singletarget.exposure_info['exptime_tot'] * u.s)
        if not is_observable:
            self.multitelescopes.log.warning('Observation cannot be dispatched: Target is unobservable')
            return False
        
        # Dispatch observation
        obsmode = target['obsmode'].upper()
        do_trigger = False
        if obsmode == 'COLOR':
            if set(self.multitelescopes.devices.keys()) == set(self.tel_queue.keys()):
                telescopes = self.multitelescopes
                self._pop_telescope(telescope=telescopes)
                action = ColorObservation(multitelescopes= telescopes, abort_action = abort_action)
                kwargs.get('specmode', None)
                kwargs.get('filter_', None)
                kwargs['ntelescope'] = len(telescopes.devices)
                do_trigger = True
        elif obsmode == 'SPEC':
            if set(self.multitelescopes.devices.keys()) == set(self.tel_queue.keys()):
                telescopes = self.multitelescopes
                self._pop_telescope(telescope=telescopes)
                action = SpecObservation(multitelescopes= telescopes, abort_action = abort_action)
                kwargs.get('colormode', None)
                kwargs.get('filter_', None)
                kwargs['ntelescope'] = len(telescopes.devices)
                do_trigger = True
        elif obsmode == 'DEEP':
            ntelescope = target['ntelescope']
            if len(self.tel_queue) >= ntelescope:
                telescopes = MultiTelescopes(SingleTelescope_list = [self.tel_queue.popitem()[1] for i in range(ntelescope)])
                action = DeepObservation(multitelescopes= telescopes, abort_action = abort_action)
                kwargs.get('colormode', None)
                kwargs.get('specmode', None)
                do_trigger = True
        elif obsmode == 'SEARCH':
            if len(self.tel_queue) >= 1:
                _, telescopes = self.tel_queue.popitem()
                action = SingleObservation(singletelescope= telescopes, abort_action = abort_action)
                kwargs.get('colormode', None)
                kwargs.get('specmode', None)
                kwargs['ntelescope'] = 1
                do_trigger = True
        else:
            if len(self.tel_queue) >= 1:
                _, telescopes = self.tel_queue.popitem()
                kwargs.get('colormode')
                kwargs.get('specmode')
                kwargs['ntelescope'] = 1
                action = SingleObservation(singletelescope= telescopes, abort_action = abort_action)
                do_trigger = True
        if do_trigger:
            Thread(target = self.execute_observation, kwargs = {'action': action, 'telescopes': telescopes, 'kwargs': kwargs, 'target': target, 'observation_status': observation_status}, daemon = False).start()
    
    def execute_observation(self, action, telescopes, kwargs, target, observation_status, check_visibility : bool = False):
        if check_visibility:
            # Check visibility of the target
            singletarget = SingleTarget(observer = self.multitelescopes.observer,
                                        ra = target['RA'],
                                        dec = target['De'])
            is_observable = singletarget.is_observable(utctime= Time.now())
            if not is_observable:
                self.multitelescopes.log.warning('Observation cannot be dispatched: Target is unobservable')
                self.DB.update_target(update_values = [Time.now().isot, 'unobservable'], update_keys = ['obs_endtime','status'], id_value = [target['id'],target['objname']], id_key = ['id','objname'])
                self.DB.export_to_csv()
                return
        
        # Update kwargs with observation_status
        kwargs['observation_status'] = observation_status
        
        # Update target status to 'scheduled'
        self.DB.update_target(update_values = ['scheduled',Time.now().isot], update_keys = ['status','obs_starttime'], id_value = [target['id'],target['objname']], id_key = ['id','objname'])
        # Export to csv
        self.DB.export_to_csv()
        # Update telescope status to 'busy'
        telescopes.update_statusfile(status = 'busy', do_trigger = True)
        action_id = uuid.uuid4().hex
        # Pop the telescope from the tel_queue
        self._pop_telescope(telescope = telescopes)
        # Appedd the action and telescope to the action_queue
        self._put_action(target = target, action = action, telescopes = telescopes, action_id = action_id, kwargs = kwargs)
        
        # Run observation
        process = Process(target = action.run, kwargs = kwargs)
        process.start()
        abort_wait_start = time.time()
        while process.is_alive():
            # If a global abort has been signaled past the timeout, force-kill the stuck child
            if self.abort_action.is_set() and time.time() - abort_wait_start > self.abort_timeout:
                self.multitelescopes.log.warning('Global abort: terminating stuck observation process')
                process.terminate()
                process.join(timeout=10)
                if process.is_alive():
                    process.kill()
                break
            time.sleep(0.1)
        # Ensure is_running is cleared regardless of how the child exited (crash, unhandled exception, etc.)
        action.shared_memory['is_running'] = False

        # Check the exception
        exception = action.shared_memory['exception']
        succeeded = action.shared_memory.get('succeeded', False)
        if not exception and succeeded:
            self.DB.update_target(update_values = [Time.now().isot, 'observed'], update_keys = ['obs_endtime','status'], id_value = [target['id'],target['objname']], id_key = ['id','objname'])
            self.DB.export_to_csv()
            telescopes.update_statusfile(status = 'idle', do_trigger = True)
        elif not exception and not succeeded:
            self.DB.update_target(update_values = [Time.now().isot, 'failed'], update_keys = ['obs_endtime','status'], id_value = [target['id'],target['objname']], id_key = ['id','objname'])
            self.DB.export_to_csv()
            telescopes.update_statusfile(status = 'idle', do_trigger = True)
            self.multitelescopes.log.warning(f'[{type(self).__name__}] Observation of {target["objname"]} ended with no images (no exception but succeeded=False)')
        elif exception == 'AbortionException':
            self.DB.update_target(update_values = [Time.now().isot, 'aborted'], update_keys = ['obs_endtime','status'], id_value = [target['id'],target['objname']], id_key = ['id','objname'])
            self.DB.export_to_csv()
            telescopes.update_statusfile(status = 'idle', do_trigger = True)
        elif exception == 'ActionFailedException':
            self.DB.update_target(update_values = [Time.now().isot, 'failed'], update_keys = ['obs_endtime','status'], id_value = [target['id'],target['objname']], id_key = ['id','objname'])
            self.DB.export_to_csv()
            telescopes.update_statusfile(status = 'idle', do_trigger = True)
            if self.slack and self.slack_message_ts:
                try:
                    detail = action.shared_memory.get('exception_message') or 'ActionFailedException'
                    self.slack.post_thread_message(
                        self.slack_message_ts,
                        f':warning: Observation failed: *{target["objname"]}* — {detail}'
                    )
                except Exception:
                    self.multitelescopes.log.warning('Failed to post ActionFailedException to Slack', exc_info=True)
        # Pop the action and telescope from  the action_queue
        self._pop_action(action_id = action_id)
        # Apped the telescope to the tel_queue
        self._put_telescope(telescope = telescopes)
        
    def abort(self):
        # Abort NightObservation
        self.abort_action.set()
        aborted_action, aborted_observation_status = None, None
        if self.is_rapidToO_triggered:
            aborted_action, aborted_observation_status = self._abort_ToO()
        else:
            aborted_action, aborted_observation_status = self._abort_observation()
        self.is_running = False
        return aborted_action, aborted_observation_status    

    def _is_tel_ready(self, tel_status_dict):
        ready_tel = tel_status_dict['mount'].upper() == 'IDLE'
        ready_cam = tel_status_dict['camera'].upper() == 'IDLE'
        ready_filt = tel_status_dict['filterwheel'].upper() == 'IDLE'
        ready_focus = tel_status_dict['focuser'].upper() == 'IDLE'
        return all([ready_tel, ready_cam, ready_filt, ready_focus])
    
    def _is_weather_safe(self):
        weather_status = self.weather.get_status()
        if weather_status['is_safe'] == True:
            return True
        else:
            return False

    def _is_safetymonitor_safe(self):
        safetymonitor_status = self.safetymonitor.get_status()
        if safetymonitor_status['is_safe'] == True:
            return True
        else:
            return False
    
    def _rapidToOobservation(self):
        self.is_rapidToO_triggered = True
        aborted_action, aborted_observation_status = self._abort_observation()
        self.multitelescopes.log.info('ToO is triggered.================================')
        obs_start_time = self.obsnight.sunset_observation
        obs_end_time = self.obsnight.sunrise_observation
        now = Time.now()
        
        # Wait until sunset
        if now < obs_start_time:
            self.multitelescopes.log.info('Wait until sunset... [%.2f hours left]'%((obs_start_time - Time.now())*24).value)
        while now < obs_start_time:
            time.sleep(5)
            now = Time.now()
            if self.abort_action.is_set():
                self.multitelescopes.log.warning(f'[{type(self).__name__}] is aborted.')
                raise AbortionException(f'[{type(self).__name__}] is aborted.')

        aborted_action_ToO = None
        unsafe_weather_count = 0
        is_shutdown_triggered = False

        # Trigger observation until sunrise
        while now < obs_end_time:
            if self.abort_action.is_set():
                self.multitelescopes.log.warning(f'[{type(self).__name__}] is aborted.')
                raise AbortionException(f'[{type(self).__name__}] is aborted.')
            now = Time.now()
            
            # Target tbl initialization is handled lazily inside DB.best_target()
            # Retrieve best target
            best_target, score = self.DB.best_target(utctime = now)
            
            # Check weather status
            is_weather_safe = self.is_safe()
            # If weather is safe
            if is_weather_safe:
                if is_shutdown_triggered:
                    if self.slack and self.slack_message_ts:
                        try:
                            self.slack.post_thread_message(
                                self.slack_message_ts,
                                f':white_check_mark: *Weather recovered* — resuming ToO observations. ({Time.now().strftime("%H:%M:%S")} UTC)'
                            )
                        except Exception:
                            self.multitelescopes.log.warning('Failed to post weather recovery to Slack', exc_info=True)
                is_shutdown_triggered = False
                self.last_ToO_trigger_time = now.isot
                # If there is any aborted_action due to unsafe weather, resume the observation
                if aborted_action_ToO:
                    for action, observation_status in zip(aborted_action_ToO, aborted_observation_status_ToO):
                        time.sleep(0.5)
                        self.execute_observation(action = action['action'], telescopes = action['telescope'], kwargs = action['kwargs'], target = action['target'], observation_status = observation_status, check_visibility = True)
                    aborted_action_ToO = None
                # If there is no observable target
                if not best_target:
                    break
                
                # If ToO is aborted manually
                if not self.is_rapidToO_triggered:
                    break
                
                # If target is not ToO, finish loop
                if not best_target['is_rapidToO']:
                    break
                
                # Else; trigger observation
                else:
                    self._dispatched_rapid_ids.add(str(best_target['id']))
                    self.dispatch_observation(target = best_target, abort_action = self._ToO_abort)
            # If weather is unsafe
            else:
                #unsafe_weather_count += 1
                aborted_action_ToO, aborted_observation_status_ToO = self._abort_ToO()
                self.multitelescopes.log.info(f'[{type(self).__name__} ToO is aborted: Unsafe weather]')
                self._ToO_abort = Event()
                #self.is_rapidToO_triggered = True
                if not is_shutdown_triggered:
                    if self.slack and self.slack_message_ts:
                        try:
                            self.slack.post_thread_message(
                                self.slack_message_ts,
                                f':rain_cloud: *Unsafe weather detected* — ToO observations paused and telescope parked. ({Time.now().strftime("%H:%M:%S")} UTC)'
                            )
                        except Exception:
                            self.multitelescopes.log.warning('Failed to post weather alert to Slack', exc_info=True)
                    Shutdown(self.multitelescopes, self.abort_action).run(fanoff = False, slew = True, warm = False)
                    is_shutdown_triggered = True
                time.sleep(200)
            time.sleep(self.loop_interval)
            
        while len(self.action_queue) > 0:
            self.multitelescopes.log.info('Waiting for ToO to be finished')
            time.sleep(1)
        self.is_rapidToO_triggered = False
        self.multitelescopes.log.info(f'[{type(self).__name__}] rapid ToO observation is finished')
        self._observation_abort = Event()
        
        # Resume the ordinary aborted observation
        for action, observation_status in zip(aborted_action, aborted_observation_status):
            time.sleep(0.5)
            if set(action['telescope'].devices.keys()).issubset(self.tel_queue.keys()):
                self.execute_observation(action = action['action'], telescopes = action['telescope'], kwargs = action['kwargs'], target = action['target'], observation_status = observation_status, check_visibility= True)
        aborted_action = None
        return True

    def _process(self):
        is_shutdown_triggered = False
        aborted = False
        try:
            self.is_running = True
            self.multitelescopes.register_logfile()
            self.multitelescopes.log.info(f'[{type(self).__name__}] is triggered.')
            self._observation_abort = Event()
            self._ToO_abort = Event()
            obs_start_time = self.obsnight.sunset_observation
            obs_end_time = self.obsnight.sunrise_observation
            now = Time.now()

            # Wait until sunset
            if now < obs_start_time:
                self.multitelescopes.log.info('Wait until sunset... [%.2f hours left]'%((obs_start_time - Time.now())*24).value)
            while now < obs_start_time:
                time.sleep(5)
                now = Time.now()
                if self.abort_action.is_set():
                    self.multitelescopes.log.warning(f'[{type(self).__name__}] is aborted.')
                    aborted = True
                    return

            aborted_action, aborted_observation_status = None, None

            # Trigger observation until sunrise
            while now < obs_end_time:
                try:
                    if self.abort_action.is_set():
                        self.multitelescopes.log.warning(f'[{type(self).__name__}] is aborted.')
                        aborted = True
                        break
                    now = Time.now()

                    # Target tbl initialization is handled lazily inside DB.best_target()

                    # Check weather status
                    is_weather_safe = self.is_safe()
                    # If weather is safe
                    if is_weather_safe:
                        if is_shutdown_triggered:
                            if self.slack and self.slack_message_ts:
                                try:
                                    self.slack.post_thread_message(
                                        self.slack_message_ts,
                                        f':white_check_mark: *Weather recovered* — resuming observations. ({Time.now().strftime("%H:%M:%S")} UTC)'
                                    )
                                except Exception:
                                    self.multitelescopes.log.warning('Failed to post weather recovery to Slack', exc_info=True)
                        is_shutdown_triggered = False
                        # If there is any aborted_action due to unsafe weather, resume the observation
                        if aborted_action:
                            for action, observation_status in zip(aborted_action, aborted_observation_status):
                                time.sleep(0.5)
                                self.execute_observation(action = action['action'], telescopes = action['telescope'], kwargs = action['kwargs'], target = action['target'], observation_status = observation_status, check_visibility= True)
                            aborted_action = None
                        else:
                            # Retrieve best target
                            best_target, score = self.DB.best_target(utctime = now)
                            if best_target:
                                if bool(best_target['is_rapidToO']):
                                    since_last_ToO = (now - Time(self.last_ToO_trigger_time)).jd * 86400
                                    # A rapid ToO never dispatched before may bypass the cooldown (new event)
                                    is_new_rapidToO = self.rapidToO_cooldown_bypass_new and str(best_target['id']) not in self._dispatched_rapid_ids
                                    if since_last_ToO > self.rapidToO_cooldown or is_new_rapidToO:
                                        self._rapidToOobservation()
                                    else:
                                        # If ToO is re-triggered within the cooldown, trigger ordinary observation
                                        best_target, score = self.DB.best_target(utctime = now, force_non_ToO= True)
                                        if best_target:
                                            self.multitelescopes.log.info(f'Best target: {now.isot, best_target["objname"]}')
                                            self.dispatch_observation(target = best_target, abort_action = self._observation_abort)
                                else:
                                    self.multitelescopes.log.info(f'Best target: {now.isot, best_target["objname"]}')
                                    self.dispatch_observation(target = best_target, abort_action = self._observation_abort)
                            else:
                                self.multitelescopes.log.info('No observable target exists... Waiting for target being observable or new target input')
                    # If weather is unsafe
                    else:
                        if len(self.action_queue) > 0:
                            aborted_action, aborted_observation_status = self._abort_observation()
                            self.multitelescopes.log.info(f'[{type(self).__name__}] is aborted: Unsafe weather')
                        self.multitelescopes.log.info(f'[{type(self).__name__}] is waiting for safe weather condition')
                        self._observation_abort = Event()
                        if not is_shutdown_triggered:
                            if self.slack and self.slack_message_ts:
                                try:
                                    self.slack.post_thread_message(
                                        self.slack_message_ts,
                                        f':rain_cloud: *Unsafe weather detected* — observations paused and telescope parked. ({Time.now().strftime("%H:%M:%S")} UTC)'
                                    )
                                except Exception:
                                    self.multitelescopes.log.warning('Failed to post weather alert to Slack', exc_info=True)
                            Shutdown(self.multitelescopes, self.abort_action).run(fanoff = False, slew = True, warm = False)
                            is_shutdown_triggered = True
                        time.sleep(200)
                    time.sleep(self.loop_interval)
                except AbortionException:
                    self.multitelescopes.log.warning(f'[{type(self).__name__}] is aborted.')
                    aborted = True
                    break
                except Exception:
                    # A transient error in a single iteration (e.g. a DB hiccup) must not
                    # kill the whole night. Log the traceback and continue next iteration.
                    self.multitelescopes.log.exception(f'[{type(self).__name__}] loop iteration failed; recovering and continuing')
                    time.sleep(5)

            if not aborted and len(self.action_queue) > 0:
                aborted_action, aborted_observation_status = self._abort_observation()
            time.sleep(10)
            self.multitelescopes.log.info(f'[{type(self).__name__}] observation finished: {Time.now().isot}')
        except Exception:
            self.multitelescopes.log.exception(f'[{type(self).__name__}] terminated with an unexpected error')
        finally:
            self.is_running = False
            # Park/secure the telescope on exit unless this was a manual abort.
            if not aborted and not is_shutdown_triggered:
                try:
                    Shutdown(self.multitelescopes, self.abort_action).run(fanoff = False, slew = True, warm = False)
                except Exception:
                    self.multitelescopes.log.exception(f'[{type(self).__name__}] end-of-night Shutdown failed')
                is_shutdown_triggered = True
            self.multitelescopes.log.info(f'[{type(self).__name__}] is finished')
        
            
    def _put_action(self, target, action, telescopes, action_id, kwargs):
        # Acquire the lock before putting action into the action queue
        self.action_lock.acquire()
        try:
            # Put action and corresponding telescopes into the action queue
            self.action_queue.append({'target': target, 'action': action, 'telescope' : telescopes, 'id' : action_id, 'kwargs': kwargs})
        finally:
            # Release the lock
            self.action_lock.release()
            
    def _pop_action(self, action_id):
        # Acquire the lock before putting action into the action queue
        self.action_lock.acquire()
        try:
            # Put action and corresponding telescopes into the action queue
            self.action_queue = [item for item in self.action_queue if item.get('id') != action_id]
        finally:
            # Release the lock
            self.action_lock.release()
            
    def _put_telescope(self, telescope):
        # Acquire the lock before modifying self.used_telescopes
        self.tel_lock.acquire()
        try:
            # Append telescopes used in the action to the list
            if isinstance(telescope, SingleTelescope):
                status = TelescopeStatus(telescope).dict
                tel_name = telescope.tel_name
                #if self._is_tel_ready(status):
                self.tel_queue[tel_name] = telescope
            if isinstance(telescope, MultiTelescopes):
                status_devices = telescope.status
                for tel_name, status in status_devices.items():
                    #if self._is_tel_ready(status):
                    self.tel_queue[tel_name] = self.multitelescopes.devices[tel_name]
        finally:
            # Release the lock
            self.tel_lock.release()

    def _pop_telescope(self, telescope):
        # Acquire the lock before modifying self.used_telescopes
        self.tel_lock.acquire()
        try:
            # Append telescopes used in the action to the list
            if isinstance(telescope, SingleTelescope):
                self.tel_queue.pop(telescope.tel_name, None)
            if isinstance(telescope, MultiTelescopes):
                for tel_name, tel in telescope.devices.items():
                    self.tel_queue.pop(tel_name, None)
        finally:
            # Release the lock
            self.tel_lock.release()
    
    def _abort_observation(self):
        # Abort ordinary observation
        action_history = list(self.action_queue)
        observation_status_history = []
        self._observation_abort.set()
        if len(action_history) > 0:
            for action in action_history:
                action['telescope'].register_logfile()
                action['telescope'].log.warning('Waiting for ordinary observation aborted...')
                # Check process aborted
                action_observation = action['action']
                if isinstance(action_observation, (SpecObservation, DeepObservation, ColorObservation)):
                    observation_status = {tel_name: status['status'] for tel_name, status in action_observation.shared_memory['status'].items()}
                else:
                    observation_status =  action_observation.shared_memory['status']
                observation_status_history.append(observation_status.copy())
                abort_wait_start = time.time()
                while action_observation.shared_memory['is_running']:
                    if time.time() - abort_wait_start > self.abort_timeout:
                        self.multitelescopes.log.warning('Timeout waiting for observation to abort — forcing cleanup')
                        action_observation.shared_memory['is_running'] = False
                        break
                    time.sleep(self.abort_poll_interval)

                self._pop_action(action_id =action['id'])
                self._put_telescope(telescope = action['telescope'])
                self.DB.update_target(update_values = [Time.now().isot, 'aborted'], update_keys = ['obs_endtime','status'], id_value = [action['target']['objname'], action['target']['id']], id_key = ['objname','id'])
                self.DB.export_to_csv()
        # Get status of all telescopes
        return action_history, observation_status_history
        
    def _abort_ToO(self):
        # Abort ToO observation
        action_history = list(self.action_queue)
        observation_status_history = []
        self._ToO_abort.set()
        if len(action_history) > 0:
            for action in action_history:
                action['telescope'].register_logfile()
                action['telescope'].log.warning('Waiting for ordinary observation aborted...')
                # Check process aborted
                action_observation = action['action']
                if isinstance(action_observation, (SpecObservation, DeepObservation, ColorObservation)):
                    observation_status = {tel_name: status['status'] for tel_name, status in action_observation.shared_memory['status'].items()}
                else:
                    observation_status =  action_observation.shared_memory['status']
                observation_status_history.append(observation_status.copy())
                abort_wait_start = time.time()
                while action_observation.shared_memory['is_running']:
                    if time.time() - abort_wait_start > self.abort_timeout:
                        self.multitelescopes.log.warning('Timeout waiting for ToO observation to abort — forcing cleanup')
                        action_observation.shared_memory['is_running'] = False
                        break
                    time.sleep(self.abort_poll_interval)

                self._pop_action(action_id =action['id'])
                self._put_telescope(telescope = action['telescope'])
                self.DB.update_target(update_values = [Time.now().isot, 'aborted'], update_keys = ['obs_endtime','status'], id_value = action['target']['id'], id_key = 'id')
                self.DB.export_to_csv()
        self.is_rapidToO_triggered = False
        return action_history, observation_status_history


# %%
if __name__ == '__main__':
    from tcspy.devices import MultiTelescopes
    from tcspy.utils.connector import SlackConnector
    from tcspy.utils import NightSession
    M = MultiTelescopes()
    abort_action = Event()
    application = NightObservation(M, abort_action)
    slack = SlackConnector(token_path= application.config['SLACK_TOKEN'], default_channel_id= application.config['SLACK_DEFAULT_CHANNEL'])
    obsnight = NightSession().obsnight_utc
    tonight_str = '%.4d-%.2d-%.2d'%(obsnight.sunrise_civil.datetime.year, obsnight.sunrise_civil.datetime.month, obsnight.sunrise_civil.datetime.day)
    message_ts = slack.get_message_ts(match_string = f'{application.config["SYSTEM_NAME"]} Observation on {tonight_str}')
    if message_ts:
        slack.post_thread_message(message_ts,f'{type(application).__name__} is triggered: {time.strftime("%H:%M:%S", time.localtime())}')
    application.run()
    while application.is_running:
        time.sleep(0.1)
    if message_ts:
        slack.post_thread_message(message_ts,f'{type(application).__name__} is finished: {time.strftime("%H:%M:%S", time.localtime())}')

    
# %%
