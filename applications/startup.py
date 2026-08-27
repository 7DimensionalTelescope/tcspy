

#%%
from multiprocessing import Event, Lock
import time
from threading import Thread
from astropy.time import Time

from tcspy.configuration import mainConfig
from tcspy.devices import MultiTelescopes
from tcspy.utils.exception import *

from tcspy.action.level1 import Cool
from tcspy.action.level1 import Connect
from tcspy.action.level1 import Home
from tcspy.action.level1 import SlewAltAz
from tcspy.action.level1 import FansOn
from tcspy.action import MultiAction

#%%

class Startup(mainConfig):
    """
    A class representing the startup process for multiple telescopes.

    Parameters
    ----------
    MultiTelescopes : MultiTelescopes
        An instance of MultiTelescopes class representing a collection of telescopes.
    abort_action : Event
        An instance of the built-in Event class to handle the abort action.

    Attributes
    ----------
    multitelescopes : MultiTelescopes
        The MultiTelescopes instance on which the action has to be performed.
    devices : devices
        The devices associated with the multiple telescopes.
    log : log
        Logging details of the operation.
    abort_action : Event
        An instance of Event to handle the abort action.

    Methods
    -------
    run()
        Starts the startup process in a separate thread.
    abort()
        Aborts the startup process.
    """
    
    def __init__(self,
                 multitelescopes,
                 abort_action : Event,
                 ):
        super().__init__()
        self.multitelescopes = multitelescopes
        self.abort_action = abort_action
        self.is_running = False
        self.succeeded = False
        self.failure_reason = ''

    def run(self,
            connect: bool = False,
            fanon : bool = True,
            home : bool = True, 
            slew : bool = True,    
            cool : bool = True):
        """
        Starts the startup process in a separate thread.
        """
        startup_thread = Thread(target=self._process, kwargs = dict(connect = connect, fanon = fanon, home = home, slew = slew, cool = cool))
        startup_thread.start()

    def abort(self):
        """
        Aborts the startup process.
        """
        self.abort_action.set()
        self.is_running = False
    
    def _process(self, connect = False, fanon = True, home = True, slew = True, cool = True):
        """
        Performs the necessary steps to startup the telescopes.

        Raises
        ------
        AbortionException
            If the abortion event is triggered during the startup process.
        """
        self.is_running = True
        self.multitelescopes.register_logfile()
        self.multitelescopes.update_statusfile(status = 'busy', do_trigger = True)
        self.multitelescopes.log.info(f'[{type(self).__name__}] is triggered.')
        try:
            # Connect
            if connect:
                params_connect = []
                for telescope_name, telescope in self.multitelescopes.devices.items():
                    params_connect.append(dict())

                multi_connect =MultiAction(array_telescope= self.multitelescopes.devices.values(), array_kwargs= params_connect, function = Connect, abort_action = self.abort_action)
                result_multi_connect = multi_connect.shared_memory

                ## Run
                try:
                    multi_connect.run()
                except AbortionException:
                    self.multitelescopes.log.warning(f'[{type(self).__name__}] is aborted.')

                ## Check result
                for tel_name, result in result_multi_connect.items():
                    is_succeeded = result_multi_connect[tel_name]['succeeded']
                    if not is_succeeded:
                        exc = result_multi_connect[tel_name].get('exception', 'unknown')
                        self.failure_reason += f'Connect[{tel_name}]:{exc}; '
                        self.multitelescopes.log_dict[tel_name].critical(f'[{type(self).__name__}] is failed: Connection failure.')
                        self.multitelescopes.remove(tel_name)

                ## Check len(devices) > 0
                if len(self.multitelescopes.devices) == 0:
                    raise ActionFailedException(f'[{type(self).__name__}] is Failed. Telescopes are not specified')

                ## Check abort_action
                if self.abort_action.is_set():
                    self.multitelescopes.log.warning(f'[{type(self).__name__}] is aborted.')
                    raise AbortionException(f'[{type(self).__name__}] is aborted.')

            if fanon:
                # Focuser fans on
                params_fanson = []
                for telescope_name, telescope in self.multitelescopes.devices.items():
                    params_fanson.append(dict())
                ##### MODIFICATION FOR 7DT02 FAN OFF
                #multitelescopes_except_unit2 = self.multitelescopes.devices.copy()

                #if '7DT02' in self.multitelescopes.devices.keys():
                #   multitelescopes_except_unit2 = self.multitelescopes.devices.copy()
                #   multitelescopes_except_unit2.pop('7DT02')
                #multi_fanson = MultiAction(array_telescope= multitelescopes_except_unit2.values(), array_kwargs= params_fanson[:-1], function = FansOn, abort_action = self.abort_action)
                multi_fanson = MultiAction(array_telescope= self.multitelescopes.devices.values(), array_kwargs= params_fanson, function = FansOn, abort_action = self.abort_action)
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
                        self.failure_reason += f'FansOn[{tel_name}]:{exc}; '
                        self.multitelescopes.log_dict[tel_name].critical(f'[{type(self).__name__}] is failed: Fans operation failure.')
                        self.multitelescopes.remove(tel_name)

                ## Check len(devices) > 0
                if len(self.multitelescopes.devices) == 0:
                    raise ActionFailedException(f'[{type(self).__name__}] is Failed. Telescopes are not specified')

                ## Check abort_action
                if self.abort_action.is_set():
                    self.multitelescopes.log.warning(f'[{type(self).__name__}] is aborted.')
                    raise AbortionException(f'[{type(self).__name__}] is aborted.')

            if home:
                # Telescope homing
                params_home = []
                for telescope_name, telescope in self.multitelescopes.devices.items():
                    params_home.append(dict())

                multi_home = MultiAction(array_telescope= self.multitelescopes.devices.values(), array_kwargs= params_home, function = Home, abort_action = self.abort_action)
                result_multi_home = multi_home.shared_memory

                ## Run
                try:
                    multi_home.run()
                    time.sleep(10)
                except AbortionException:
                    self.multitelescopes.log.warning(f'[{type(self).__name__}] is aborted.')

                ## Check result
                for tel_name, result in result_multi_home.items():
                    is_succeeded = result_multi_home[tel_name]['succeeded']
                    if not is_succeeded:
                        exc = result_multi_home[tel_name].get('exception', 'unknown')
                        self.failure_reason += f'Home[{tel_name}]:{exc}; '
                        self.multitelescopes.log_dict[tel_name].critical(f'[{type(self).__name__}] is failed: Homing failure.')
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
                    params_slew.append(dict(alt = self.config['STARTUP_ALT'],
                                            az = self.config['STARTUP_AZ']))

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

            if cool:
                # Camera cooling
                params_cool = []
                for telescope_name, telescope in self.multitelescopes.devices.items():
                    params_cool.append(dict(settemperature = self.config['STARTUP_CCDTEMP'],
                                            tolerance = self.config['STARTUP_CCDTEMP_TOLERANCE']))

                multi_cool = MultiAction(array_telescope= self.multitelescopes.devices.values(), array_kwargs= params_cool, function = Cool, abort_action = self.abort_action)
                result_multi_cool = multi_cool.shared_memory

                ## Run
                try:
                    multi_cool.run()
                except AbortionException:
                    self.multitelescopes.log.warning(f'[{type(self).__name__}] is aborted.')

                ## Check result
                for tel_name, result in result_multi_cool.items():
                    is_succeeded = result_multi_cool[tel_name]['succeeded']
                    if not is_succeeded:
                        exc = result_multi_cool[tel_name].get('exception', 'unknown')
                        self.failure_reason += f'Cool[{tel_name}]:{exc}; '
                        self.multitelescopes.log_dict[tel_name].critical(f'[{type(self).__name__}] is failed: Cooling failure.')
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
    S = Startup(M, abort_aciton)
    slack = SlackConnector(token_path= S.config['SLACK_TOKEN'], default_channel_id= S.config['SLACK_DEFAULT_CHANNEL'])
    obsnight = NightSession().obsnight_utc
    tonight_str = '%.4d-%.2d-%.2d'%(obsnight.sunrise_civil.datetime.year, obsnight.sunrise_civil.datetime.month, obsnight.sunrise_civil.datetime.day)
    message_ts = slack.get_message_ts(match_string = f'{S.config["SYSTEM_NAME"]} Observation on {tonight_str}')
    if message_ts:
        slack.post_thread_message(message_ts = message_ts, text = f'{type(S).__name__} is triggered: {time.strftime("%H:%M:%S", time.localtime())}')
    S.run(connect = False,
          fanon = True,                    
          home = True,
          slew = True,
          cool = True)
    while S.is_running:
        time.sleep(0.1)
    if message_ts:
        slack.post_thread_message(message_ts = message_ts, text = f'{type(S).__name__} is finished: {time.strftime("%H:%M:%S", time.localtime())}')

# %%
