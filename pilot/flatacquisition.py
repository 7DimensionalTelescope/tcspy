#%%
from multiprocessing import Event
from multiprocessing import Manager
from threading import Thread

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
        
    def run(self,
            count : int = 9,
            gain : int = 2750,
            binning : int = 1):
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
                false_filters = [key for key, value in status_filter.items() if value is False]
                if is_succeeded:
                    self.multitelescopes.log_dict[tel_name].info(f'[{type(self).__name__}] is finished')
                else:
                    self.multitelescopes.log_dict[tel_name].info(f'[{type(self).__name__}] is failed: {false_filters}')
            self.multitelescopes.log.critical(f'[{type(self).__name__}] is failed.')
            self.is_running = False
            raise ActionFailedException(f'[{type(self).__name__}] is failed.')    

        self.multitelescopes.log.info(f'[{type(self).__name__}] is finished.')
        self.is_running = False

        
# %%
if __name__ == '__main__':
    list_telescope = [SingleTelescope(21),
                      #SingleTelescope(2),
                      #SingleTelescope(3),
                      #SingleTelescope(5),
                      #SingleTelescope(6),
                      ##SingleTelescope(7),
                      #SingleTelescope(8),
                      #SingleTelescope(9),
                      #SingleTelescope(10),
                      #SingleTelescope(11),
                     ]

    m = MultiTelescopes(list_telescope)
#%%
    b = FlatAcquisition(m, Event())
    #b.run(gain = 2750, exptime = 100)
    #b.run(gain = 0, exptime = 30)
# %%
