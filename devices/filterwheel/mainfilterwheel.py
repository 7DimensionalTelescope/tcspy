#%%
from astropy.io import ascii
from astropy.time import Time
import time
import json
from alpaca.filterwheel import FilterWheel
from multiprocessing import Event
from multiprocessing import Lock

from tcspy.configuration import mainConfig
from tcspy.utils import Timeout
from tcspy.utils.exception import *
from tcspy.utils.logger import mainLogger
# %%
class mainFilterwheel(mainConfig):
    """
    This class provides an interface to interact with a filter wheel device.

    Parameters
    ----------
    unitnum : int
        The unit number.

    Attributes
    ----------
    device : alpaca.filterwheel.FilterWheel
        The filter wheel device to interact with.
    filtnames : list
        A list of all filter names configured for the filter wheel.
    offsets : dict
        A dictionary containing the filter offsets configured for the filter wheel.
    status : dict
        A dictionary containing the current status of the filter wheel.

    Methods
    -------
    get_status() -> dict
        Returns a dictionary containing the current status of the filter wheel.
    connect()
        Connects to the filter wheel device.
    disconnect()
        Disconnects from the filter wheel device.
    move(filter_: Union[str, int]) -> bool
        Moves the filter wheel to the specified filter position or filter name.
    abort()
        Dummy abort action. No supported action exists.
    """
    
    def __init__(self,
                 unitnum : int,
                 **kwargs):
        super().__init__(unitnum = unitnum)
        self.device = FilterWheel(f"{self.config['FTWHEEL_HOSTIP']}:{self.config['FTWHEEL_PORTNUM']}",self.config['FTWHEEL_DEVICENUM'])        
        self.status = self.get_status()
        self.is_idle = Event()
        self.is_idle.set()
        self.device_lock = Lock()
        self.filtnames = self._get_all_filt_names()
        # self.offsets = self._get_all_filt_offset()
        self._log = mainLogger(unitnum = unitnum, logger_name = __name__+str(unitnum)).log()

    def get_status(self) -> dict:
        """
        Returns a dictionary containing the current status of the filter wheel.

        Returns
        -------
        status : dict
            A dictionary containing the current status of the filter wheel.
        """
        status = dict()
        status['update_time'] = Time.now().isot
        status['jd'] = round(Time.now().jd,6)
        status['is_connected'] = False
        status['name'] = None
        status['filter_'] = None
        status['offset'] = None

        if self.device.Connected:
            try:              
                filtinfo = self._get_current_filtinfo()
            except:
                pass
            try:
                status['update_time'] = Time.now().isot
            except:
                pass
            try:
                status['jd'] = round(Time.now().jd,6)
            except:
                pass
            try:
                status['name'] = self.device.Name
            except:
                pass
            try:
                status['filter_'] = filtinfo['name']
            except:
                pass
            # try:
            #     status['offset'] = filtinfo['offset']
            # except:
            #     pass
            try:
                status['is_connected'] = self.device.Connected
            except:
                pass

        return status

    @Timeout(5, 'Timeout')
    def connect(self):
        """
        Connects to the filter wheel device.
        """
        self._log.info('Connecting to the filterwheel...')
        try:
            self.device.Connected = True
            time.sleep(float(self.config['FTWHEEL_CHECKTIME']))
            while not self.device.Connected:
                time.sleep(float(self.config['FTWHEEL_CHECKTIME']))
            if  self.device.Connected:
                self._log.info('Filterwheel connected')
        except:
            self._log.critical('Connection failed')
            raise ConnectionException('Connection failed')
        return True
    
    @Timeout(5, 'Timeout')
    def disconnect(self):
        """
        Disconnects from the filter wheel device.
        """
        self._log.info('Disconnecting the filterwheel...')
        try:
            if self.device.Connected:
                self.device.Connected = False
                time.sleep(float(self.config['FTWHEEL_CHECKTIME']))
            while self.device.Connected:
                time.sleep(float(self.config['FTWHEEL_CHECKTIME']))
            if not self.device.Connected:
                self._log.info('Filterwheel is disconnected')
        except:
            self._log.critical('Disconnect failed')
            raise ConnectionException('Disconnect failed')
        return True
            
    def move(self,
             filter_ : str or int) -> bool:
        """
        Moves the filter wheel to the specified filter position or filter name.

        Parameters
        ----------
        filter_ : str or int
            The position or name of the filter to move to.
        """
        self.is_idle.clear()
        self.device_lock.acquire()
        exception_raised = None
        
        try:
            # Check whether the input filter is implemented
            current_filter = self._get_current_filtinfo()['name']
            if isinstance(filter_, str):
                if not filter_ in self.filtnames:
                    self._log.critical(f'Filter {filter_} is not implemented [{self.filtnames}]')
                    raise FilterChangeFailedException(f'Filter {filter_} is not implemented [{self.filtnames}]')
                else:
                    self._log.info('Changing filter... (Current : %s To : %s)'%(current_filter, filter_))
                    filter_ = self._filtname_to_position(filter_)
            else:
                if filter_ > len(self.filtnames):
                    self._log.critical(f'Position "{filter_}" is not implemented')
                    raise FilterChangeFailedException(f'Position "{filter_}" is not implemented')
            
            # Change filter
            self._log.info('Changing filter... (Current : %s To : %s)'%(current_filter, self._position_to_filtname(filter_)))
            self.device.Position = filter_
            time.sleep(float(self.config['FTWHEEL_CHECKTIME']))
            while not self.device.Position == filter_:
                time.sleep(float(self.config['FTWHEEL_CHECKTIME']))
            time.sleep(2*float(self.config['FTWHEEL_CHECKTIME']))
            
            # Return result
            self._log.info('Filter changed (Current : %s)'%(self._get_current_filtinfo()['name']))
            return True
        
        except Exception as e:
            exception_raised = e

        finally:
            self.device_lock.release()
            self.is_idle.set()
            if exception_raised:
                raise exception_raised            

    def get_offset_from_currentfilt(self,
                                    filter_ : str):
        """
        Calculates the offset between the current filter and the specified filter.

        Parameters
        ----------
        filter_ : str
            The filter name for which the offset is calculated.

        Returns
        -------
        pffset : int
            The offset between the current filter and the specified filter.
        """
        current_filter = self._get_current_filtinfo()['name']
        offset = self.calc_offset(current_filt= current_filter, changed_filt = filter_)
        return offset 
    
    def calc_offset(self,
                    current_filt : str,
                    changed_filt : str) -> int:
        """
        Calculates the offset between two filters.

        Parameters
        ----------
        current_filt : str
            The name of the current filter.
        changed_filt : str
            The name of the filter that will be changed to.

        Returns
        -------
        offset : int
            The offset between the two filters.

        Raises
        ------
        FilterRegisterException
            If either the current filter or the changed filter is not registered.
        """
        try:
            offset_current = self.offsets[current_filt]['offset']
            offset_changed = self.offsets[changed_filt]['offset']
            offset = offset_changed - offset_current
            if (offset_changed == -999) | (offset_current == -999):
                offset = 0 
            return offset
        except:
            raise FilterRegisterException(f'Filter: one of {current_filt}, {changed_filt} is not registered')

    def wait_idle(self):
        self.is_idle.wait()
    
    # Information giding
    def _get_all_filt_names(self) -> list:

        if self.device.Names is None:
            raise FilterRegisterException("No filter information is registered")
        filtnames = self.device.Names
        return filtnames
        
    def _get_all_filt_offset(self) -> list:
        with open(self.config['FTWHEEL_OFFSETFILE'], 'r') as f:
            info_offset = json.load(f)
            del info_offset['updated_date']
        filters_in_config = set(info_offset.keys())
        filters_in_device = set(self._get_all_filt_names())
        if not filters_in_config.issubset(filters_in_device):
            raise FilterRegisterException(f'Registered filters are not matched with configured filters \n Configured = [{filters_in_config}] \n Registered = [{filters_in_device}]')
        return info_offset
    
    def _position_to_filtname(self,
                              position : int) -> str:
        try:
            return self.filtnames[position]  
        except:
            self._log.warning('Position "%s" is out of range of the filterwheel'%position)
            raise FilterRegisterException('Position "%s" is out of range of the filterwheel'%position)
        
    def _filtname_to_position(self,
                              filtname : str) -> int:
        try:
            return self.filtnames.index(filtname)
        except:
            self._log.warning('%s is not implemented in the filterwheel'%filtname)
            raise FilterRegisterException('%s is not implemented in the filterwheel'%filtname)

    def _get_current_filtinfo(self) -> str:
        position = self.device.Position
        filtname = self._position_to_filtname(position = position)
        return dict( position = position, name = self.filtnames[position])#, offset = self.offsets[filtname]['offset'])
    

# %%
if __name__ == '__main__':
    self = mainFilterwheel(unitnum = 36)
    
# %%
