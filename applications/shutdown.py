#%%


from multiprocessing import Event, Lock
from threading import Thread
import time

from tcspy.configuration import mainConfig
from tcspy.devices import MultiTelescopes
from tcspy.utils.exception import *

from tcspy.action.level1 import Warm
from tcspy.action.level1 import SlewAltAz
from tcspy.action.level1 import FansOff
from tcspy.action import MultiAction

#%%

class Shutdown(mainConfig):
    
    def __init__(self,
                 MultiTelescopes,
                 abort_action : Event,
                 ):
        super().__init__()
        self.multitelescopes = MultiTelescopes
        self.abort_action = abort_action
        self.is_running = False
        self.succeeded = False
        self.failure_reason = ''

    def run(self, fanoff = True, slew = True, warm = True):
        startup_thread = Thread(target=self._process, kwargs = dict(fanoff = fanoff, slew = slew, warm = warm))
        startup_thread.start()
    
    def abort(self):
        self.abort_action.set()

    def _process(self, fanoff = True, slew = True, warm = True):
        self.is_running = True
        self.multitelescopes.register_logfile()
        self.multitelescopes.update_statusfile(status = 'busy', do_trigger = True)
        self.multitelescopes.log.info(f'[{type(self).__name__}] is triggered.')
        try:
            if fanoff:
                # Focuser fans off
                params_fanson = []
                for telescope_name, telescope in self.multitelescopes.devices.items():
                    params_fanson.append(dict())

                multi_fanson = MultiAction(array_telescope= self.multitelescopes.devices.values(), array_kwargs= params_fanson, function = FansOff, abort_action = self.abort_action)
                result_multi_fanson = multi_fanson.shared_memory

                ## Run
                try:
                    multi_fanson.run()
                except AbortionException:
                    self.multitelescopes.log.warning(f'[{type(self).__name__}] is aborted.')

                ## Check result
                for tel_name, result in result_multi_fanson.items():
                    is_succeeded = result_multi_fanson[tel_name]['succeeded']
                    if not is_succeeded:
                        exc = result_multi_fanson[tel_name].get('exception', 'unknown')
                        self.failure_reason += f'FansOff[{tel_name}]:{exc}; '
                        self.multitelescopes.log_dict[tel_name].critical(f'[{type(self).__name__}] is failed: Fans operation failure.')
                        self.multitelescopes.remove(tel_name)

                ## Check len(devices) > 0
                if len(self.multitelescopes.devices) == 0:
                    raise ActionFailedException(f'[{type(self).__name__}] is Failed. Telescopes are not specified')

                ## Check abort_action
                if self.abort_action.is_set():
                    self.multitelescopes.log.warning(f'[{type(self).__name__}] is aborted.')
                    raise AbortionException(f'[{type(self).__name__}] is aborted.')

            if slew:
                # Telescope slewing
                params_slew = []
                for telescope_name, telescope in self.multitelescopes.devices.items():
                    params_slew.append(dict(alt = self.config['SHUTDOWN_ALT'],
                                            az = self.config['SHUTDOWN_AZ']))

                multi_slew = MultiAction(array_telescope= self.multitelescopes.devices.values(), array_kwargs= params_slew, function = SlewAltAz, abort_action = self.abort_action)
                result_multi_slew = multi_slew.shared_memory

                ## Run
                try:
                    multi_slew.run()
                except AbortionException:
                    self.multitelescopes.log.warning(f'[{type(self).__name__}] is aborted.')

                ## Check result
                for tel_name, result in result_multi_slew.items():
                    is_succeeded = result_multi_slew[tel_name]['succeeded']
                    if not is_succeeded:
                        exc = result_multi_slew[tel_name].get('exception', 'unknown')
                        self.failure_reason += f'Slew[{tel_name}]:{exc}; '
                        self.multitelescopes.log_dict[tel_name].critical(f'[{type(self).__name__}] is failed: Slewing failure.')
                        self.multitelescopes.remove(tel_name)

                ## Check len(devices) > 0
                if len(self.multitelescopes.devices) == 0:
                    raise ActionFailedException(f'[{type(self).__name__}] is Failed. Telescopes are not specified')

                ## Check abort_action
                if self.abort_action.is_set():
                    self.multitelescopes.log.warning(f'[{type(self).__name__}] is aborted.')
                    raise AbortionException(f'[{type(self).__name__}] is aborted.')

            if warm:
                # Warm camera
                params_warm = []
                for telescope_name, telescope in self.multitelescopes.devices.items():
                    params_warm.append(dict(settemperature = self.config['SHUTDOWN_CCDTEMP'],
                                            tolerance = self.config['SHUTDOWN_CCDTEMP_TOLERANCE']))

                multi_warm = MultiAction(array_telescope= self.multitelescopes.devices.values(), array_kwargs= params_warm, function = Warm, abort_action = self.abort_action)
                result_multi_warm = multi_warm.shared_memory

                ## Run
                try:
                    multi_warm.run()
                except AbortionException:
                    self.multitelescopes.log.warning(f'[{type(self).__name__}] is aborted.')

                ## Check result
                for tel_name, result in result_multi_warm.items():
                    is_succeeded = result_multi_warm[tel_name]['succeeded']
                    if not is_succeeded:
                        exc = result_multi_warm[tel_name].get('exception', 'unknown')
                        self.failure_reason += f'Warm[{tel_name}]:{exc}; '
                        self.multitelescopes.log_dict[tel_name].critical(f'[{type(self).__name__}] is failed: Warming failure.')
                        self.multitelescopes.remove(tel_name)

                ## Check len(devices) > 0
                if len(self.multitelescopes.devices) == 0:
                    raise ActionFailedException(f'[{type(self).__name__}] is Failed. Telescopes are not specified')

            self.multitelescopes.log.info(f'[{type(self).__name__}] is finished.')
            self.succeeded = True
        finally:
            self.multitelescopes.update_statusfile(status = 'idle', do_trigger = True)
            self.is_running = False

# %%
if __name__ == '__main__':
    from tcspy.devices import MultiTelescopes
    from tcspy.utils.connector import SlackConnector
    from tcspy.utils import NightSession
    
    M = MultiTelescopes()
    abort_aciton = Event()
    S = Shutdown(M, abort_aciton)
    slack = SlackConnector(token_path= S.config['SLACK_TOKEN'], default_channel_id= S.config['SLACK_DEFAULT_CHANNEL'])
    obsnight = NightSession().obsnight_utc
    tonight_str = '%.4d-%.2d-%.2d'%(obsnight.sunrise_civil.datetime.year, obsnight.sunrise_civil.datetime.month, obsnight.sunrise_civil.datetime.day)
    message_ts = slack.get_message_ts(match_string = f'{S.config["SYSTEM_NAME"]} Observation on {tonight_str}')
    if message_ts:
        slack.post_thread_message(message_ts = message_ts, text = f'{type(S).__name__} is triggered: {time.strftime("%H:%M:%S", time.localtime())}')
    S.run(fanoff = True,                    
          slew = True,
          warm = True)
    while S.is_running:
        time.sleep(0.1)
    if message_ts:
        slack.post_thread_message(message_ts = message_ts, text = f'{type(S).__name__} is finished: {time.strftime("%H:%M:%S", time.localtime())}')




# %%
