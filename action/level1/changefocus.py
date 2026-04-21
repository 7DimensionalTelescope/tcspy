#%%
from multiprocessing import Event
from multiprocessing import Manager

from tcspy.devices import SingleTelescope
from tcspy.devices import TelescopeStatus
from tcspy.interfaces import *
from tcspy.utils.logger import mainLogger
from tcspy.utils.exception import *
#%%
class ChangeFocus(Interface_Runnable, Interface_Abortable):
    """
    A class representing a change focus action for a single telescope.

    Parameters
    ----------
    singletelescope : SingleTelescope
        An instance of SingleTelescope class representing an individual telescope to perform the action on.
    abort_action : Event
        An instance of the built-in Event class to handle the abort action. 

    Attributes
    ----------
    telescope : SingleTelescope
        The SingleTelescope instance on which the action has to performed.
    telescope_status : TelescopeStatus
        A TelescopeStatus instance which is used to check the current status of the telescope.
    abort_action : Event
        An instance of Event to handle the abort action.

    Methods
    -------
    run(position: int = None, is_relative : bool = False)
        Performs the action to change the focus of the telescope. 
        A position can be specified if an absolute change in focus is desired. 
        Use is_relative flag for relative changes in focus.
    abort()
        A function that aborts the focus changing action if the focuser is busy.
    """
    
    def __init__(self, 
                 singletelescope : SingleTelescope,
                 abort_action : Event):
        self.telescope = singletelescope
        self.telescope_status = TelescopeStatus(self.telescope)
        self.abort_action = abort_action
        self.shared_memory_manager = Manager()
        self.shared_memory = self.shared_memory_manager.dict()
        self.shared_memory['succeeded'] = False
        self.shared_memory['exception'] = None
        self.shared_memory['is_running'] = False
        self.is_running = False

    def run(self,
            position: int = None,
            is_relative : bool = False):
        """
        Excute the focus change.
        
        Parameters
        ----------
        position : int, optional
            The new focus position.
        is_relative : bool, optional
            If set to True, considers the position as a relative change. 
            If False, considers position as an absolute position. 
            Default is False.
            
        Returns
        -------
        bool
            True if the focus change action is successful, otherwise an exception is raised.

        Raises
        ------
        ConnectionException
            If the focuser of the telescope is disconnected.
        AbortionException
            If the action has been aborted.
        ActionFailedException
            If action fails due to any other reason.
        """
        self.telescope.register_logfile()
        self.telescope.log.info(f'=====LV1[{type(self).__name__}] is triggered.')
        self.is_running = True
        self.shared_memory['is_running'] = True
        self.shared_memory['succeeded'] = False
        
        # Check device connection
        if self.telescope_status.focuser.lower() == 'disconnected':
            
            self.telescope.log.critical(f'=====LV1[{type(self).__name__}] is failed: focuser is disconnected.')
            self.shared_memory['exception'] = 'ConnectionException'
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise ConnectionException(f'[{type(self).__name__}] is failed: focuser is disconnected.')
        
        # If not aborted, execute the action
        if self.abort_action.is_set():
            self.telescope.log.warning(f'=====LV1[{type(self).__name__}] is aborted.')
            self.telescope.focuser.wait_idle()
            self.shared_memory['exception'] = 'AbortionException'
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise AbortionException(f'[{type(self).__name__}] is aborted.')
                 
        # Start action
        if self.telescope_status.focuser.lower() == 'idle':
            try:
                info_focuser = self.telescope.focuser.get_status()
                if is_relative:
                    position = info_focuser['position'] + position
                result_move = self.telescope.focuser.move(position = position, abort_action= self.abort_action)
            except FocusChangeFailedException:
                self.telescope.log.critical(f'=====LV1[{type(self).__name__}] is failed: focuser move failure.')
                self.shared_memory['exception'] = 'ActionFailedException'
                self.shared_memory['is_running'] = False
                self.is_running = False
                raise ActionFailedException(f'[{type(self).__name__}] is failed: focuser move failure.')            
            except AbortionException:
                self.telescope.focuser.wait_idle()
                self.telescope.log.warning(f'=====LV1[{type(self).__name__}] is aborted.')
                self.shared_memory['exception'] = 'AbortionException'
                self.shared_memory['is_running'] = False
                self.is_running = False
                raise AbortionException(f'[{type(self).__name__}] is aborted.')
        elif self.telescope_status.focuser.lower() == 'busy':
            self.telescope.log.critical(f'=====LV1[{type(self).__name__}] is failed: focuser is busy.')
            self.shared_memory['exception'] = 'ActionFailedException'
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise ActionFailedException(f'[{type(self).__name__}] is failed: focuser is busy.')
        else:
            self.telescope.log.critical(f'=====LV1[{type(self).__name__}] is failed: focuser status error.')
            self.shared_memory['exception'] = 'ActionFailedException'
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise ActionFailedException(f'[{type(self).__name__}] is failed: focuser status error.')
        
        self.telescope.log.info(f'=====LV1[{type(self).__name__}] is finished.')
        self.shared_memory['succeeded'] = True
        self.shared_memory['is_running'] = False
        self.is_running = False
        return True
            
    def abort(self):
        self.telescope.register_logfile()
        self.abort_action.set()
        self.telescope.focuser.wait_idle()
        self.telescope.log.warning(f'=====LV1[{type(self).__name__}] is aborted.')
        self.shared_memory['exception'] = 'AbortionException'
        self.shared_memory['is_running'] = False
        self.is_running = False
        raise AbortionException(f'[{type(self).__name__}] is aborted.')
# %%
if __name__ == '__main__':
    from tcspy.devices import SingleTelescope
    from multiprocessing import Event
    tel = SingleTelescope(36)
    abort_action = Event()
    self= ChangeFocus(tel, abort_action)
# %%