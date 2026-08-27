#%%
from multiprocessing import Event
from multiprocessing import Manager
from threading import Thread
import time
import os
import glob
import numpy as np
from astropy.io import fits
from astropy.time import Time
import astropy.units as u

from tcspy.configuration import mainConfig
from tcspy.devices import MultiTelescopes
from tcspy.devices import SingleTelescope

from tcspy.utils.exception import *
from tcspy.action import MultiAction
from tcspy.action.level1 import Exposure
from tcspy.action.level2 import AutoFlat
from tcspy.action.level1 import SlewAltAz

from tcspy.devices import multitelescopes
#%%

class FilterCheck(mainConfig):

    def __init__(self,
                 multitelescopes : MultiTelescopes,
                 abort_action : Event,
                 ):
        super().__init__()
        self.multitelescopes = multitelescopes
        self.abort_action = abort_action
        self.is_running = False
        
    def run(self, exptime : int  = 1):
        """
        Starts the startup process in a separate thread and waits for the result.
        """
        startup_thread = Thread(target=self._process, kwargs = dict(exptime = exptime))
        startup_thread.start()
        startup_thread.join()  # Wait for the thread to complete
        return self.result  # Return the result after completion
        
        
    def abort(self):
        """
        Aborts the startup process.
        """
        self.is_running = False
        self.abort_action.set()
        self.multitelescopes.log.warning(f'[{type(self).__name__}] is aborted.')  
        raise AbortionException(f'[{type(self).__name__}] is aborted.')  
    
    def _process(self, exptime : int = 1):
        self.is_running = True
        self.multitelescopes.register_logfile()
        self.multitelescopes.update_statusfile(status = 'busy', do_trigger = True)
        self.multitelescopes.log.info(f'[{type(self).__name__}] is triggered.')
        
        #Prepare for MultiAction for Slew
        params_slew_all = []
        
        for telescope_name, telescope in self.multitelescopes.devices.items():
            params_slew = dict(alt = 80, az = 300) 
            params_slew_all.append(params_slew)
        self.multiaction = MultiAction(array_telescope= self.multitelescopes.devices.values(), array_kwargs= params_slew_all, function = SlewAltAz, abort_action = self.abort_action)    
        self.shared_memory = self.multiaction.shared_memory
        
        # Slew
        try:
            self.multiaction.run()
        except AbortionException:
            self.abort()
        except ActionFailedException:
            for tel_name, result in self.shared_memory.items():
                is_succeeded = self.shared_memory[tel_name]['succeeded']
                if is_succeeded:
                    self.multitelescopes.log_dict[tel_name].info(f'[{type(self).__name__}] is finished')
                else:
                    self.multitelescopes.log_dict[tel_name].info(f'[{type(self).__name__}] is failed')
            self.multitelescopes.log.critical(f'[{type(self).__name__}] is failed.')
            self.is_running = False
            raise ActionFailedException(f'[{type(self).__name__}] is failed.')    

        filterset = ['g','r','i']
        expset = [exptime] * len(filterset)
        skylevel_dict = {}
        for filter_, exptime in zip(filterset, expset):
            skylevel_dict[filter_] = {}
            #Prepare for MultiAction for Exposure
            params_exposure_all = []
            for telescope_name, telescope in self.multitelescopes.devices.items():
                params_exposure = dict(frame_number = 0, exptime = exptime, filter_ = filter_, gain = 0, alt = 40, az = 300, name = 'filtercheck', objtype = 'test')
                params_exposure_all.append(params_exposure)
            self.multiaction = MultiAction(array_telescope= self.multitelescopes.devices.values(), array_kwargs= params_exposure_all, function = Exposure, abort_action = self.abort_action)
            self.shared_memory = self.multiaction.shared_memory
            
            # Exposure
            try:
                folder_key = (Time.now() - 12 * u.hour).datetime.strftime('%Y-%m-%d*')
                self.multiaction.run()
            except AbortionException:
                self.abort()
            except ActionFailedException:
                for tel_name, result in self.shared_memory.items():
                    is_succeeded = self.shared_memory[tel_name]['succeeded']
                    if is_succeeded:
                        self.multitelescopes.log_dict[tel_name].info(f'[{type(self).__name__}] is finished')
                    else:
                        self.multitelescopes.log_dict[tel_name].info(f'[{type(self).__name__}] is failed')
                self.multitelescopes.log.critical(f'[{type(self).__name__}] is failed.')
                self.is_running = False
                raise ActionFailedException(f'[{type(self).__name__}] is failed.')    
            
            # Get the image count for each telescope
            for telescope_name, telescope in self.multitelescopes.devices.items():
                key = os.path.join(telescope.config['IMAGE_PATH'], folder_key, '*filtercheck*.fits')
                fits_file = glob.glob(key)
                header_key = os.path.join(telescope.config['IMAGE_PATH'], folder_key, '*filtercheck*.head')
                header_file = glob.glob(header_key)
                data = fits.getdata(fits_file[0])
                mean = int(np.mean(data))
                print(f'{telescope_name} : {mean}')
                os.remove(fits_file[0])
                os.remove(header_file[0])                
                skylevel_dict[filter_][telescope_name] = mean
                if os.listdir(os.path.dirname(fits_file[0])) == []:
                    os.rmdir(os.path.dirname(fits_file[0]))
        
        all_problematic_units = np.array([])
        for filter_, skylevel_info in skylevel_dict.items():
            telnames = list(skylevel_info.keys())
            skylevels = list(skylevel_info.values())
            std = np.std(skylevels)
            idx = np.where(np.abs(np.array(skylevels) - np.mean(skylevels)) > 5 * std)
            problem_units = np.array(telnames)[idx]
            if problem_units.size > 0:
                self.multitelescopes.log.critical(f'{filter_} band level is wired for the units: {problem_units}')
                self.multitelescopes.log.critical(f'SKYLEVEL = {skylevel_dict[filter_]}')
            all_problematic_units = np.concatenate((all_problematic_units, problem_units))
        final_problematic_units = set(all_problematic_units)
        
        self.multitelescopes.log.info(f'[{type(self).__name__}] is finished.')
        self.multitelescopes.update_statusfile(status = 'idle', do_trigger = True)
        self.is_running = False
        self.result = skylevel_dict, problem_units
        return skylevel_dict, final_problematic_units


# %%
if __name__ == '__main__':
    
    from tcspy.devices import MultiTelescopes
    from tcspy.utils.connector import SlackConnector
    from tcspy.utils import NightSession
    multitelescopes = MultiTelescopes()
    abort_action = Event()
    application = FilterCheck(multitelescopes, abort_action)
    slack = SlackConnector(token_path= application.config['SLACK_TOKEN'], default_channel_id= application.config['SLACK_DEFAULT_CHANNEL'])
    obsnight = NightSession(Time.now()).obsnight_utc
    tonight_str = '%.4d-%.2d-%.2d'%(obsnight.sunrise_civil.datetime.year, obsnight.sunrise_civil.datetime.month, obsnight.sunrise_civil.datetime.day)
    #message_ts = None
    message_ts = slack.get_message_ts(match_string = f'{application.config["SYSTEM_NAME"]} Observation on {tonight_str}')
    if message_ts:
        slack.post_thread_message(message_ts,f'{type(application).__name__} is triggered: {time.strftime("%H:%M:%S", time.localtime())}')
    result= application.run(exptime = 100)
    while application.is_running:
        time.sleep(0.1)
    if message_ts:
        slack.post_thread_message(message_ts,f'{type(application).__name__} is finished: {time.strftime("%H:%M:%S", time.localtime())}')
    if message_ts:
        slack.post_thread_message(message_ts,f'{type(application).__name__} is finished: {time.strftime("%H:%M:%S", time.localtime())}')
        skylevel_str = '\n'.join([f'*{band}*: ' + ', '.join([f'{telescope}: {value} \n' for telescope, value in telescopes.items()])
                                for band, telescopes in result[0].items()])
        slack.post_thread_message(message_ts, f'Skylevel:\n{skylevel_str}')

# %%
