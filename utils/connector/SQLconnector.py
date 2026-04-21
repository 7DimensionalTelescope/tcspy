
#%%
import mysql.connector
from mysql.connector import pooling, Error
from astropy.table import Table
import uuid
import numpy as np

class SQLConnector:
    def __init__(self,
                 id_user: str = 'snu',
                 pwd_user: str = 'astro19315',
                 host_user: str = 'localhost',
                 db_name: str = 'target',
                 pool_name: str = 'mypool',
                 pool_size: int = 16):
        self.id_user = id_user
        self.pwd_user = pwd_user
        self.host_user = host_user
        self.db_name = db_name

        # Set up connection pooling
        self.pool = mysql.connector.pooling.MySQLConnectionPool(
            pool_name=pool_name,
            pool_size=pool_size,
            pool_reset_session=True,
            host=self.host_user,
            user=self.id_user,
            password=self.pwd_user,
            database=self.db_name
        )

    def __repr__(self):
        return f"MySQL(DB = {self.db_name}, Address = {self.id_user}@{self.host_user})"

    def connect(self):
        """Get a connection from the pool"""
        return self.pool.get_connection()

    def disconnect(self):
        """Close all connections in the pool and release resources."""
        self.pool = None  # Remove reference to the pool to allow for cleanup
        print("Connection pool has been closed.")

    def execute(self, sql_command, params=None, commit=False):
        conn = self.connect()
        cursor = conn.cursor(buffered=True)
        try:
            cursor.execute(sql_command, params)
            if commit:
                conn.commit()
            
            # Fetch results immediately if it is a selection query
            result = None
            if cursor.description: # Checks if the query returns rows (like SELECT)
                result = cursor.fetchall()
            else:
                result = True # For successful INSERT/UPDATE/CREATE
            return result
        except Error as e:
            conn.rollback()
            print(f"Error: {e}")
            return None
        finally:
            cursor.close()
            conn.close()

    # def execute(self, sql_command, params=None, commit=False):
    #     conn = self.connect()
    #     cursor = conn.cursor(buffered=True)
    #     try:
    #         cursor.execute(sql_command, params)
    #         if commit:
    #             conn.commit()
    #         return cursor
    #     except Error as e:
    #         conn.rollback()
    #         print(f"Error: {e}")
    #         return None
    #     finally:
    #         cursor.close()
    #         conn.close()

    @property
    def databases(self):
        # cursor = self.execute("SHOW DATABASES")
        # return [db_name[0] for db_name in cursor] if cursor else []
        results = self.execute("SHOW DATABASES")
        return [db_name[0] for db_name in results] if results else []


    def change_db(self, db_name: str):
        self.db_name = db_name
        self.pool = mysql.connector.pooling.MySQLConnectionPool(
            pool_name=self.pool.pool_name,
            pool_size=self.pool.pool_size,
            pool_reset_session=True,
            host=self.host_user,
            user=self.id_user,
            password=self.pwd_user,
            database=self.db_name
        )

    def create_db(self, db_name: str):
        self.execute(f"CREATE DATABASE {db_name}", commit=True)

    def remove_db(self, db_name: str):
        self.execute(f"DROP DATABASE {db_name}", commit=True)

    @property
    def tables(self):
        cursor = self.execute(f"SHOW TABLES")
        return [tbl_name[0] for tbl_name in cursor] if cursor else []

    def remove_tbl(self, tbl_name: str):
        self.execute(f"DROP TABLE {tbl_name}", commit=True)

    # def get_colnames(self, tbl_name: str):
    #     cursor = self.execute(f"SHOW COLUMNS FROM {tbl_name};")
    #     return [column[0] for column in cursor.fetchall()] if cursor else []

    def get_colnames(self, tbl_name: str):
        # self.execute now returns the list of rows (fetchall result) directly
        rows = self.execute(f"SHOW COLUMNS FROM {tbl_name};")
        return [column[0] for column in rows] if rows else []

    # def get_column_data_types(self, tbl_name: str):
    #     cursor = self.execute(f"SHOW COLUMNS FROM {tbl_name}")
    #     column_info = cursor.fetchall() if cursor else []
    #     return {col[0]: col[1] for col in column_info}

    def get_column_data_types(self, tbl_name: str):
        column_info = self.execute(f"SHOW COLUMNS FROM {tbl_name}")
        if not column_info: return {}
        return {col[0]: col[1] for col in column_info}

    def remove_rows(self, tbl_name: str, ids: list or str):
        if isinstance(ids, str):
            ids = [ids]
        id_list = ', '.join([f"'{id_}'" for id_ in ids])
        self.execute(f"DELETE FROM {tbl_name} WHERE id IN ({id_list})", commit=True)

    def insert_rows(self, tbl_name: str, data: Table):
        data_str = data.copy()
        for colname in data_str.columns:
            data_str[colname] = data_str[colname].astype(str)
        if 'idx' in data_str.keys():
            data_str.remove_column('idx')

        common_colnames = [col for col in data_str.colnames if col in self.get_colnames(tbl_name)]
        placeholders = ', '.join(['%s'] * len(common_colnames))
        sql_command = f"INSERT INTO {tbl_name} (`{'`, `'.join(common_colnames)}`) VALUES ({placeholders})"
        values = [tuple(row[col] if row[col] != ('None' and '') else None for col in common_colnames) for row in data_str]

        insertion_results = []
        for value in values:
            cursor = self.execute(sql_command, value, commit=True)
            insertion_results.append(cursor is not None)
        return insertion_results

    def update_row(self, tbl_name: str, update_value: list or str, update_key: list or str, id_value: list or str, id_key: list or str = ['id']):
        def convert_value(val):
            if isinstance(val, (np.integer, np.int64)):
                return int(val)
            elif isinstance(val, (np.floating, np.float64)):
                return float(val)
            return val

        # Handle single or multiple id_keys and id_values
        if isinstance(id_key, str):
            id_key = [id_key]
        if isinstance(id_value, str):
            id_value = [id_value]
            #where_clause = f"{id_key} = '{id_value}'"
        if isinstance(id_key, list) and isinstance(id_value, list) and len(id_key) == len(id_value):
            where_clause = ' AND '.join([f"{key} = %s" for key in id_key])
        else:
            raise ValueError("id_key and id_value must both be strings or lists of the same length.")

        if isinstance(update_value, (str, np.int64, np.float64, np.integer, np.floating)):
            update_command = f"{update_key} = '{update_value}'"
            sql_command = f"UPDATE {tbl_name} SET {update_command} WHERE {where_clause}"
            cursor = self.execute(sql_command, id_value if isinstance(id_value, list) else [id_value], commit=True)
            return cursor is not None
        else:
            update_command = ', '.join([f"{key} = %s" for key in update_key])
            sql_command = f"UPDATE {tbl_name} SET {update_command} WHERE {where_clause}"
            value_None = tuple(None if val in ('None', '') else val for val in update_value)
            value = tuple(convert_value(val) for val in value_None)
            # Combine update values with id values for the placeholders
            all_values = value + (tuple(id_value) if isinstance(id_value, list) else (id_value,))
            cursor = self.execute(sql_command, all_values, commit=True)
            return cursor is not None

    def get_data(self, tbl_name: str, select_key: str = '*', where_value: str = None, where_key: str = 'id', out_format: str = 'Table'):
        keys = select_key.split(',')
        if select_key == '*':
            keys = self.get_colnames(tbl_name=tbl_name)
        len_key = len(keys)
        sql_command = f"SELECT {select_key} FROM {tbl_name}"
        if where_value:
            sql_command = f"SELECT {select_key} FROM {tbl_name} WHERE {where_key} = '{where_value}'"
        # cursor = self.execute(sql_command)
        # output = cursor.fetchall() if cursor else []
        output = self.execute(sql_command)
        if output is None: output = []
        if out_format.lower() == 'table':
            result = Table()
        else:
            result = dict()
        if len_key == 1:
            result[keys[0]] = [out[0] for out in output]
        else:
            for i, key in enumerate(keys):
                result[key] = [out[i] for out in output]
        return result

    def set_data_id(self, tbl_name: str, update_all: bool = False):
        values_all = self.get_data(tbl_name=tbl_name, select_key='id,idx')
        values_to_update = values_all
        if not update_all:
            rows_to_update = [any(row[name] in (None, '') for name in ['id']) for row in values_all]
            values_to_update = values_all[rows_to_update]
        uuidlist = [uuid.uuid4().hex for _ in range(len(values_to_update))]

        for id_, index in zip(uuidlist, values_to_update['idx']):
            self.update_row(tbl_name=tbl_name, update_value=id_, update_key='id', id_value=str(index), id_key='idx')
  
    def pool_status(self):
        """Check the status of the connection pool"""
        print(f"Pool size: {self.pool.pool_size}")
        #print(f"Connections in pool: {len(self.pool.get_connection())}")
        #print(f"Connections in use: {pool.pool_size - len(pool._idle_cache)}")
# %%
if __name__ == '__main__':
    self = SQLConnector()
    from astropy.table import Table
    tbl = Table()
    tbl['objname'] = ['Test']
    tbl['RA'] = 10
    tbl['De'] = - 20
    tbl['exptime'] = 3
    tbl['count'] = 3
    tbl['obsmode'] = 'Single'
    self.insert_rows('Dynamic', tbl)

# %%
