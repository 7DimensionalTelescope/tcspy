#%%
from multiprocessing import Process, Event, Manager
from tcspy.devices import SingleTelescope
from typing import List, Union
import time
from tcspy.action.level1 import *

from tcspy.utils.exception import *

class MultiAction:
    def __init__(self, 
                 array_telescope : List[SingleTelescope],
                 array_kwargs : Union[List[dict], dict],
                 function : object,
                 abort_action : Event
                 ):
        """
        A class representing the execution of an action on multiple telescopes.

        Parameters
        ----------
        array_telescope : List[SingleTelescope]
            A list with instances of SingleTelescope class representing the telescopes to perform the action on.
        array_kwargs : Union[List[dict], dict]
            If it's a dictionary, then it will be applied to all telescopes. If it's a list, each dictionary in the list will apply to the corresponding telescope.
        function : object
            The function to be executed in each telescope.
        abort_action : Event
            An instance of the built-in Event class to handle the abort action.

        Attributes
        ----------
        array_telescope : List[SingleTelescope]
            The list of SingleTelescope instances.
        array_kwargs : Union[List[dict], dict]
            The kwargs to feed into each function call.
        function : object
            The function to be executed in each telescope.
        abort_action : Event
            The Event instance to handle the abort actions.
        shared_memory : Manager().dict()
            A managed dictionary to hold the results of each function call.

        Methods
        -------
        run()
            Execute the action on each telescope.
        abort()
            Abort the ongoing action.
        get_results()
            Retrieve the results for each telescope's executed action.
        """
        self.array_telescope = array_telescope
        self.array_kwargs = array_kwargs
        if isinstance(array_kwargs, dict):
            num_telescope = len(array_telescope)
            self.array_kwargs = [self.array_kwargs.copy() for i in range(num_telescope)]
        self.function = function
        self.abort_action = abort_action
        #self.shared_memory = dict()
        self.shared_memory_manager = Manager()
        self.shared_memory = self.shared_memory_manager.dict()
        self._set_multiprocess()
        
    def _set_multiprocess(self):
        self.multifunction = dict()
        self.multiprocess = dict()
        for telescope, kwargs in zip(self.array_telescope, self.array_kwargs):
            func = self.function(telescope, abort_action = self.abort_action)
            process = Process(name = f'{self.function.__name__}[{telescope.tel_name}]', target = func.run, kwargs= kwargs)
            self.multifunction[telescope.tel_name] = func
            self.multiprocess[telescope.tel_name] = process
            self.shared_memory[telescope.tel_name] = func.shared_memory

    def run(self):
        """
        Add the parameters for each thread in the queue.
        """
        self.abort_action.clear()
        for process in self.multiprocess.values():
            process.start()
        while True:
            is_running = self.status.values()
            if not any(is_running):
                break
            time.sleep(0.1)
            if self.abort_action.is_set():
                for process in self.multiprocess.values():
                    if process.is_alive():
                        process.terminate()
                raise AbortionException(f'[{type(self).__name__}] is aborted.')
        
        # After running all processes, check succeeded or not
        is_all_succeeded = []
        for tel_name, result in self.shared_memory.items():
            is_succeeded = self.shared_memory[tel_name]['succeeded']
            is_all_succeeded.append(is_succeeded)
        if not all(is_all_succeeded):
            raise ActionFailedException(f'[{type(self).__name__}] is failed.')

    def abort(self):
        """
        Abort the ongoing action.
        """
        self.abort_action.set()
    
    @property
    def status(self):
        status = dict()
        for process in self.multiprocess.values():
            status[process.name] = process.is_alive()
        return status
# %%
if __name__ == '__main__':
    from threading import Thread
    from multiprocessing import Event
    from tcspy.action.level2 import *
    from tcspy.devices import MultiTelescopes
    m = MultiTelescopes()
#%%
if __name__ == '__main__':
    abort_action = Event()
    m = MultiAction(list(m.devices.values()), dict(), FansOn, abort_action)
    p = Thread(target = m.run, kwargs = dict())
    p.start()
    #m.abort()
# %%
