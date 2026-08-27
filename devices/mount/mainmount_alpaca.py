#%%
import time
from astropy.coordinates import SkyCoord
import astropy.units as u
from astropy.time import Time
from threading import Event

from alpaca.telescope import Telescope
from alpaca.exceptions import *

from tcspy.utils import Timeout
from tcspy.utils.logger import mainLogger
from tcspy.devices.observer import mainObserver
from tcspy.configuration import mainConfig

from tcspy.utils.exception import *

#%%
class mainMount_Alpaca(mainConfig):
    """
    Class for controlling an Alpaca telescope.

    Parameters
    ----------
    unitnum : int
        The unit number of the telescope.
    **kwargs
        Additional keyword arguments.

    Attributes
    ----------
    device : alpaca.telescope.Telescope
        The Alpaca telescope instance being controlled.
    observer : mainObserver
        The observer used for calculations.
    status : dict
        The current status of the telescope.

    Methods
    -------
    get_status() -> dict
        Returns the current status of the telescope.
    connect() -> None
        Connects to the telescope.
    disconnect() -> None
        Disconnects from the telescope.
    set_park(altitude : float = 40, azimuth : float = 180) -> None
        Sets the park position of the telescope.
    park(abort_action : Event) -> None
        Parks the telescope.
    unpark() -> None
        Unparks the telescope.
    slew_radec(ra : float, dec : float, abort_action : Event, tracking: bool = True) -> None
        Slews the telescope to the given RA and Dec.
    slew_altaz(alt : float, az : float, abort_action : Event, tracking: bool = False) -> None
        Slews the telescope to the given Altitude and Azimuth coordinates.
    tracking_on() -> None
        Turns on the telescope tracking.
    tracking_off() -> None
        Turns off the telescope tracking.
    abort() -> None
        Aborts the movement of the telescope.
    """

    def __init__(self,
                 unitnum : int,
                 **kwargs):
        super().__init__(unitnum = unitnum)
        self._log = mainLogger(unitnum = unitnum, logger_name = __name__+str(unitnum)).log()
        self._min_altitude = float(self.config['TARGET_MINALT'])
        self._max_altitude = float(self.config['TARGET_MAXALT'])
        self._settle_time = float(self.config['MOUNT_SETTLETIME'])
        self._checktime = float(self.config['MOUNT_CHECKTIME'])
        self.observer = mainObserver()
        self.device = Telescope(f"{self.config['MOUNT_HOSTIP']}:{self.config['MOUNT_PORTNUM']}",self.config['MOUNT_DEVICENUM'])
        self.status = self.get_status()
        
    def get_status(self):
        """
        Returns the current status of the telescope.
        """
        status = dict()
        status['update_time'] = Time.now().isot
        status['jd'] = "{:.6f}".format(Time.now().jd)
        status['ra'] = None
        status['dec'] = None
        status['alt'] = None
        status['az'] = None
        status['at_parked'] = None
        status['is_connected'] = False
        status['is_tracking'] = None
        status['is_slewing'] = None
        status['is_stationary'] = None

        if self.device.Connected:
            try:
                status['update_time'] = Time.now().isot
            except:
                pass
            try:
                status['jd'] = "{:.6f}".format(Time.now().jd)
            except:
                pass
            try:
                coordinates = SkyCoord(self.device.RightAscension, self.device.Declination, unit = (u.hourangle, u.deg) )
                status['ra'] =  float("{:.4f}".format(coordinates.ra.deg))
                status['dec'] =  float("{:.4f}".format(coordinates.dec.deg))
            except:
                pass
            try:
                status['ra_hour'] =  float("{:.4f}".format(self.device.RightAscension))
            except:
                pass
            try:
                status['dec_deg'] =  float("{:.4f}".format(self.device.Declination))
            except:
                pass
            try:
                status['alt'] =  float("{:.3f}".format(self.device.Altitude))
            except:
                pass
            try:
                status['az'] =  float("{:.3f}".format(self.device.Azimuth))
            except:
                pass
            try:
                status['at_parked'] = self.device.AtPark
            except:
                pass
            try:
                status['is_connected'] = self.device.Connected
            except:
                pass
            try:
                status['is_tracking'] = self.device.Tracking
            except:
                pass
            try:
                status['is_slewing'] = self.device.Slewing
            except:
                pass
            try:
                status['is_stationary'] = not status['is_slewing']
            except:
                pass

        return status
    
    @Timeout(5, 'Timeout')  
    def connect(self):
        """
        Connects to the telescope.
        """
        self._log.info('Connecting to the telescope...')
        try:
            if not self.device.Connected:
                self.device.Connected = True
            time.sleep(self._checktime)
            while not self.device.Connected:
                time.sleep(self._checktime)
            if  self.device.Connected:
                self._log.info('Mount connected')
        except:
            self._log.warning('Connection failed')
            raise ConnectionException('Connection failed')
        return True
    
    @Timeout(5, 'Timeout') 
    def disconnect(self):
        """
        Disconnects from the telescope.
        """
        self._log.info('Disconnecting telescope...')
        try:
            if self.device.Connected:
                self.device.Connected = False
                time.sleep(self._checktime)
            while self.device.Connected:
                time.sleep(self._checktime)
            if not self.device.Connected:
                self._log.info('Mount is disconnected')
        except:
            self._log.warning('Disconnect failed')
            raise ConnectionException('Disconnect failed')
        return True
        
    def park(self,
             abort_action : Event):
        """
        Parks the telescope.

        Parameters
        ----------
        abort_action : threading.Event
            An event to signal if the parking operation needs to be aborted.
        """
        coordinate = SkyCoord(self.config['MOUNT_PARKAZ'],self.config['MOUNT_PARKALT'], frame = 'altaz', unit ='deg')
        alt = coordinate.alt.deg
        az = coordinate.az.deg
        
        #if self.device.CanPark:
            #if not self.device.AtPark:
        self._log.info('Parking telescope...')
        if self.device.CanSlewAsync:

            if self.device.Tracking:
                self.device.Tracking = False
            while self.device.Tracking:
                time.sleep(self._checktime)
            if self.device.AtPark:
                pass
            else:
                self.device.SlewToAltAzAsync(az, alt)
            time.sleep(self._checktime)
            while self.device.Slewing:
                time.sleep(self._checktime)
                if abort_action.is_set():
                    self.abort()
                    self._log.warning('Mount parking is aborted')
                    raise AbortionException('Mount parking is aborted')
            time.sleep(self._checktime)
            self._log.info('Mount parked')
        else:
            self._log.critical('Parking failed')
            raise ParkingFailedException('Parking failed')
        return True
    
    def unpark(self):
        """
        Unparks the telescope.
        """
        
        self._log.info('Unparking telescope...')
        if self.device.CanUnpark:
            if self.device.AtPark:
                self.device.Unpark()
            self.device.Tracking = False
            self._log.info('Mount Unparked')
            return True
        else:
            self._log.critical('Unparking failed')
            raise ParkingFailedException('Unparking failed')
        

    def slew_radec(self,
                   ra : float,
                   dec : float,
                   abort_action : Event,
                   force_action : bool = False,
                   tracking = True):
        """
        Slews the telescope to the given RA and Dec.

        Parameters
        ----------
        ra : float
            The right ascension of the target, in hours.
        dec : float
            The declination of the target, in degrees.
        abort_action : threading.Event
            An event to signal if the slewing operation needs to be aborted.
        tracking : bool, optional
            Whether to start tracking after slewing to the target. Default is True.
        """
        from tcspy.utils.target import SingleTarget
        target = SingleTarget(observer = self.observer, ra = float(ra), dec = float(dec))
        altaz = target.altaz()
        self._log.info('Slewing to the coordinate (RA = %.3f, Dec = %.3f, Alt = %.1f, Az = %.1f)' %(ra, dec, altaz.alt.deg, altaz.az.deg))

        # Check coordinates
        if altaz.alt.deg < self._min_altitude:
            if force_action:
                self._log.warning('Forced slewing: Destination altitude below limit (%.1fdeg)' %altaz.alt.deg)
            else:
                self._log.critical('Destination altitude below limit (%.1fdeg)' %altaz.alt.deg)
                raise SlewingFailedException('Destination altitude below limit (%.1fdeg)' %altaz.alt.deg)
        
        # Slewing 
        if self.device.CanSlewAsync:
            if self.device.AtPark:
                try:
                    self.unpark()
                except ParkingFailedException:
                    raise SlewingFailedException('Mount slewing is failed : Unpark failed')
            self.device.Tracking = True 
            while not self.device.Tracking:
                time.sleep(self._checktime)
            self.device.SlewToCoordinatesAsync(target.ra_hour, target.dec_deg)
            time.sleep(self._checktime)
            while self.device.Slewing:
                time.sleep(self._checktime)
                if abort_action.is_set():
                    self.abort()
                    self._log.warning('Mount slewing is aborted')
                    raise AbortionException('Mount slewing is aborted')
            self._log.info(f'Mount settling for {self.config["MOUNT_SETTLETIME"]}s...' )
            time.sleep(self._settle_time)
            self.status = self.get_status()
            self._log.info('Slewing finished. Current coordinate (RA = %.3f, Dec = %.3f, Alt = %.1f, Az = %.1f)' %(self.status['ra'], self.status['dec'], self.status['alt'], self.status['az']))
            if not tracking:
                try:
                    self.tracking_off()
                except TrackingFailedException:
                    raise SlewingFailedException('Mount slewing is failed : Tracking failed')
            else:
                try:
                    self.tracking_on()
                except TrackingFailedException:
                    raise SlewingFailedException('Mount slewing is failed : Tracking failed')                    
            return True
        else:
            self._log.critical('Slewing failed')
            raise SlewingFailedException('Slewing failed')
            
    def slew_altaz(self,
                   alt : float,
                   az : float,
                   abort_action : Event,
                   force_action : bool = False,
                   tracking = False):
        """
        Slews the telescope to the given Altitude and Azimuth coordinates.

        Parameters
        ----------
        alt : float
            Altitude coordinate in degrees.
        az : float
            Azimuth coordinate in degrees.
        abort_action : threading.Event
            An event to signal if the slewing operation needs to be aborted.
        tracking : bool, optional
            If True, activate the telescope tracking feature after slewing. Default is False.
        """
        self._log.info('Slewing to the coordinate (Alt = %.1f, Az = %.1f)' %(alt, az))

        # Check coordinates
        if alt < self._min_altitude:
            if force_action:
                self._log.warning('Forced slewing: Destination altitude below limit (%.1fdeg)' %alt)
            else:
                self._log.critical('Destination altitude below limit (%.1fdeg)' %alt)
                raise SlewingFailedException('Destination altitude below limit (%.1fdeg)' %alt)
        
        # Slewing 
        if self.device.CanSlewAsync:
            if self.device.AtPark:
                try:
                    self.unpark()
                except ParkingFailedException:
                    raise SlewingFailedException('Mount slewing is failed : Unpark failed')
            self.device.Tracking = False 
            while self.device.Tracking:
                time.sleep(self._checktime)
            self.device.SlewToAltAzAsync(az, alt)
            time.sleep(self._checktime)
            while self.device.Slewing:
                time.sleep(self._checktime)
                if abort_action.is_set():
                    self.abort()
                    self._log.warning('Mount slewing is aborted')
                    raise AbortionException('Mount slewing is aborted')
            self._log.info(f'Mount settling for {self.config["MOUNT_SETTLETIME"]}s...' )
            time.sleep(self._settle_time)
            self.status = self.get_status()
            self._log.info('Slewing finished. Current coordinate (Alt = %.1f, Az = %.1f)' %(self.status['alt'], self.status['az']))
            if tracking:
                try:
                    self.tracking_on()
                except TrackingFailedException:
                    raise SlewingFailedException('Tracking failed')
            return True
        else:
            self._log.critical('Slewing failed')
            raise SlewingFailedException('Slewing failed')

    def tracking_on(self):
        """
        Turnㄴ on the telescope tracking.
        """
        if self.device.CanSetTracking:
            if not self.device.Tracking:
                time.sleep(self._checktime)
                self.device.Tracking = True
                while not self.device.Tracking:
                    time.sleep(self._checktime)
            if  self.device.Tracking:
                self._log.info('Tracking activated')
            return True
        else:
            self._log.critical('Tracking failed')
            raise TrackingFailedException('Tracking failed')
    
    def tracking_off(self):
        """
        Turnㄴ off the telescope tracking.
        """
        if self.device.CanSetTracking:
            if self.device.Tracking:
                self.device.Tracking = False
                time.sleep(self._checktime)
                while self.device.Tracking:
                    time.sleep(self._checktime)
            if not self.device.Tracking:
                self._log.info('Tracking deactivated')
            return True
        else:
            self._log.critical('Untracking failed')
            raise TrackingFailedException('Untracking failed')
    
    def find_home(self):
        """
        Finds the home position of the telescope.
        """
        print('Find home is not implemented in Alpaca Mount')
        pass
    
    def abort(self):
        """
        Aborts the movement of the telescope.
        """
        self.device.AbortSlew()