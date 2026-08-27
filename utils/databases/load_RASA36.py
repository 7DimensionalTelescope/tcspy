#%%
from astropy.io import ascii
from astropy.table import Table
from tcspy.utils.connector.SQLconnector import SQLConnector

# %%
print("Connect to the target database...")
sql = SQLConnector(db_name = 'target', id_user = 'snu', pwd_user = 'astro19315')

#%% Read displaycenter.txt
print("Read displaycenter.txt...")
tbl = ascii.read('/home/snu/code/tcspy/utils/databases/tileinfo/RASA36/displaycenter.txt')
tbl.rename_column('id', 'objname')
tbl.rename_column('ra', 'RA')
tbl.rename_column('dec', 'De')
str_tile = tbl['objname']
objnames = []
for tilenum in str_tile:
    objname = 'T' + str(tilenum).zfill(5)
    objnames.append(objname)
tbl['objname'] = objnames
tbl = tbl[tbl['De'] < 21]

#%% Fill in remaining columns referenced by DB_Annual and DB_Dynamic
n = len(tbl)
tbl['exptime'] = ['60'] * n
tbl['count'] = ['5'] * n
tbl['filter_'] = ['r'] * n
tbl['binning'] = ['1'] * n
tbl['obsmode'] = ['Single'] * n
tbl['ntelescope'] = ['1'] * n
tbl['gain'] = ['25'] * n
tbl['obs_count'] = ['0'] * n
tbl['weight'] = ['1'] * n
tbl['priority'] = ['1000'] * n
tbl['note'] = [''] * n
tbl['objtype'] = ['TOS'] * n
tbl['is_ToO'] = ['0'] * n
tbl['is_rapidToO'] = ['0'] * n

#%% Delete existing RIS data and insert new data
print("Delete existing RIS data and insert new data...")
sql.execute("DELETE FROM TOS", commit=True)
sql.insert_rows(tbl_name='TOS', data=tbl)
sql.set_data_id('TOS')

#%% Populate risedate, bestdate, setdate
from tcspy.utils.databases.DB_annual import DB_Annual
print("Populate risedate, bestdate, setdate...")
tos = DB_Annual(tbl_name='TOS')
tos.initialize(initialize_all=True)

#%% Update specific column values
print("Update gain to 25...")
sql.execute("UPDATE TOS SET gain = '25'", commit=True)

# %%
print("Update specmode to NULL...")
sql.execute("UPDATE TOS SET specmode = NULL", commit=True)

# %%
