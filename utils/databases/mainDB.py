#%%
from astropy.time import Time
from tcspy.utils.databases import *
from tcspy.configuration import mainConfig
#%%
class DB(mainConfig):
    """
    A class used to handle actions with the database.

    Parameters
    ----------
    utctime : Time
        Representing the current time.

    Attributes
    ----------
    Daily : DB_Dynamic
        An instance of the DB_Dynamic class updated at utctime.
    RIS : DB_Annual
        An instance of the DB_Annual class updated at utcdate.

    Methods
    -------
    update_Daily(utctime)
        Returns an instance of DB_Dynamic updated at utctime.
    update_RIS(utcdate)
        Returns an instance of DB_Annual updated at utcdate.
    """
    
    def __init__(self,
                 utctime = Time.now()):
        super().__init__()
        self.Daily = self.update_Daily(utctime = utctime)
        self.RIS = self.update_RIS()
    
    def update_Daily(self, utctime):
        """
        Returns an instance of DB_Dynamic updated at utctime.

        Parameters
        ----------
        utctime : Time
            Representing the current time.

        Returns
        -------
        DB_Dynamic
            An instance of the DB_Dynamic class updated at utctime.
        """
        Daily = DB_Dynamic(utctime = utctime, tbl_name = 'Daily')
        return Daily

    def update_RIS(self):
        """
        Returns an instance of DB_Annual updated at utcdate.

        Parameters
        ----------
        utcdate : Time
            Representing the current time.

        Returns
        -------
        DB_Annual
            An instance of the DB_Annual class updated at utcdate.
        """
        return DB_Annual(tbl_name = 'RIS')
# %%