#%%
from multiprocessing import Event
from multiprocessing import Manager
from threading import Thread
import time

from tcspy.configuration import mainConfig
from tcspy.devices import MultiTelescopes
from tcspy.devices import SingleTelescope

from tcspy.utils.exception import *
from tcspy.action import MultiAction
from tcspy.action.level1 import Exposure
from tcspy.action.level2 import AutoFlat
#%%

class FlatAcquisition(mainConfig):

    def __init__(self,
                 multitelescopes : MultiTelescopes,
                 abort_action : Event,
                 ):
        super().__init__()
        self.multitelescopes = multitelescopes
        self.abort_action = abort_action
        self.is_running = False
        self.succeeded = False
        self.failure_reason = ''

    def run(self,
            count : int = 9,
            binning : int = 1,
            gain : int = 16
            ):
        """
        Starts the startup process in a separate thread.
        """
        startup_thread = Thread(target=self._process, kwargs = dict(count = count, binning = binning, gain = gain))
        startup_thread.start()
        
        
    def abort(self):
        """
        Aborts the startup process.
        """
        self.is_running = False
        self.abort_action.set()
        self.multitelescopes.log.warning(f'[{type(self).__name__}] is aborted.')  
        raise AbortionException(f'[{type(self).__name__}] is aborted.')  
    
    def _process(self, count, gain, binning):
        self.is_running = True
        self.multitelescopes.register_logfile()
        self.multitelescopes.update_statusfile(status = 'busy', do_trigger = True)
        self.multitelescopes.log.info(f'[{type(self).__name__}] is triggered.')
        
        #Prepare for MultiAction
        params_autoflat_all = []
        for telescope_name, telescope in self.multitelescopes.devices.items():
            params_autoflat = dict(count = count,
                                    gain = gain,
                                    binning = binning) 
            params_autoflat_all.append(params_autoflat)
        self.multiaction = MultiAction(array_telescope= self.multitelescopes.devices.values(), array_kwargs= params_autoflat_all, function = AutoFlat, abort_action = self.abort_action)    
        self.shared_memory = self.multiaction.shared_memory
        
        #Run
        try:
            self.multiaction.run()
        except AbortionException:
            self.abort()
        except ActionFailedException:
            for tel_name, result in self.shared_memory.items():
                is_succeeded = self.shared_memory[tel_name]['succeeded']
                status_filter = self.shared_memory[tel_name]['status']
                exception_info = self.shared_memory[tel_name].get('exception', None)
                false_filters = [key for key, value in status_filter.items() if value is False]
                if is_succeeded:
                    self.multitelescopes.log_dict[tel_name].info(f'[{type(self).__name__}] is finished')
                else:
                    reason = false_filters if false_filters else exception_info
                    self.failure_reason += f'AutoFlat[{tel_name}]:{reason}; '
                    self.multitelescopes.log_dict[tel_name].warning(f'[{type(self).__name__}] is failed: {reason}')
            self.multitelescopes.log.critical(f'[{type(self).__name__}] is failed.')
            self.multitelescopes.update_statusfile(status='idle', do_trigger=True)
            self.is_running = False
            raise ActionFailedException(f'[{type(self).__name__}] is failed.')    

        self.multitelescopes.log.info(f'[{type(self).__name__}] is finished.')
        self.multitelescopes.update_statusfile(status = 'idle', do_trigger = True)
        self.succeeded = True
        self.is_running = False


# %%
if __name__ == '__main__':
    M = MultiTelescopes()
    abort_action = Event()
    application = FlatAcquisition(M, abort_action)
    application.run()

# %%
