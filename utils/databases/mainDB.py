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
    Dynamic : DB_Dynamic
        An instance of the DB_Dynamic class updated at utctime.
    TOS : DB_Annual
        An instance of the DB_Annual class updated at utcdate.

    Methods
    -------
    update_Dynamic(utctime)
        Returns an instance of DB_Dynamic updated at utctime.
    update_TOS()
        Returns an instance of DB_Annual updated at utcdate.
    """
    
    def __init__(self,
                 utctime = Time.now()):
        super().__init__()
        self.Dynamic = self.update_Dynamic(utctime = utctime)
        self.TOS = self.update_TOS()
    
    def update_Dynamic(self, utctime):
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
        Dynamic = DB_Dynamic(utctime = utctime, tbl_name = 'Dynamic')
        return Dynamic

    def update_TOS(self):
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
        return DB_Annual(tbl_name = 'TOS')
# %%