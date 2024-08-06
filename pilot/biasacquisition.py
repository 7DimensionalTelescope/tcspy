

#%%
from multiprocessing import Event
from threading import Thread
import uuid

from tcspy.configuration import mainConfig
from tcspy.devices import MultiTelescopes
from tcspy.devices import SingleTelescope

from tcspy.utils.exception import *

from tcspy.action import MultiAction
from tcspy.action.level1 import Exposure
#%%

class BiasAcquisition(mainConfig):

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
            binning = 1,
            gain : int = 2750):
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
        
    def _process(self, 
                 count, 
                 binning : int = 1, 
                 gain : int = 2750):
        self.is_running = True
        id_ = uuid.uuid4().hex
        self.multitelescopes.log.info(f'[{type(self).__name__}] is triggered.')
        for i in range(count):
            params_exposure_all = []
            for telescope_name, telescope in self.multitelescopes.devices.items():
                params_exposure = dict(frame_number = i,
                                       exptime = 0,
                                       filter_ = None,
                                       imgtype = 'BIAS',
                                       binning = binning,
                                       gain = gain,
                                       obsmode = 'Single',
                                       objtype = 'BIAS',
                                       name = 'BIAS',
                                       id_ = id_
                                       ) 
                params_exposure_all.append(params_exposure)
            multi_exposure =MultiAction(array_telescope= self.multitelescopes.devices.values(), array_kwargs= params_exposure_all, function = Exposure, abort_action = self.abort_action)    
            result_multi_exposure = multi_exposure.shared_memory
            #Run
            try:
                multi_exposure.run()
            except AbortionException:
                self.is_running = False
                self.multitelescopes.log.warning(f'[{type(self).__name__}] is aborted.')    
                raise AbortionException(f'[{type(self).__name__}] is aborted.')  
        self.multitelescopes.log.info(f'[{type(self).__name__}] is finished.')
        self.is_running = False

        
# %%
if __name__ == '__main__':
    list_telescope = [SingleTelescope(1),
                      SingleTelescope(2),
                      SingleTelescope(3),
                      SingleTelescope(5),
                      SingleTelescope(6),
                      SingleTelescope(7),
                      SingleTelescope(8),
                      SingleTelescope(9),
                      SingleTelescope(10),
                      SingleTelescope(11),
                     ]
    m = MultiTelescopes(list_telescope)
    b = BiasAcquisition(m, Event())
    b.run(gain = 2750)
# %%
