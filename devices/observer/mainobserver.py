

#%%
from astropy.coordinates import EarthLocation, get_sun, get_body
import astropy.units as u
from datetime import datetime
from astropy.time import Time
import pytz
from astroplan import Observer
from tcspy.configuration import mainConfig
#%%
class mainObserver(mainConfig):
    """
    Class for observing astronomical objects and events from a specific location on Earth.

    Parameters
    ==========
    1. OBSERVER_LATITUDE : str
        The latitude of the observer's location in degrees.
    2. OBSERVER_LONGITUDE : str
        The longitude of the observer's location in degrees.
    3. OBSERVER_ELEVATION : str
        The elevation of the observer's location in meters.
    4. OBSERVER_TIMEZONE : str
        The timezone of the observer's location, in the format 'Area/Location'.
    5. OBSERVER_NAME : str, optional
        The name of the observer.
    6. OBSERVER_OBSERVATORY : str, optional
        The name of the observatory.
    **kwargs : optional
        Additional keyword arguments to pass to the Observer object.

    Methods
    =======
    1. get_obsinfo() -> dict
        Returns a dictionary containing the observer's information.
    2. localtime(utctime: datetime = None) -> datetime
        Converts the provided UTC time to the observer's local time.
    3. siderialtime(time: datetime or Time = None, mode: str = 'mean') -> astropy.coordinates.Angle
        Calculates the local sidereal time at the provided UTC time.
    4. now() -> astropy.time.Time
        Returns the current UTC time.
    5. is_night(time: datetime or Time = None) -> bool
        Returns True if it is night at the observer's location at the provided UTC time.
    6. tonight(time: datetime or Time = None, horizon: float = -18) -> tuple
        Calculates the start and end times of tonight at the observer's location, starting from the provided UTC time.
    7. sun_radec(time: datetime or Time = None) -> astropy.coordinates.SkyCoord
        Calculates the RA and Dec of the Sun at the provided UTC time.
    8. sun_altaz(time: datetime or Time = None) -> astropy.coordinates.AltAz
        Calculates the altitude and azimuth of the Sun at the observer's location at the provided UTC time.
    9. sun_risetime(time: datetime or Time = None, mode: str = 'nearest', horizon: float = -18) -> astropy.time.Time
        Calculates the next rise time of the Sun at the observer's location, starting from the provided UTC time.
    10. sun_settime(time: datetime or Time = None, mode: str = 'nearest', horizon: float = -18) -> astropy.time.Time
        Calculates the next set time of the Sun at the observer's location, starting from the provided UTC time.
    11. moon_radec(time: datetime or Time = None) -> astropy.coordinates.SkyCoord
        Calculates the RA and Dec of the Moon at the provided UTC time.
    12. moon_altaz(time: datetime or Time = None) -> astropy.coordinates.AltAz
        Calculates the altitude and azimuth of the Moon at the observer's location at the provided UTC time.
    13. moon_risetime(time: datetime or Time = None, mode: str = 'nearest', horizon: float = -18) -> astropy.time.Time
        Calculates the next rise time of the Moon at the observer's location, starting from the provided UTC time.
    14. moon_settime(time: datetime or Time = None, mode: str = 'nearest', horizon: float = -18) -> astropy.time.Time
        Calculates the next set time of the Moon at the observer's location, starting from the
    """
    
    def __init__(self):
        
        super().__init__()
        self._latitude = float(self.config['OBSERVER_LATITUDE'])*u.deg
        self._longitude = float(self.config['OBSERVER_LONGITUDE'])*u.deg
        self._elevation = float(self.config['OBSERVER_ELEVATION'])*u.m
        self._name = self.config['OBSERVER_NAME']
        self._timezone = pytz.timezone(self.config['OBSERVER_TIMEZONE'])
        self._earthlocation = EarthLocation.from_geodetic(lat=self._latitude, lon=self._longitude, height=self._elevation)
        self._observer = Observer(location = self._earthlocation, name = self.config['TCSPY_TEL_NAME'], timezone = self._timezone)
        self.status = self.get_status()
        self.condition = 'idle'
    ############ Site info ############
    
    def get_status(self):
        """
        Returns observation information.
        
        Returns
        =======
        1. obsinfo : dict
            A dictionary containing the following keys and values:
            - update_time: The UTC time at which the observation information was last updated, in ISO format.
            - name_observatory: The name of the observatory.
            - name_observer: The name of the observer.
            - latitude: The latitude of the observatory in degrees.
            - longitude: The longitude of the observatory in degrees.
            - elevation: The elevation of the observatory in meters.
            - timezone: The timezone of the observatory in hours relative to UTC.
            - observer: The astropy.coordinates.EarthLocation object representing the observer's location.
        """
        status = dict()
        now = Time.now()
        status['update_time'] = now.isot
        status['jd'] = round(now.jd,6)
        #status['name_observatory'] = self._observatory
        status['name_observer'] = self._name
        status['latitude'] = round(self._latitude.value,4)
        status['longitude'] = round(self._longitude.value,4)
        status['elevation'] = round(self._elevation.value,2)
        status['moonphase'] = self.moon_phase(now)
        status['timezone'] = self._timezone
        status['observer'] = self._observer
        status['is_connected'] = True
        return status
        
    ############ Time ############
    def localtime(self, 
                  utctimes : datetime or np.array = None):
        """
        Returns the datetime object representing the corresponding local time in the timezone 
        specified by the object's `_timezone` attribute.

        Parameters
        ==========
        1. utctime : datetime, optional
            The datetime object representing the time to convert to local time. If not provided,
            the current UTC time will be used.
            
        Returns
        =======
        1. localtime : datetime
            The datetime object representing the corresponding local time in the timezone 
            specified by the object's `_timezone` attribute.
        """
        
        if utctimes is None:
            utctimes = datetime.utcnow()
        localtime = pytz.utc.localize(utctimes).astimezone(self._timezone)
        return localtime
    
    def siderialtime(self,
                     utctimes : datetime or Time or np.array = None,
                     mode : str = 'mean'): 
        """
        Calculate the local sidereal time at a given UTC time and mode.
        
        Parameters
        ==========
        1. time : datetime or Time, optional
            The UTC time at which to calculate the local sidereal time. If not provided, the current time is used.
        2. mode : str, optional
            The mode to use when calculating the local sidereal time. Can be either 'mean' (default) or 'apparent'.

        Returns
        =======
        1. local_sidereal_time : astropy.coordinates.Angle
            The local sidereal time at the given time, as an Angle object.
        """
        
        if utctimes is None:
            utctimes = Time.now()
        if not isinstance(utctimes, Time):
            utctimes = Time(utctimes)
        return self._observer.local_sidereal_time(utctimes, kind = mode)
    
    def now(self):
        """
        Get the current UTC time.
        
        Returns
        =======
        1. time : astropy.time.Time
            The current UTC time.
        """
        
        return Time.now()
    
    def is_night(self,
                 utctimes : datetime or Time or np.array = None):
        """
        Check if it is night at a given UTC time and location.
        
        Parameters
        ==========
        1. time : datetime or Time, optional
            The UTC time at which to check if it is night. If not provided, the current time is used.

        Returns
        =======
        1. is_night : bool
            True if it is night at the given time and location, False otherwise.
        """
        
        if utctimes is None:
            utctimes = Time.now()
        if not isinstance(utctimes, Time):
            utctimes = Time(utctimes)
        return self._observer.is_night(utctimes, horizon = -18*u.deg)
    
    def tonight(self,
                time : datetime or Time or np.array = None,
                horizon = -18):
        """
        Get the start and end times of tonight at a given UTC time and location.

        Parameters
        ==========
        1. time : datetime or Time, optional
            The UTC time at which to start the calculation of the start and end of tonight. If not provided, the current time is used.
        2. horizon : float, optional
            The horizon angle to use when calculating the start and end of tonight. Default is -18 degrees.

        Returns
        =======
        1. tonight : tuple
            A tuple of two astropy.time.Time objects representing the start and end times of tonight at the given time and location.
        """

        if time is None:
            time = Time.now()
        if not isinstance(time, Time):
            time = Time(time)
        return self._observer.tonight(time, horizon = horizon*u.deg)

    ############ Sun ############
    def sun_radec(self,
                  utctimes : datetime or Time or np.array = None):
        """
        Get the RA and Dec of the Sun at a given UTC time.

        Parameters
        ==========
        1. time : datetime or Time, optional
            The UTC time at which to calculate the RA and Dec of the Sun. If not provided, the current time is used.

        Returns
        =======
        1. sun_radec : astropy.coordinates.SkyCoord
            The RA and Dec of the Sun at the given time, as a SkyCoord object.
        """

        if utctimes is None:
            utctimes = Time.now()
        if not isinstance(utctimes, Time):
            utctimes = Time(utctimes)
        return get_body("sun", utctimes)
    
    def sun_altaz(self,
                  utctimes : datetime or Time or np.array = None):
        """
        Calculates the altitude and azimuth of the Sun at the given time and location.

        Parameters
        ==========
        1. time : datetime or Time, optional
            The UTC time at which to calculate the altitude and azimuth of the Sun. If not provided, the current time is used.

        Returns
        =======
        1. sun_altaz : astropy.coordinates.AltAz
            The altitude and azimuth of the Sun at the given time and location, as an AltAz object.
        """

        if utctimes is None:
            utctimes = Time.now()
        if not isinstance(utctimes, Time):
            utctimes = Time(utctimes)
        return self._observer.sun_altaz(utctimes)
    
    def sun_risetime(self,
                     utctimes : datetime or Time or np.array = None,
                     mode = 'nearest',
                     horizon = -18):
        """
        Calculates the next rise time of the Sun at the given time and location.

        Parameters
        ==========
        1. time : datetime or Time, optional
            The UTC time at which to calculate the next rise time of the Sun. If not provided, the current time is used.
        2. mode : str, optional
            The method to use for calculating the rise time of the Sun. Can be either 'nearest' (default), 'next', or 'previous'.
        3. horizon : float, optional
            The horizon angle to use when calculating the rise time of the Sun. Default is -18 degrees.

        Returns
        =======
        1. sun_rise_time : astropy.time.Time
            The next rise time of the Sun at the given time and location, as a Time object.
        """

        if utctimes is None:
            utctimes = Time.now()
        if not isinstance(utctimes, Time):
            utctimes = Time(utctimes)
        return self._observer.sun_rise_time(utctimes, which = mode, horizon = horizon * u.deg)
    
    def sun_settime(self,
                    utctimes : datetime or Time or np.array = None,
                    mode = 'nearest',
                    horizon = -18):
        """
        Calculates the next rise time of the Sun at the given time and location.

        Parameters
        ==========
        1. time : datetime or Time, optional
            The UTC time at which to calculate the next set time of the Sun. If not provided, the current time is used.
        2. mode : str, optional
            The method to use for calculating the set time of the Sun. Can be either 'nearest' (default), 'next', or 'previous'.
        3. horizon : float, optional
            The horizon angle to use when calculating the set time of the Sun. Default is -18 degrees.

        Returns
        =======
        1. sun_set_time : astropy.time.Time
            The next set time of the Sun at the given time and location, as a Time object.
        """

        if utctimes is None:
            utctimes = Time.now()
        if not isinstance(utctimes, Time):
            utctimes = Time(utctimes)
        return self._observer.sun_set_time(utctimes, which = mode, horizon = horizon * u.deg)
    
    ############ Moon ############
    def moon_radec(self,
                   utctimes : datetime or Time or np.array = None):
        """
        Calculates the RA and Dec of the Moon at the given time and location.
        
        Parameters
        ==========
        1. time : datetime or Time, optional
            The UTC time at which to calculate the RA and Dec of the Moon. If not provided, the current time is used.

        Returns
        =======
        1. moon_radec : astropy.coordinates.SkyCoord
            The RA and Dec of the Moon at the given time, as a SkyCoord object.
        """

        if utctimes == None:
            utctimes = Time.now()
        if not isinstance(utctimes, Time):
            utctimes = Time(utctimes)
        #moon_coord_icrs = moon_radec_gcrs.transform_to('icrs')
        return get_body("moon", utctimes)
    
    def moon_altaz(self,
                   utctimes : datetime or Time or np.array = None):
        """
        Calculates the altitude and azimuth of the Moon at the given time and location.

        Parameters
        ==========
        1. time : datetime or Time, optional
            The UTC time at which to calculate the altitude and azimuth of the Moon. If not provided, the current time is used.

        Returns
        =======
        1. moon_altaz : astropy.coordinates.AltAz
            The altitude and azimuth of the Moon at the given time and location, as an AltAz object.
        """

        if utctimes is None:
            utctimes = Time.now()
        if not isinstance(utctimes, Time):
            utctimes = Time(utctimes)
            
        return self._observer.moon_altaz(utctimes) #self._moon_altaz(radec = get_moon(time), time = time)

    def moon_risetime(self,
                      utctimes : datetime or Time or np.array = None,
                      mode = 'nearest',
                      horizon = -18):
        """
        Calculates the next rise time of the Moon at the given time and location.

        Parameters
        ==========
        1. time : datetime or Time, optional
            The UTC time at which to calculate the next rise time of the Moon. If not provided, the current time is used.
        2. mode : str, optional
            The method to use for calculating the rise time of the Moon. Can be either 'nearest' (default), 'next', or 'previous'.
        3. horizon : float, optional
            The horizon angle to use when calculating the rise time of the Moon. Default is -18 degrees.

        Returns
        =======
        1. moon_rise_time : astropy.time.Time
            The next rise time of the Moon at the given time and location, as a Time object.
        """

        if utctimes is None:
            utctimes = Time.now()
        if not isinstance(utctimes, Time):
            utctimes = Time(utctimes)
        return self._observer.moon_rise_time(utctimes, which = mode, horizon = horizon * u.deg)
    
    def moon_settime(self,
                     utctimes : datetime or Time or np.array = None,
                     mode = 'nearest',
                     horizon = -18):
        """
        Calculates the next set time of the Moon at the given time and location.

        Parameters
        ==========
        1. time : datetime or Time, optional
            The UTC time at which to calculate the next set time of the Moon. If not provided, the current time is used.
        2. mode : str, optional
            The method to use for calculating the set time of the Moon. Can be either 'nearest' (default), 'next', or 'previous'.
        3. horizon : float, optional
            The horizon angle to use when calculating the set time of the Moon. Default is -18 degrees.

        Returns
        =======
        1. moon_set_time : astropy.time.Time
            The next set time of the Moon at the given time and location, as a Time object.
        """

        if utctimes is None:
            utctimes = Time.now()
        if not isinstance(utctimes, Time):
            utctimes = Time(utctimes)
        return self._observer.moon_set_time(utctimes, which = mode, horizon = horizon * u.deg)
    
    def moon_phase(self,
                   utctimes : datetime or Time or np.array = None):
        """
        Calculates the phase of the Moon at the given time and location.
        
        Parameters
        ==========
        1. time : datetime or Time, optional
            The UTC time at which to calculate the phase of the Moon. If not provided, the current time is used.

        Returns
        =======
        1. k : float
            Fraction of moon illuminated
        """
        
        if utctimes is None:
            utctimes = Time.now()
        if not isinstance(utctimes, Time):
            utctimes = Time(utctimes)
        return self._observer.moon_illumination(utctimes)
# %%
if __name__ == '__main__':
    import astropy.units as u
    obs = mainObserver()
# %%
