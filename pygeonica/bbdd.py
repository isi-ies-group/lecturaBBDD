# -*- coding: utf-8 -*-
"""

@author: Martin
"""
import pyodbc
import pandas as pd
import datetime as dt
import yaml
import os
import pytz
from pathlib import Path

# En el servidor SQL hay que habilitar el puerto TCP del servidor y abrirlo en el firewall
# https://docs.microsoft.com/es-es/sql/relational-databases/lesson-2-connecting-from-another-computer?view=sql-server-ver15

module_path = os.path.dirname(__file__)

try: 
    with open(str(Path(module_path, 'bbdd_config.yaml')),'r') as config_file:
        config = yaml.load(config_file, Loader = yaml.FullLoader) #Se utiliza el FullLoader para evitar un mensaje de advertencia, ver https://msg.pyyaml.org/load para mas información
        servidor = config['Servidor']                             #No se utiliza el BasicLoader debido a que interpreta todo como strings, con FullLoader los valores numéricos los intrepreta como int o float
        bbdd = config['BBDD']
        del config                       

except yaml.YAMLError:
    print ("Error in configuration file")

SERVER_ADDRESS = servidor['IP']  # IP PC Ruben: '138.4.46.139'      IP PC Martin: '138.4.46.164'      IP PC Server: '138.4.46.69'
PORT = str(servidor['Puerto'])              
DDBB_name = bbdd['Database']
database = bbdd['Nombre']    #Nombre por defecto que se le asigna a la base de datos
username = bbdd['Usuario']            #Usuario por defecto
password = bbdd['Contrasena']            #Contraseña por defecto
    
    

# pyodbc.drivers() # lista de drivers disponibles
# ['SQL Server',
#  'SQL Server Native Client 11.0',
#  'ODBC Driver 11 for SQL Server']

# Instalar driver (si no está ya al instalar GEONICA SUITE 4K)
# https://www.microsoft.com/en-us/download/details.aspx?id=36434

def _request_ddbb(server_address = SERVER_ADDRESS):                                            #request común a todas las funciones
    request = (                                                         
            'DRIVER={ODBC Driver 11 for SQL Server};'                   ##Se seleccion el driver a utilizar
            # la ; hace que falle si hay más campos
            f'SERVER={server_address},{PORT}\{DDBB_name};'          ##Dirrección IP del servidor dónde se encuentre la base de datos 
            f'DATABASE={database};'                                     ##Nombre de la base de datos en la que se encuentran los datos
            f'UID={username};'                                          ##Usuario con el que se accede a la base de datos
            f'PWD={password}'                                           ##Contreseña de acceso a la base de datos
    )
    return request;


def get_data_raw(numero_estacion, fecha_ini, fecha_fin = dt.date.today().strftime('%Y-%m-%d %H:%M')):
    '''
    Se obtienen los datos en bruto de una estacion deseada, 
        estos datos incluyen todos las funciones que estén configuradas en la estación.

    '''
    request = _request_ddbb()
    
    query_data = (
            "SELECT * FROM Datos "
            "WHERE NumEstacion = " + str(numero_estacion) + " AND "
            "Fecha >= '" + fecha_ini + "' AND "
            "Fecha < '" + fecha_fin + "'"
    ) #Se solicitan las medidas, junto son su correspondiende NumParámetro, de un periodo determinado
    
    data_raw = pd.read_sql(query_data, pyodbc.connect(request))#Se construye el DataFrame con los valores pedidos a la base de datos
    
    return data_raw


def get_parameters():
    '''
    Mediante esta función se obtienen las funciones que están disponibles en la estacion,
        junto con su número de parametro y unidad.

    '''
    request = _request_ddbb()
    
    query_parameters = (
            'SELECT NumParametro, Nombre, Abreviatura, Unidad FROM Parametros_spanish '
    )
    
    data_parameters = (
            pd.read_sql(query_parameters, pyodbc.connect(request))
    )
    
    #parametros = data_parameters.set_index('NumParametro')
    return data_parameters
    

def get_channels_config(numero_estacion):
    '''
    Devuelve una lista de los canales configurasdos en la estación indicada,
    estos canales estan ordenados en el mismo orden en el que los deveulve la estación
    cuando se le solicita (mediante puerto Serie, conexión IP, etc. ) los datos de los canales.
    '''
    request = _request_ddbb()
    
    query_channels_config = (
            'SELECT Canales.NumFuncion, Canales.Canal, Parametros_spanish.Abreviatura, Parametros_spanish.NumParametro '
            'FROM Canales '
            'INNER JOIN Parametros_spanish ON Canales.NumParametro = Parametros_spanish.NumParametro '
            'INNER JOIN Funciones ON Funciones.NumFuncion = Canales.NumFuncion '
            'WHERE NumEstacion = ' + str(numero_estacion)
    )
    
    data_channels_config = (
            pd.read_sql(query_channels_config, pyodbc.connect(request))
     )
    
    data_channels_config.set_index('Canal', inplace = True)
    data_channels_config.sort_values(by = 'Canal', inplace= True)
    canales = data_channels_config.drop_duplicates(subset='Abreviatura').reset_index().drop(columns='Canal')
    return canales

def get_functions():
    '''
    Devuelve una lista con el número correspondiente a la función.
    '''
    
    request = _request_ddbb()
    
    query_functions = (
            'SELECT NumFuncion, Nombre FROM dbo.Funciones_MI '
            'WHERE Ididioma = 1034' #Se solicita en nombre de las funciones en español; 2057, para inglés
    )   
    
    funciones = (
            pd.read_sql(query_functions, pyodbc.connect(request))
    )
    
    funciones.set_index('NumFuncion', inplace = True)
    return funciones


def lee_dia_geonica_ddbb(dia, numero_estacion, lista_campos=None):
    #    INPUT:    dia (datetime.date)
    #            lista_campos (lista con campos a obtener de la BBDD)
    #    OUTPUT:    datos (pandas.DataFrame)
    #    CONFIG:    numero_estacion
    #            path_mdb, fichero_mdb
    #            driver

    #Si el usuario no especifica ninguna lista de campos deseados, por defecto de le devuelven todos los canales
    # disponibles de la estación
    if lista_campos == None:
        lista_campos = ['yyyy/mm/dd hh:mm']
        canales = get_channels_config(numero_estacion)['Abreviatura'].tolist()
        lista_campos += canales
    
    dia_datetime = dt.datetime.combine(dia, dt.datetime.min.time())
    formato_tiempo = '%Y-%m-%d %H:%M'
    
    # Como se lee hora UTC y la civil necesita de valores del día anterior, se leen minutos del día anterior
    # El dataset tiene 1 día + 2 horas, que luego al convertir a hora civil se tomarán solo los minutos del día en cuestión
    fecha_ini = (dia_datetime - dt.timedelta(hours=2)).strftime(formato_tiempo)
    fecha_fin = (dia_datetime + dt.timedelta(hours=24)).strftime(formato_tiempo)
                                                    
    # https://docs.microsoft.com/es-es/sql/relational-databases/lesson-2-connecting-from-another-computer?view=sql-server-ver15
    
    data = get_data_raw(numero_estacion, fecha_ini, fecha_fin)
    
    # Se procesa data solo si hay contenido
    if len(data) != 0:
        # dict_estacion tiene como indice el numero_estacion y contenido 'nombre_parametro_ficheros' y 'mtype'
        # nombre, mtype
        #   'mtype'     Measurement type: Enter an integer to determine which
        #               information on each one minute interval to return.  Options are.
        #               0       1   2   3   4   5
        #               Ins.    Med Acu Int Max Min
               
        dict_estacion = get_channels_config(numero_estacion).set_index('NumParametro');
           
        def tipo_medida(d):
            try:
                return dict_estacion.loc[d]['NumFuncion']
            except:
                pass        
            
        # Selecciona las filas que tienen NumFuncion == el tipo de medida dado el NumParametro
        data = data[data['NumFuncion'] ==
                    data['NumParametro'].apply(tipo_medida)]

        # Conversion de parametros en filas a columnas del Dataframe
        data = data.pivot_table(index='Fecha', columns=[
                                'NumParametro'], values='Valor')

        # Si los valores son medias (mtype==1), sería el valor de hace 30 seg. Por lo tanto se toma el que realmente le corresponde.
        # samplea cada 30seg, se interpola para que haya valor, se desplazan los valores 30seg para cuadrar y se reajusta de nuevo con el indice original.
        
        def adapta(columna):
            try:
                #if dict_estacion[columna.name][1] == 1: Se sustituye por:
                if dict_estacion.loc[columna.name]['NumFuncion'] == 1:
                    return columna.resample('30S').interpolate(method='linear').shift(periods=-30, freq='S').reindex(data.index)
                else:
                    return columna
            except:
                pass

        data = data.apply(adapta, axis=0)
        # El ultimo valor si se ha ajustado, se queda en NaN. Se arregla tomando el penultimo + diff
        data.iloc[-1] = data.iloc[-2] + (data.diff().mean())

        # Cambia codigo NumParametro de BBDD a su nombre de fichero
        
        data_channels = get_parameters().set_index('NumParametro') #Se obtienen los números de los parámetros...
        data.rename(columns = data_channels['Abreviatura'], inplace=True) #... y se sustituye el NumParametro por el Nombre
        
    # cambia index a hora civil
    data.index = (data.index.tz_localize(pytz.utc).
                  tz_convert(pytz.timezone('Europe/Madrid')).
                  tz_localize(None))
    
    # filtra y se queda solo con los minutos del dia en cuestion, una vez ya se han convertido a hora civil
    data = data[str(dia)]
    
    # Si data está vacio, se crea con valores NaN
    indice_fecha = pd.Index(pd.date_range(
        start=dia, end=dt.datetime.combine(dia, dt.time(23, 59)), freq='1T'))
    if len(data) == 0:
        data = pd.DataFrame(index=indice_fecha, columns=lista_campos)

    # En caso de que el indice esté incompleto, se reindexa para que añada nuevos con valores NaN
    if len(data) != len(indice_fecha):
        data = data.reindex(index=indice_fecha)

    # En caso de que el columns esté incompleto, se reindexa para que añada nuevos con valores NaN

    lista_campos_corta = lista_campos.copy()
    lista_campos_corta.remove('yyyy/mm/dd hh:mm')
    # lista_campos_corta.remove('yyyy/mm/dd')
    if set(lista_campos_corta).issuperset(data.columns):
        data = data.reindex(columns=lista_campos)
    
    # # Separa y crea en 2 columnas fecha y hora
    # # tambien valdría data.index.strftime('%Y/%m/%d')
    # data['yyyy/mm/dd'] = [d.strftime('%Y/%m/%d') for d in data.index]
    # data['hh:mm'] = [d.strftime('%H:%M') for d in data.index]
    data['yyyy/mm/dd hh:mm'] = [d.strftime('%Y/%m/%d %H:%M') for d in data.index]

    return data
