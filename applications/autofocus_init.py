#%%
from tcspy.configuration import mainConfig
from tcspy.action.level2 import AutoFocus
from tcspy.action import MultiAction
from tcspy.action.level1 import SlewAltAz
from tcspy.devices import SingleTelescope, MultiTelescopes
from multiprocessing import Event
from threading import Thread
from tcspy.utils.exception import *
import json, os
#%%

class AutofocusInitializer(mainConfig):
    
    def __init__(self,
                 multitelescopes : MultiTelescopes,
                 abort_action : Event,
                 ):
        super().__init__()
        self.multitelescopes = multitelescopes
        self.abort_action = abort_action
        self.filtinfo = self._get_filtinfo()
        self.is_running = False
    
    def run(self,
            filter_ : str = 'r',
            use_offset : bool = True,
            use_history : bool = False, 
            history_duration : float = 60,
            search_focus_when_failed : bool = True, 
            search_focus_range : int = 3000,
            slew : bool = True):
        startup_thread = Thread(target=self._process, kwargs = dict(filter_ = filter_, use_offset = use_offset, use_history = use_history, history_duration = history_duration, search_focus_when_failed = search_focus_when_failed, search_focus_range = search_focus_range, slew = slew))
        startup_thread.start()
    
    def abort(self):
        self.abort_action.set()
        
    def _get_filtinfo(self):
        with open(self.config['AUTOFOCUS_FILTINFO_FILE'], 'r') as f:
            filtinfo_all = json.load(f)
        filtinfo = {key : filtinfo_all[key] for key in self.multitelescopes.devices.keys()}
        return filtinfo

    def _get_specmode(self, specmode : str):
        specmode_file = self.config['SPECMODE_FOLDER'] + f'{specmode}.specmode'
        is_exist_specmodefile = os.path.isfile(specmode_file)
        if is_exist_specmodefile: 
            with open(specmode_file, 'r') as f:
                specmode_dict = json.load(f)
            return specmode_dict
        else:
            return None
       
    def _process(self,
                 filter_ : str = 'r',
                 use_offset : bool = True,
                 use_history : bool = True, 
                 history_duration : float = 60,
                 search_focus_when_failed : bool = True, 
                 search_focus_range : int = 3000,
                 slew : bool = True):
        
        self.is_running = True
        self.multitelescopes.register_logfile()
        self.multitelescopes.log.info(f'[{type(self).__name__}] is triggered.')
        self.multitelescopes.update_statusfile(status = 'busy', do_trigger = True)

        # Slew 
        if slew:
            alt = 50
            az = 160
            tracking= True
            action_slew = MultiAction(self.multitelescopes.devices.values(), dict(alt = alt, az = az, tracking = tracking), SlewAltAz, Event())
            try:
                action_slew.run()
            except ConnectionException:
                self.multitelescopes.log.critical(f'[{type(self).__name__}] is failed.')
                self.is_running = False
                raise ConnectionException(f'[{type(self).__name__}] is failed.')
            except AbortionException:
                self.multitelescopes.log.warning(f'[{type(self).__name__}] is aborted.')
                self.is_running = False
                raise AbortionException(f'[{type(self).__name__}] is aborted.')
            except ActionFailedException:
                self.multitelescopes.log.critical(f'[{type(self).__name__}] is failed')
                self.is_running = False
                raise ActionFailedException(f'[{type(self).__name__}] is failed.')
        
        autofocus_filtinfo = self._get_specmode(filter_)
        if autofocus_filtinfo is None:
            autofocus_filtinfo = {tel_name : [filter_] for tel_name in self.multitelescopes.devices.keys()}

        # Run Autofocus
        max_length = max(len(lst) for lst in autofocus_filtinfo.values())
        # Extend each list to the maximum length by repeating its elements
        for key, lst in autofocus_filtinfo.items():
            if len(lst) < max_length:
                repeat_times = (max_length // len(lst)) + 1  # Determine how many times to repeat the list
                extended_list = (lst * repeat_times)[:max_length]  # Repeat and slice to the maximum length
                autofocus_filtinfo[key] = extended_list
        
        for idx_filter in range(max_length):
            kwargs_autofocus_all = []
            for tel_name in self.multitelescopes.devices.keys():
                filter_ = autofocus_filtinfo[tel_name][idx_filter]
                kwargs_autofocus_single = dict(filter_ = filter_, use_offset = use_offset, use_history = use_history, history_duration = history_duration, search_focus_when_failed = search_focus_when_failed, search_focus_range = search_focus_range)
                kwargs_autofocus_all.append(kwargs_autofocus_single)
            action_autofocus = MultiAction(self.multitelescopes.devices.values(), kwargs_autofocus_all, AutoFocus, self.abort_action)
            try:
                action_autofocus.run()
            except AbortionException:
                self.multitelescopes.log.warning(f'[{type(self).__name__}] is aborted.')
                self.is_running = False
                raise AbortionException(f'[{type(self).__name__}] is aborted.')
        self.multitelescopes.log.info(f'[{type(self).__name__}] is finished.')
        self.is_running = False
        self.multitelescopes.update_statusfile(status = 'idle', do_trigger = True)


#%%  
if __name__ == '__main__':
    M = MultiTelescopes([SingleTelescope(36)])
    AutofocusInitializer(M, Event()).run(filter_ = 'r',
                                         use_offset = False,
                                         use_history = False, 
                                         history_duration = 60,
                                         search_focus_when_failed = False, 
                                         search_focus_range = 200,
                                         slew = True) 
# %%
