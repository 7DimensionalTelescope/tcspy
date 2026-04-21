#%%
from threading import Thread
from typing import List
from tcspy.devices import SingleTelescope
from tcspy.devices import TelescopeStatus
from tcspy.devices.observer import mainObserver
from tcspy.utils.logger import mainLogger
from astropy.time import Time
from tcspy.configuration import mainConfig
import json
import re
import portalocker
#%%

class MultiTelescopes(mainConfig):
    """
    A class representing multiple telescopes.

    Parameters
    ----------
    SingleTelescope_list : List[SingleTelescope]
        A list of SingleTelescope instances representing individual telescopes.

    Attributes
    ----------
    devices : dict
        A dictionary containing the telescopes with their names as keys and corresponding SingleTelescope instances as values.
    log : dict
        A dictionary containing logger instances of multiple telescopes for each telescope with their names as keys.
    observer : mainObserver
        An instance of the mainObserver class.

    Methods
    -------
    add(singletelescope : SingleTelescope)
        Add a SingleTelescope instance to the MultiTelescopes instance.
    remove(telescope_name)
        Remove a telescope by its name.
    status
        Get the status of all telescopes using ThreadPoolExecutor.
    """
    
    def __init__(self, 
                 SingleTelescope_list : List[SingleTelescope] = None):
        super().__init__()
        self._devices_list = SingleTelescope_list
        if not self._devices_list:
            self._load_from_config()
        self._register()
    
    def __repr__(self):
        txt=  f'MultiTelescopes[{list(self.devices.keys())}]'
        return txt
        
    def update_statusfile(self, 
                          status : str, #idle or busy
                          do_trigger : bool = True
                          ):
        if do_trigger:
            if status.lower() not in ['idle', 'busy']:
                raise ValueError('Status must be either "idle" or "busy".')

            status_file = self.config['MULTITELESCOPES_FILE']

            # Safely lock the file for updating
            with portalocker.Lock(status_file, 'r+', timeout=10) as f:
                try:
                    # Load the JSON data
                    f.seek(0)  # Ensure reading starts at the beginning
                    status_dict = json.load(f)

                    # Update the status for each telescope
                    for tel_name in self.devices.keys():
                        if tel_name in status_dict:
                            status_dict[tel_name]['Status'] = status.lower()
                            status_dict[tel_name]['Status_update_time'] = Time.now().isot

                    # Overwrite the file with the updated data
                    f.seek(0)  # Reset pointer to the beginning
                    f.truncate()  # Clear the file before writing
                    json.dump(status_dict, f, indent=4)
                    f.flush()  # Ensure data is written to disk
                except json.JSONDecodeError:
                    raise ValueError(f"The file {status_file} is not a valid JSON file.")
        else:
            return None
    
    def add(self,
            singletelescope : SingleTelescope):
        """
        Add a SingleTelescope instance to the MultiTelescopes instance.

        Parameters
        ----------
        SingleTelescope : SingleTelescope
            The SingleTelescope instance to add.
        """
        telescope_name = singletelescope.name
        log = mainLogger(unitnum = singletelescope.unitnum, logger_name = __name__+str(singletelescope.unitnum)).log()
        self.devices[telescope_name] = singletelescope
        self.log_dict[telescope_name] = log
    
    def remove(self,
               telescope_name):
        """
        Remove a telescope by its name.

        Parameters
        ----------
        telescope_name : str
            The name of the telescope to remove.
        """
        self.devices.pop(telescope_name)
        self.log_dict.pop(telescope_name)
        self.log = self._all_logs()

    @property
    def status(self):
        """
        Get the status of all telescopes using ThreadPoolExecutor.

        Returns
        -------
        dict
            A dictionary containing the status of all telescopes.
        """
        thread_list = []
        for device in self._devices_list:
            thread = Thread(target=self._get_device_status, args=(device,))
            thread_list.append(thread)
            thread.start()

        for thread in thread_list:
            thread.join()
        return self._status_dict
    
    @property
    def filters(self):
        filters_dict = dict()
        for telescope in self._devices_list:
            try:
                filters_dict[telescope.name] = telescope.filterwheel.filtnames
            except:
                filters_dict[telescope.name] = None
        return filters_dict
    
    def register_logfile(self):
        self.log_dict = self._dict_logs()
        self.log = self._all_logs()
    
    def _load_from_config(self):
        print('Loading multitelescopes...')
        with open(self.config['MULTITELESCOPES_FILE'],'r') as f:
            device_status_all = json.load(f)
        
        def is_telescope_active(telescope_status: dict):
            tel_status = telescope_status
            alldevices_status = []
            for device_name in ['Mount', 'Focuser', 'Camera', 'Filterwheel']:
                device_status = tel_status[device_name]['is_active']
                alldevices_status.append(device_status)
            telescope_status = all(alldevices_status)
            return telescope_status
        
        list_telescopes = []
        for tel_name, tel_status in device_status_all.items():
            is_tel_active = is_telescope_active(tel_status)
            tel_num = int(re.search(r"\d{2}$", tel_name).group())
            if is_tel_active:
                list_telescopes.append(SingleTelescope(tel_num))
        
        self._devices_list = list_telescopes
        self._register()
        print('Multitelescopes are loaded.')
    
    def _register(self):
        self.devices = self._get_telescopes()
        self.observer = mainObserver()
        self._status_dict = dict()
        self.register_logfile()
        
    def _get_device_status(self, telescope):
        self._status_dict[telescope. name] = TelescopeStatus(telescope).dict
    
    def _get_telescopes(self):
        telescopes_dict = dict()
        for telescope in self._devices_list:
            telescope_name = telescope.name
            telescopes_dict[telescope_name] = telescope
        return telescopes_dict

    def _dict_logs(self):
        all_logs_dict = dict()
        for telescope in self._devices_list:
            telescope_name = telescope.name
            log = mainLogger(unitnum = telescope.unitnum, logger_name = __name__+str(telescope.unitnum)).log()
            all_logs_dict[telescope_name] = log
        return all_logs_dict

    def _all_logs(self):
        class log: 
            def info(message):
                for log_unit in self.log_dict.values():
                    log_unit.info(message)
            def warning(message):
                for log_unit in self.log_dict.values():
                    log_unit.warning(message)
            def critical(message):
                for log_unit in self.log_dict.values():
                    log_unit.critical(message)
        return log
# %%

if __name__ == '__main__':
    self = MultiTelescopes()
    
# %%
