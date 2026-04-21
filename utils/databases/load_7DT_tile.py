#%%
from astropy.io import ascii
from astropy.coordinates import SkyCoord
import astropy.units as u
from utils.connector.SQLconnector import SQLConnector
# %%
sql = SQLConnector(db_name = 'target', id_user = 'hhchoi', pwd_user = 'gusgh1020!')
# %% 
from astropy.io import ascii
import uuid
#%% RIS
tbl = ascii.read('./sky-grid and tiling/7-DT/displaycenter.txt')
tbl.rename_column('id', 'objname')
tbl.rename_column('ra', 'RA')
tbl.rename_column('dec', 'De')
str_tile = tbl['objname']
objnames = []
for tilenum in str_tile:
    objname = 'T' + str(tilenum).zfill(5)
    objnames.append(objname)
tbl['objname'] = objnames
tbl = tbl[tbl['De'] < 20]
#%%
sql.initialize_tbl(tbl_name = 'RIS')
#%%
sql.insert_data(tbl_name = 'WFS', data = tbl)
# %% Update data
sql.update_data(tbl_name = 'RIS', update_value = 'observed', update_key='obs_status', id_value = id_)
observed_num = sql.select_data(tbl_name = 'RIS', select_key= 'obs_number', where_value = id_)['obs_number'][0]
sql.update_data(tbl_name = 'RIS', update_value = observed_num+1, update_key='obs_number', id_value = id_)
# %% Select data
id_data = sql.select_data(tbl_name = 'Daily', select_key = 'id')['id']
# %% Set ID
sql.set_data_id('Daily')
# %%
