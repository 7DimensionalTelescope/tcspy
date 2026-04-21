#%%
from tcspy.configuration import mainConfig
from tcspy.devices.camera import mainCamera
from tcspy.devices.focuser import mainFocuser_Alpaca
from tcspy.devices.focuser import mainFocuser_pwi4
from tcspy.devices.focuser import mainFocuser_NINA
from tcspy.devices.filterwheel import mainFilterwheel
from tcspy.devices.observer import mainObserver
from tcspy.devices.weather import mainWeather
from tcspy.devices.safetymonitor import mainSafetyMonitor
from tcspy.utils.error import *
from tcspy.devices.mount import mainMount_Alpaca
from tcspy.devices.mount import mainMount_pwi4
from tcspy.utils.logger import mainLogger
import json
from astropy.time import Time
import portalocker
#%%

class SingleTelescope(mainConfig):
    """
    A class representing a single telescope setup.

    Parameters
    ----------
    unitnum : int
        The unit number.

    Attributes
    ----------
    mount_type : str
        The type of mount device.
    focus_type : str
        The type of focuser device.
    name : str
        The name of the telescope.
    camera : mainCamera
        The camera device.
    mount : mainMount_Alpaca or mainMount_pwi4
        The mount device.
    focuser : mainFocuser_Alpaca or mainFocuser_pwi4 or mainFocuser_NINA
        The focuser device.
    filterwheel : mainFilterwheel
        The filter wheel device.
    weather : mainWeather
        The weather device.
    safetymonitor : mainSafetyMonitor
        The safety monitor device.
    observer : mainObserver
        The observer device.
    

    Methods
    -------
    update_status()
        Update the status of all devices.
    """
    def __init__(self,
                 unitnum : int):
        super().__init__(unitnum= unitnum)
        self.mount_type = self.config['MOUNT_DEVICETYPE'].lower()
        self.focus_type = self.config['FOCUSER_DEVICETYPE'].lower()
        self.name = self.tel_name
        self.camera = None
        self.mount = None
        self.focuser = None
        self.filterwheel = None
        self.weather = None
        self.safetymonitor = None
        #self.switch = None
        self.observer = self._get_observer()
        self._set_devices()
        self.log = self.register_logfile()

    def __repr__(self):
        txt=  f'SingleTelescope[{self.name}]'
        return txt

    @property
    def status(self):
        """
        Get the status of all devices.

        Returns
        -------
        dict
            A dictionary containing the status of all devices.
        """
        self._get_status()
        status = dict()
        status['camera'] = self.camera.status
        status['mount'] = self.mount.status
        status['focuser'] = self.focuser.status
        status['filterwheel'] = self.filterwheel.status
        status['weather'] = self.weather.status
        status['safetymonitor'] = self.safetymonitor.status
        status['observer'] = self.observer.status
        #status['switch'] = self.switch.status
        return status

    @property
    def devices(self):
        """
        Get all devices.

        Returns
        -------
        dict
            A dictionary containing all devices.
        """
        devices = dict()
        devices['camera'] = self.camera
        devices['mount'] = self.mount
        devices['focuser'] = self.focuser
        devices['filterwheel'] = self.filterwheel
        devices['weather'] = self.weather
        devices['safetymonitor'] = self.safetymonitor
        #devices['switch'] = self.switch
        return devices
    
    def update_statusfile(self, 
                        status: str,  # 'idle' or 'busy'
                        do_trigger: bool = True):
        if do_trigger:
            if status.lower() not in ['idle', 'busy']:
                raise ValueError('Status must be either "idle" or "busy".')

            status_file = self.config['MULTITELESCOPES_FILE']

            # Lock the file for safe access
            with portalocker.Lock(status_file, 'r+', timeout=10) as f:
                try:
                    # Load the JSON data
                    f.seek(0)  # Ensure reading starts at the beginning
                    status_dict = json.load(f)

                    # Update the status for this telescope
                    if self.name in status_dict:
                        status_dict[self.name]['Status'] = status.lower()
                        status_dict[self.name]['Status_update_time'] = Time.now().isot
                    else:
                        raise KeyError(f"Telescope '{self.name}' not found in status file.")

                    # Overwrite the file with the updated data
                    f.seek(0)  # Reset pointer to the beginning
                    f.truncate()  # Clear the file before writing
                    json.dump(status_dict, f, indent=4)
                    f.flush()  # Ensure data is written to disk
                except json.JSONDecodeError:
                    raise ValueError(f"The file {status_file} is not a valid JSON file.")
        else:
            return None
    
    def register_logfile(self):
        self.log = mainLogger(unitnum = self.unitnum, logger_name = __name__+str(self.unitnum)).log()
        
    def _get_status(self):
        self.camera.status = self.camera.get_status()
        self.mount.status = self.mount.get_status()
        self.focuser.status = self.focuser.get_status()
        self.filterwheel.status = self.filterwheel.get_status()
        self.weather.status = self.weather.get_status()
        self.safetymonitor.status = self.safetymonitor.get_status()
        #self.switch.status = self.switch.get_status()
    
    def _set_devices(self):
        self.camera = self._get_camera()
        self.mount = self._get_mount()
        self.focuser = self._get_focuser()
        self.filterwheel = self._get_filterwheel()
        self.weather = self._get_weather()
        self.safetymonitor = self._get_safetymonitor()
        #self.switch = self._get_switch()
    
    def _get_camera(self):
        return mainCamera(unitnum= self.unitnum)

    def _get_mount(self):
        if self.mount_type.lower() == 'alpaca':
            return mainMount_Alpaca(unitnum= self.unitnum)
        elif self.mount_type.lower() == 'pwi4':
            return mainMount_pwi4(unitnum= self.unitnum)
        else: 
            return TelTypeError(f'Mount Type "{self.mount_type}" is not defined')

    def _get_focuser(self):
        if self.focus_type.lower() == 'alpaca':
            return mainFocuser_Alpaca(unitnum= self.unitnum)
        elif self.focus_type.lower() == 'pwi4':
            return mainFocuser_pwi4(unitnum= self.unitnum)
        elif self.focus_type.lower() == 'nina':
            return mainFocuser_NINA(unitnum= self.unitnum)
        else:
            return FocuserTypeError(f'Focuser Type "{self.focus_type}" is not defined')
    
    def _get_filterwheel(self):
        return mainFilterwheel(unitnum= self.unitnum)
    
    def _get_observer(self):
        return mainObserver()
    
    def _get_weather(self):
        return mainWeather()
    
    def _get_safetymonitor(self):
        return mainSafetyMonitor()
    
    #def _get_switch(self):
    #    return mainSwitch(unitnum = self.unitnum)

# %%
if __name__ == '__main__':
    self = SingleTelescope(36)
# %%
