#%%
from multiprocessing import Event
from multiprocessing import Manager

from tcspy.devices import SingleTelescope
from tcspy.devices import TelescopeStatus
from tcspy.interfaces import *
from tcspy.utils.logger import mainLogger
from tcspy.utils.exception import *

class ChangeFilter(Interface_Runnable, Interface_Abortable):
    """
    A class representing a change filter action for a single telescope.

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
    run(filter_ : str)
        Performs the action to change the filter of the telescope. It does so by attempting to move the filter to a new state.
    abort()
        A function that needs to be defined to enable abort functionality. In this class, it does nothing and should be overridden in subclasses if needed.
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
            filter_ : str):
        """
        Performs the action to change the filter of the telescope.

        Parameters
        ----------
        filter_ : str
            The new filter state to which the telescope's filter wheel needs to be moved.

        Returns
        -------
        bool
            True if the action is successful, otherwise an exception is raised.
        
        Raises
        ------
        ConnectionException
            If the filter wheel of the telescope is disconnected. 
        AbortionException
            If the action has been aborted.
        ActionFailedException
            If the action fails due to any other reason.
        """
        self.telescope.register_logfile()
        self.telescope.log.info(f'=====LV1[{type(self).__name__}] is triggered.')
        self.is_running = True
        self.shared_memory['is_running'] = True
        self.shared_memory['succeeded'] = False
        # Check device connection
        if self.telescope_status.filterwheel.lower() == 'disconnected':
            self.telescope.log.critical(f'=====LV1[{type(self).__name__}] is failed: filterwheel is disconnected.')
            self.shared_memory['exception'] = 'ConnectionException'
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise ConnectionException(f'[{type(self).__name__}] is failed: filterwheel is disconnected.')
        
        # If not aborted, execute the action
        if self.abort_action.is_set():
            self.telescope.filterwheel.wait_idle()
            self.telescope.log.warning(f'=====LV1[{type(self).__name__}] is aborted.')
            self.shared_memory['exception'] = 'AbortionException'
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise AbortionException(f'[{type(self).__name__}] is aborted.') 
               
        # Start action
        if self.telescope_status.filterwheel.lower() == 'idle':
            try:
                result_move = self.telescope.filterwheel.move(filter_ = filter_)
            except FilterChangeFailedException:
                self.telescope.log.critical(f'=====LV1[{type(self).__name__}] is failed: filterwheel move failure.')
                self.shared_memory['exception'] = 'ActionFailedException'
                self.shared_memory['is_running'] = False    
                self.is_running = False
                raise ActionFailedException(f'[{type(self).__name__}] is failed: filterwheel move failure.')
                
        elif self.telescope_status.filterwheel.lower() == 'busy':
            self.telescope.log.critical(f'=====LV1[{type(self).__name__}] is failed: filterwheel is busy.')
            self.shared_memory['exception'] = 'ActionFailedException'
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise ActionFailedException(f'[{type(self).__name__}] is failed: filterwheel is busy.')
        else:
            self.telescope.log.critical(f'=====LV1[{type(self).__name__}] is failed: filterwheel status error.')
            self.shared_memory['exception'] = 'ActionFailedException'
            self.shared_memory['is_running'] = False
            self.is_running = False
            raise ActionFailedException(f'[{type(self).__name__}] is failed: filterwheel status error.')
        if result_move:
            self.shared_memory['succeeded'] = True
        
        self.telescope.log.info(f'=====LV1[{type(self).__name__}] is finished.')            
        self.is_running = False
        if self.shared_memory['succeeded']:
            return True    
        
    def abort(self):
        self.telescope.register_logfile()
        self.abort_action.set()
        self.telescope.filterwheel.wait_idle()
        self.telescope.log.warning(f'=====LV1[{type(self).__name__}] is aborted.')
        self.shared_memory['exception'] = 'AbortionException'
        self.shared_memory['is_running'] = False
        self.is_running = False
        raise AbortionException(f'[{type(self).__name__}] is aborted.')

# %%