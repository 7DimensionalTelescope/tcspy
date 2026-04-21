#%%
#%%
import numpy as np
import os
import json
import time
import astropy.units as u
from astropy.time import Time
from multiprocessing import Event
from multiprocessing import Manager

from tcspy.devices import SingleTelescope
from tcspy.devices import TelescopeStatus
from tcspy.interfaces import *
from tcspy.utils.error import *
from tcspy.utils.exception import *
from tcspy.utils.logger import mainLogger
from tcspy.configuration import mainConfig

from tcspy.action.level1 import ChangeFocus
from tcspy.action.level1 import ChangeFilter

#%%

class AutoFocus(Interface_Runnable, Interface_Abortable, mainConfig):
    """
    A class representing the autofocus action for a single telescope.

    Parameters
    ----------
    singletelescope : SingleTelescope
        An instance of SingleTelescope class representing an individual telescope to perform the autofocus action on.
    abort_action : Event
        An instance of the built-in Event class to handle the abort action. 

    Attributes
    ----------
    telescope : SingleTelescope
        The SingleTelescope instance on which the autofocus action has to be performed.
    telescope_status : TelescopeStatus
        A TelescopeStatus instance which is used to check the current status of the telescope.
    abort_action : Event
        An instance of Event to handle the abort action.

    Methods
    -------
    run(filter_: str, use_offset: bool)
        Performs the action of starting autofocus for the telescope.
    abort()
        Stops any autofocus action currently being carried out by the telescope.
    """
    
    def __init__(self, 
                 singletelescope : SingleTelescope,
                 abort_action : Event):
        super().__init__(singletelescope.unitnum)
        self.telescope = singletelescope
        self.telescope_status = TelescopeStatus(self.telescope)
        self.focus_history_file = os.path.join(self.config['AUTOFOCUS_FOCUSHISTORY_PATH'], self.tel_name, 'focus_history.json')
        self.abort_action = abort_action
        self.shared_memory_manager = Manager()
        self.shared_memory = self.shared_memory_manager.dict()
        self.shared_memory['succeeded'] = False
        self.shared_memory['exception'] = None
        self.shared_memory['is_running'] = False
        self.is_running = False

    def run(self,
            filter_ : str = None,
            use_offset : bool = True,
            use_history : bool = False,
            history_duration : float = 60,
            search_focus_when_failed : bool = False,
            search_focus_range : int = 2000):
        """
        Performs the action of starting autofocus for the telescope.

        Parameters
        ----------
        filter_ : str
            The name of the filter to use during autofocus.
        use_offset : bool
            Whether or not to use offset during autofocus.

        Raises
        ------
        ConnectionException:
            If the required devices are disconnected.
        AbortionException:
            If the action is aborted during execution.
        ActionFailedException:
            If the autofocus process fails.
        """
        self.telescope.register_logfile()
        self.telescope.log.info(f'==========LV2[{type(self).__name__}] is triggered.')
        self.is_running = True
        self.shared_memory['is_running'] = True
        self.shared_memory['succeeded'] = False
        
        # Check device status
        status_camera = self.telescope_status.camera
        status_focuser = self.telescope_status.focuser
        status_mount = self.telescope_status.mount
        status_filterwheel = self.telescope_status.filterwheel
        trigger_abort_disconnected = False
        if status_camera.lower() == 'disconnected':
            trigger_abort_disconnected = True
            self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: camera is disconnected.')
        if status_focuser.lower() == 'disconnected':
            trigger_abort_disconnected = True
            self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: filterwheel is disconnected.')
        if status_mount.lower() == 'disconnected':
            trigger_abort_disconnected = True
            self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: mount is disconnected.')
        if status_filterwheel.lower() == 'disconnected':
            trigger_abort_disconnected = True
            self.telescope.log.critical(f'Filterwheel is disconnected. Action "{type(self).__name__}" is not triggered')
        if trigger_abort_disconnected:
            self.shared_memory['exception'] = 'ConnectionException'
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise ConnectionException(f'==========LV2[{type(self).__name__}] is failed: devices are disconnected.')
        
        # Abort action when triggered
        if self.abort_action.is_set():
            self.telescope.log.warning(f'==========LV2[{type(self).__name__}] is aborted.')
            self.shared_memory['exception'] = 'AbortionException'
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise AbortionException(f'[{type(self).__name__}] is aborted.') 
           
        # Define action
        action_changefocus = ChangeFocus(singletelescope = self.telescope, abort_action = self.abort_action)
        action_changefilter = ChangeFilter(singletelescope = self.telescope, abort_action = self.abort_action)
        
        if filter_ == None:
            info_filterwheel = self.telescope.filterwheel.get_status()
            filter_ = info_filterwheel['filter_']
        focus_history = self.history[filter_]
        
        # Apply focus offset
        if use_offset:
            info_filterwheel = self.telescope.filterwheel.get_status()
            current_filter = info_filterwheel['filter_']
            if not current_filter == filter_:
                offset = self.telescope.filterwheel.get_offset_from_currentfilt(filter_ = filter_)
                self.telescope.log.info(f'[{type(self).__name__}] Focuser is moving with the offset of {offset}[{current_filter} >>> {filter_}]')
                try:
                    result_changefocus = action_changefocus.run(position = offset, is_relative= True)
                except ConnectionException:
                    self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: Focuser is disconnected.')
                    self.shared_memory['exception'] = 'ConnectionException'
                    self.shared_memory['is_running'] = False
                    self.is_running = False                    
                    raise ConnectionException(f'[{type(self).__name__}] is failed: Focuser is disconnected.')
                except AbortionException:
                    while action_changefocus.shared_memory['is_running']:
                        time.sleep(0.1)
                    self.telescope.log.warning(f'==========LV2[{type(self).__name__}] is aborted.')
                    self.shared_memory['exception'] = 'AbortionException'
                    self.shared_memory['is_running'] = False
                    self.is_running = False
                    raise AbortionException(f'[{type(self).__name__}] is aborted: Focuser movement is aborted.')
                except ActionFailedException:
                    self.telescope.log.critical(f'========LV2[{type(self).__name__}] is failed: Focuser movement failure.')
                    self.shared_memory['exception'] = 'ActionFailedException'
                    self.shared_memory['is_running'] = False
                    self.is_running = False
                    raise ActionFailedException(f'[{type(self).__name__}] is failed: Focuser movement failure.')
            
        # Change filter
        info_filterwheel = self.telescope.filterwheel.get_status()
        current_filter = info_filterwheel['filter_']
        if not current_filter == filter_:
            try:
                self.action = action_changefilter
                result_filterchange = action_changefilter.run(filter_ = filter_)
            except ConnectionException:
                self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: Filterwheel is disconnected.')           
                self.shared_memory['exception'] = 'ConnectionException'     
                self.shared_memory['is_running'] = False
                self.is_running = False
                raise ConnectionException(f'[{type(self).__name__}] is failed: Filterwheel is disconnected.')                
            except AbortionException:
                while action_changefilter.shared_memory['is_running']:
                    time.sleep(0.1)
                self.telescope.log.warning(f'==========LV2[{type(self).__name__}] is aborted.')
                self.shared_memory['exception'] = 'AbortionException'
                self.shared_memory['is_running'] = False
                self.is_running = False
                raise AbortionException(f'[{type(self).__name__}] is aborted: Filterwheel movement is aborted.')
            except ActionFailedException:
                self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: Filterwheel movement failure.')
                self.shared_memory['exception'] = 'ActionFailedException'
                self.shared_memory['is_running'] = False
                self.is_running = False
                raise ActionFailedException(f'[{type(self).__name__}] is failed: Filterwheel movement failure.')
        
        # run Autofocus
        result_autofocus = False
        info_focuser = self.telescope.focuser.get_status()
        optimal_position = info_focuser['position']
        self.telescope.log.info(f'[{type(self).__name__}] Start autofocus [Central focus position: {info_focuser["position"]}, filter: {filter_}]')
        try:
            # If use_history == False, run Autofocus
            if not use_history:
                result_autofocus, autofocus_position, autofocus_error = self.telescope.focuser.autofocus_start(abort_action = self.abort_action)
            # Else: use focus history value. In this case, do not run Autofocus
            else:    
                if focus_history['succeeded']:
                    optimal_position = focus_history['focusval']
                    now = Time.now()
                    elapsed_time = now - Time(focus_history['update_time'])
                    if elapsed_time < (history_duration * u.minute):
                        self.action = action_changefocus
                        result_changefocus = action_changefocus.run(position = focus_history['focusval'], is_relative = False)
                        self.telescope.log.info(f'[{type(self).__name__}] Focus history is applied. Elapsed time : {round(elapsed_time.value*1440,1)}min')
                        self.shared_memory['succeeded'] = True
                        self.shared_memory['is_running'] = False
                        self.is_running = False
                        self.telescope.log.info(f'==========LV2[{type(self).__name__}] is finished')
                        return True
                    else:
                        result_autofocus, autofocus_position, autofocus_error = self.telescope.focuser.autofocus_start(abort_action = self.abort_action)                
                else:
                    result_autofocus, autofocus_position, autofocus_error = self.telescope.focuser.autofocus_start(abort_action = self.abort_action)                
        except AbortionException:
            self.telescope.log.warning(f'==========LV2[{type(self).__name__}] is aborted.')
            self.shared_memory['exception'] = 'AbortionException'
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise AbortionException(f'[{type(self).__name__}] is aborted.') 
        except AutofocusFailedException:
            self.telescope.log.warning(f'[{type(self).__name__}] Autofocus 1st try failed. Try autofocus with the focus history')
            
        # When succeeded
        if result_autofocus:
            self.update_focus_history(filter_ = filter_, focusval =autofocus_position, is_succeeded = result_autofocus)
            self.telescope.log.info(f'==========LV2[{type(self).__name__}] is finished')
            self.shared_memory['succeeded'] = True
            self.shared_memory['is_running'] = False
            self.is_running = False
            return True
        
        # If autofocus process is failed, try autofocus again with the focus value in the history 
        elif focus_history['succeeded']:
            now = Time.now()
            elapsed_time = now - Time(focus_history['update_time'])
            try:
                self.action = action_changefocus
                result_changefocus = action_changefocus.run(position = focus_history['focusval'], is_relative = False)
            except ConnectionException:
                self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: Focuser is disconnected.')    
                self.shared_memory['exception'] = 'ConnectionException'            
                self.shared_memory['is_running'] = False
                self.is_running = False
                raise ConnectionException(f'[{type(self).__name__}] is failed: Focuser is disconnected.')                
            except AbortionException:
                while action_changefocus.shared_memory['is_running']:
                    time.sleep(0.1)
                self.telescope.log.warning(f'==========LV2[{type(self).__name__}] is aborted.')
                self.shared_memory['exception'] = 'AbortionException'
                self.shared_memory['is_running'] = False
                self.is_running = False
                raise AbortionException(f'[{type(self).__name__}] is aborted: Focuser movement is aborted.')
            except ActionFailedException:
                self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: Focuser movement failure.')
                self.shared_memory['exception'] = 'ActionFailedException'
                self.shared_memory['is_running'] = False
                self.is_running = False
                raise ActionFailedException(f'[{type(self).__name__}] is failed: Focuser movement failure.')
            self.telescope.log.info(f'[{type(self).__name__}]Focus history is applied. Elapsed time : {round(elapsed_time.value*1440,1)}min')
            
            try: 
                result_autofocus, autofocus_position, autofocus_error = self.telescope.focuser.autofocus_start(abort_action = self.abort_action)
                # When succeeded
                if result_autofocus:
                    self.update_focus_history(filter_ = filter_, focusval =autofocus_position, is_succeeded = result_autofocus)
                    self.telescope.log.info(f'==========LV2[{type(self).__name__}] is finished')
                    self.shared_memory['succeeded'] = True
                    self.shared_memory['is_running'] = False
                    self.is_running = False
                    return True
            except AbortionException:
                self.telescope.focuser.wait_idle()
                self.telescope.log.warning(f'==========LV2[{type(self).__name__}] is aborted.')
                self.shared_memory['exception'] = 'AbortionException'
                self.shared_memory['is_running'] = False
                self.is_running = False
                raise AbortionException(f'[{type(self).__name__}] is aborted.') 
 
            except AutofocusFailedException:
                self.telescope.log.warning(f'[{type(self).__name__}] Autofocus 2nd try failed. Search focus with the range of {search_focus_range}.')

        # If autofocus process is still failed, grid search
        if search_focus_when_failed:
            relative_position = 500
            n_focus_search = 2*search_focus_range//relative_position
            sign = 1
            for i in range(n_focus_search):
                print(relative_position)
                # Change focus 
                try:
                    self.action = action_changefocus
                    action_changefocus.run(position = relative_position, is_relative = True)
                except ConnectionException:
                    self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: Focuser is disconnected.')    
                    self.shared_memory['exception'] = 'ConnectionException'            
                    self.shared_memory['is_running'] = False
                    self.is_running = False
                    raise ConnectionException(f'[{type(self).__name__}] is failed: Focuser is disconnected.')                
                except AbortionException:
                    while action_changefocus.shared_memory['is_running']:
                        time.sleep(0.1)
                    self.telescope.log.warning(f'==========LV2[{type(self).__name__}] is aborted.')
                    self.shared_memory['exception'] = 'AbortionException'
                    self.shared_memory['is_running'] = False
                    self.is_running = False
                    raise AbortionException(f'[{type(self).__name__}] is aborted: Focuser movement is aborted.')
                except ActionFailedException:
                    self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: Focuser movement failure.')
                    self.shared_memory['exception'] = 'ActionFailedException'
                    self.shared_memory['is_running'] = False
                    self.is_running = False
                    raise ActionFailedException(f'[{type(self).__name__}] is failed: Focuser movement failure.')
                
                # Autofocus
                try: 
                    result_autofocus, autofocus_position, autofocus_error = self.telescope.focuser.autofocus_start(abort_action = self.abort_action)
                    # When succeeded
                    if result_autofocus:
                        self.update_focus_history(filter_ = filter_, focusval =autofocus_position, is_succeeded = result_autofocus)
                        self.telescope.log.info(f'==========LV2[{type(self).__name__}] is finished')
                        self.shared_memory['succeeded'] = True
                        self.shared_memory['is_running'] = False
                        self.is_running = False
                        return True
                except AbortionException:
                    self.telescope.focuser.wait_idle()
                    self.telescope.log.warning(f'==========LV2[{type(self).__name__}] is aborted.')
                    self.shared_memory['exception'] = 'AbortionException'
                    self.shared_memory['is_running'] = False
                    self.is_running = False
                    raise AbortionException(f'[{type(self).__name__}] is aborted.') 
                except AutofocusFailedException:
                    self.telescope.log.warning(f'[{type(self).__name__}] Autofocus {i+3}th try failed.')

                relative_position = np.abs(relative_position) + 500
                sign *= -1
                relative_position *= sign

        # If autofocus process is still failed, return ActionFailedException
        try:
            self.action = action_changefocus
            action_changefocus.run(position = optimal_position, is_relative = False)
            self.telescope.log.warning(f'==========LV2[{type(self).__name__}] Autofocus process is failed. Return to the original position')
        except ConnectionException:
            self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: Focuser is disconnected.')       
            self.shared_memory['exception'] = 'ConnectionException'         
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise ConnectionException(f'[{type(self).__name__}] is failed: Focuser is disconnected.')                
        except AbortionException:
            while action_changefocus.shared_memory['is_running']:
                time.sleep(0.1)
            self.telescope.log.warning(f'==========LV2[{type(self).__name__}] is aborted.')
            self.shared_memory['exception'] = 'AbortionException'
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise AbortionException(f'[{type(self).__name__}] is aborted: Focuser movement is aborted.')
        except ActionFailedException:
            self.telescope.log.critical(f'==========LV2[{type(self).__name__}] is failed: Focuser movement failure.')
            self.shared_memory['exception'] = 'ActionFailedException'
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise ActionFailedException(f'[{type(self).__name__}] is failed: Focuser movement failure.')
        self.is_running = False

    def write_default_focus_history(self):
        with open(self.config['AUTOFOCUS_FILTINFO_FILE'], 'r') as f:
            filtinfo = json.load(f)
        default_focus_history_filter = dict(zip(['update_time', 'succeeded', 'focusval'], [Time('2000-01-01').isot, False, 10000]))
        focus_history_default = dict()
        tel_name = self.telescope.tel_name
        filt_list = filtinfo[tel_name]
        focus_history_telescope = dict()
        for filt_name in filt_list:
            focus_history_telescope[filt_name] = default_focus_history_filter
        focus_history_default[tel_name] = focus_history_telescope
        with open(self.focus_history_file, 'w') as f:
            json.dump(focus_history_default, f, indent=4)

    def update_focus_history(self, filter_ : str, focusval : float, is_succeeded : bool):
        if not os.path.isfile(self.focus_history_file):
            print('No focus_hostory file exists. Default format is generated.')
            self.write_default_focus_history()
        with open(self.focus_history_file, 'r') as f:
            focus_history_data = json.load(f)
        focus_history_data[self.telescope.tel_name][filter_]['update_time'] = Time.now().isot
        focus_history_data[self.telescope.tel_name][filter_]['succeeded'] = is_succeeded
        focus_history_data[self.telescope.tel_name][filter_]['focusval'] = focusval
        with open(self.focus_history_file, 'w') as f:
            json.dump(focus_history_data, f, indent=4)
    
    @property
    def history(self):
        if not os.path.isfile(self.focus_history_file):
            print('No focus_hostory file exists. Default format is generated.')
            self.write_default_focus_history()
        with open(self.focus_history_file, 'r') as f:
            focus_history_data = json.load(f)
        return focus_history_data[self.telescope.tel_name]
    
    def abort(self):
        self.telescope.register_logfile()
        self.abort_action.set()
        while self.shared_memory['is_running']:
            time.sleep(0.1)
        self.telescope.log.warning(f'==========LV2[{type(self).__name__}] is aborted.')
        self.shared_memory['exception'] = 'AbortionException'
        self.shared_memory['is_running'] = False
        self.is_running = False
        raise AbortionException(f'[{type(self).__name__}] is aborted.')
# %%
if __name__ == '__main__':
    self = AutoFocus(SingleTelescope(36), Event())
    self.run()
# %%
