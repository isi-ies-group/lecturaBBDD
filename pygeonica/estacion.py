# -*- coding: utf-8 -*-
"""
Created on Mon Mar 16 09:12:36 2020

@author: Martin
"""

import serial
import socket
import time
import datetime as dt
import struct
import yaml
import os
from pathlib import Path


###########################################################################################################
####
####        EXTRACCIÓN DE VARIABLES GLOBALES DEL FICHERO DE CONFIGURACIÓN
####
###########################################################################################################

module_path = os.path.dirname(__file__)

try: 
    with open(str(Path(module_path, 'estacion_config.yaml')),'r') as config_file:
        config = yaml.load(config_file, Loader = yaml.FullLoader) #Se utiliza el FullLoader para evitar un mensaje de advertencia, ver https://msg.pyyaml.org/load para mas información
                                                                     #No se utiliza el BasicLoader debido a que interpreta todo como strings, con FullLoader los valores numéricos los intrepreta como int o float

except yaml.YAMLError:
    print ("Error in configuration file\n")
    
#Asignacion de valores a variables globales
Estaciones = []
for num in config['Estaciones'].split(','):
    Estaciones.append(int(num))
    
BYTEORDER = config['BYTEORDER']
PASS = config['PASS']
NUMERO_ESTACION = config['NUMERO_ESTACION']
NUMERO_USUARIO = config['NUMERO_USUARIO']
PORT = config['PORT']
TIEMPO_RTS_ACTIVO = config['TIEMPO_RTS_ACTIVO'] 
TIEMPO_ESPERA_DATOS = config['TIEMPO_ESPERA_DATOS']

###########################################################################################################
####
####        FUNCIONES INTERNAS DEL PROTOCOLO GEONICA
####
###########################################################################################################


def __cabecera(numero_estacion):  #La cabecera de todos los mensajes recibidos por el sistema de medición
    DLE = bytes(chr(16), encoding='ascii')                  #Data Link Escape
    SYN = bytes(chr(22), encoding='ascii')                  #Syncronos Idle
    SOH = bytes(chr(1), encoding='ascii')                   #Start of Heading
    E = numero_estacion.to_bytes(2, byteorder=BYTEORDER)    #Numero de la estacion de la que se reciben los datos
    U = NUMERO_USUARIO.to_bytes(2, byteorder=BYTEORDER)     #Numero del usuario que ha solicitado los datos
    #C = b'\x00'                                            #Número de comando que se ha solicitado
    
    CABECERA = DLE + SYN + DLE + SOH + E + U #+ C
    return CABECERA


def __comprobar_recepcion(trama_bytes, numero_estacion): #Se obtiene un booleano( o un entero) indicando si se ha producido algun error:
                                                                              # True: Recepcion correcta
                                                                              # False: Recepcion de bytes incorrecta
                                                                              # Entero: Indica el codigo del error producido (Mirar página 9 del Protocolo de comunicaciones de Geonica Meteodata 3000)
    trama = bytearray(trama_bytes)
    bytes_recibidos = len(trama)
    estado = bool()
    
    if bytes_recibidos == 13:                                           #Respuesta indicando sincronizacion completada o error en la comunicación
        if trama[:8] == __cabecera(numero_estacion, NUMERO_USUARIO):          #Comporbación de que la cabecera recibida es la correcta
            if (trama[11] == 4):                                                #Bits indicando el fin de la transmisión, sincronización completada
                estado = True                                                         #Se devuelve un booleano indicando sincronización completada
            elif (trama[11] == 21):                                             #Error en la sincronización
                return int.from_bytes(trama[10])                                    #Se devuelve el indicador del estado del error            
    elif bytes_recibidos == 193:            #Respuesta indicando las mediciones pedidas
        if trama[:8] == __cabecera(numero_estacion, NUMERO_USUARIO):          #Comporbación de que la cabecera recibida es la correcta
                estado = True
    else:
        estado = False                                                    #Estado de error
        
    return estado


def __visulizar_trama(trama_bytes):
    '''
    Este método decodifica la trama recibida de la estación, el caso expuesto a continución se produce cuando se
    solicitan los valores intanstáneos de la estación. En el caso de que se soliciten otro tipo de valores, 
    los bytes del 117(trama_bytes[116]) al 188(trama_bytes[187]) no contienen ninguna información relevante.
    '''
    
    trama = []
    #CABECERA
    trama.append(trama_bytes[0])                                                        #Data Link Escape
    trama.append(trama_bytes[1])                                                        #Syncronos Idle
    trama.append(trama_bytes[2])                                                        #Data Link Escape
    trama.append(trama_bytes[3])                                                        #Start of Heading
    trama.append(int.from_bytes(trama_bytes[4:6], byteorder = BYTEORDER))               #Número de
    trama.append(int.from_bytes(trama_bytes[6:8], byteorder = BYTEORDER))               #   estación
    trama.append(trama_bytes[8])                                                        #Comando solicitado
    trama.append(int.from_bytes(trama_bytes[9:11], byteorder = BYTEORDER))              #Longitud de bytes de datos a entregar
    trama.append(trama_bytes[11])                                                       #Número de canales configurados
    trama.append(trama_bytes[12])                                                       #Año...
    trama.append(trama_bytes[13])                                                       #Mes...
    trama.append(trama_bytes[14])                                                       #Día...
    trama.append(trama_bytes[15])                                                       #Hora...
    trama.append(trama_bytes[16])                                                       #Minuto...
    trama.append(trama_bytes[17])                                                       #Segundo de la estación
    trama.append(trama_bytes[18])                                                       #Data Link Escape
    trama.append(trama_bytes[19])                                                       #Start of Text
    trama = trama + __decodificar_medidas(trama_bytes)                                  #Datos recibidos de los canales, y codificados en formato flotante IEEE 754 32bit(4 bytes por dato)
    
    lista1 = []                                                                         
    for i in range(48 - 1):                                                             #Número de muestra correspondiente desde el incio del perido
        inicio = 116 + i                                                                #de cálculo
        lista1.append(int.from_bytes(trama_bytes[inicio:(inicio + 2)], byteorder = BYTEORDER))
    trama.append(lista1)
    
    lista2 = []
    for i in range(24 - 1):                                                             #Indicador del estado del canal:
        lista2.append(trama_bytes[164 + i])                                             # 0:Normal 1:Alarma por umbral superior 2:Alarma por umbral inferior
    trama.append(lista2)
        
    trama.append(trama_bytes[188])                                                      #Data Link Escape
    trama.append(trama_bytes[189])                                                      #Enf of Text
    trama.append(bytearray(trama_bytes[190:192]))                                       #Checksum, equivale al XOR de los bytes pares e impares de datos, por separado; para más info ver página 11 protocolo de comunicaciones geonica
    trama.append(trama_bytes[192])                                                      #Enquiring
    
    return trama


def __genera_trama(numero_estacion, comando, hora = dt.datetime.now()):
    if type(comando) == int: #Se pide una medida
        DLE = bytes(chr(16), encoding='ascii')
        SYN = bytes(chr(22), encoding='ascii')
        E = numero_estacion.to_bytes(2, byteorder=BYTEORDER)
        comando_sinc = bytes(chr(1), encoding='ascii') # 1: codigo sync petición de medidas instantáneas
        U = NUMERO_USUARIO.to_bytes(2, byteorder=BYTEORDER)
        X = 14 * b'\x00'
        ctrl = b'\xFF' +  b'\xFF'# Verificación de la configuración (CRC16, standard ITU-TSS) 0xFFFF evita verificación
        pasw = bytes(PASS, encoding='ascii')
        ENQ = bytes(chr(5), encoding='ascii')
        
        trama = DLE + SYN + E + comando_sinc + U + X + ctrl + pasw + ENQ
    
    else: #En caso de que sea cualquier otra cosa, se sinroniza la hora
        DLE = bytes(chr(16), encoding='ascii')
        SYN = bytes(chr(22), encoding='ascii')
        E = numero_estacion.to_bytes(2, byteorder=BYTEORDER)
        comando_sinc = bytes(chr(0), encoding='ascii') # 0: codigo sync hora
        U = NUMERO_USUARIO.to_bytes(2, byteorder=BYTEORDER)
        A = (hora.year - 2000).to_bytes(1, byteorder=BYTEORDER)        
        M = hora.month.to_bytes(1, byteorder=BYTEORDER)
        D = hora.day.to_bytes(1, byteorder=BYTEORDER)
        d = hora.isoweekday().to_bytes(1, byteorder=BYTEORDER)
        H = hora.hour.to_bytes(1, byteorder=BYTEORDER)
        m = hora.minute.to_bytes(1, byteorder=BYTEORDER)
        s = hora.second.to_bytes(1, byteorder=BYTEORDER)
        X = 7 * b'\x00'
        ctrl = b'\xFF' +  b'\xFF'# Verificación de la configuración (CRC16, standard ITU-TSS) 0xFFFF evita verificación
        pasw = bytes(PASS, encoding='ascii')
        ENQ = bytes(chr(5), encoding='ascii')
        
        trama = DLE + SYN + E + comando_sinc + U + A + M + D + d + H + m + s + X + ctrl + pasw + ENQ
        
    #Se devuelve a trama que se debe enviar
    return trama


def __decodificar_medidas(trama_bytes):
    trama = bytearray(trama_bytes)
    medidas = []
    canales_configurados = trama_bytes[11]                    #Bytes indicando el numero de canales configurados
    
    for i in range(canales_configurados):                          
        byte_comienzo_muestra = 20 + (4 * i)                                  #Comienzo de los bytes de datos
        byte_fin_muestra = byte_comienzo_muestra + 4                         #Longitud de cada muestra de 4bytes
        medidas.append(trama[byte_comienzo_muestra:byte_fin_muestra])   #Se añade a la lista de medidas la medida del siguiente canal   
    
    #Se pasa de la codificacion IEEE32bit a float
    valor = []
    for medida in medidas:                                #Se atraviese el array 
        valor.append(struct.unpack('>f', medida)[0])           #Por cada canal configurado, se transforma a float la medicion, actualmente codificado en IEEE 754 32bit
    
    return valor


def __decodificar_FechayHora(trama_bytes):
    #class datetime.datetime(year, month, day, hour=0, minute=0, second=0, microsecond=0, tzinfo=None, *, fold=0)  #Constructor de la clase datetime
    date = dt.datetime(trama_bytes[12] + 2000, trama_bytes[13], trama_bytes[14], trama_bytes[15], trama_bytes[16], trama_bytes[17])
    
    '''
    La trama contiene la siguiente información:
    
    date.day = trama_bytes[14]
    date.month = trama_bytes[13]
    date.year = trama_bytes[12] + 2000                  #Se le suma 2000, ya que la estación solo se almacena la centena en la que nos encontramos
    
    date.hour = trama_bytes[15]
    date.minute = trama_bytes[16]
    date.second = trama_bytes[17]
    '''
    
    return date



###########################################################################################################
####
####        FUNCIONES INTERNAS DE COMUNICACIÓN
####
###########################################################################################################


def __socket(dir_socket, trama, num_bytes):
    '''

    Parameters
    ----------
    dir_socket : string
        La dirrección IP de la estación
    trama : bytearray
        La trama que se desea enviar
        
    Returns
    -------
    lectura : bytearray
        La lectura de la estación en bruto

    '''
    
    #Se crear el scoket y se conceta con la estación
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('',0))
        sock.connect(dir_socket)
    except:
        print('Error en la creación/conexión del socket.\n')
        return -1
    
    #Se envía la trama a la estación
    sock.sendall(trama)
    
    #Se espera hasta que se reciban el numero de bytes deseados
    try:
        sock.settimeout(5 * TIEMPO_ESPERA_DATOS)
        lectura = sock.recv(num_bytes)
    except:
        print('Tiempo de espera de datos sobrepasado.\n')
        return -1
    try:
        sock.close()
    except:
        print('Error al cerrar el socket.\n')
    
    #Se devuelve la lectura obtenida
    return lectura


def __serial(dir_serial, trama):
    '''

    Parameters
    ----------
    dir_serial : string
        La dirrección del puerto serie por el 
        cual se va a producir la comunicación con la estación

    Returns
    -------
    lectura : bytearray
        La lectura de la estación en bruto

    '''
    #Se confiura y abre el puerto serie
    try:
        ser = serial.Serial(
                    port=dir_serial,
                    baudrate=57600,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    bytesize=serial.EIGHTBITS
                    )
    except:
        print('Error en la aperura del puerto serie.\n')
        return -1
    
    # Debe activarse la linea RTS 1seg. antes del envio para que el dispositivo se prepare, si esta en modo ahorro,
    ## Mantener nivel alto durante 100ms y descactivar es suficiente  Referencia: Protocolo de comunicaciones Geonica Meteodata 3000 Página 3 Apartado 2.a.ii
    ser.rts = True
    time.sleep(TIEMPO_RTS_ACTIVO)
    ser.rts = False
    
    #Se escribe en el buffer de salida la trama deseada y se espera un tiempo para que la estación responda
    ser.write(trama)      
    time.sleep(TIEMPO_ESPERA_DATOS)
    
    #Se lee el buffer de entrada donde debería estar la informacion recibida
    lectura = ser.read_all()
    ser.close()
    
    #Se devuelve la lectura obtenida
    return lectura



###########################################################################################################
####
####        INTERFAZ DE USUARIO
####
###########################################################################################################


def lee_canales_estacion(num_estacion = NUMERO_ESTACION, modo_comm='socket', dir_socket=None, dir_serie=None, modo=1):
    '''

    Parameters
    ----------
    num_estacion : int, opcional
        Por defecto es NUMERO_ESTACION.
    modo_comm : str, opcional
        Por defecto es 'socket'.
    dir_socket : str, opcional
        Por defecto es None.
    dir_serie : str, opcional
        Por defecto es None.
    modo : int, optional
        Indica el tipo de medidas que se quieren leer:
            12 (Valores tendentes)
            13 (Instantáneo)
            14 (Medio)
            15 (Acumulado)
            16 (Integrado)
            17 (Máximo)
            18 (Mínimo)
            19 (Desviación estándar)
            20 (Incremento)
            21 (Estado alarma)
            22 (Operación OR de todos los valores)
        Por defecto es 1(Medidas instantáneas).

    Returns
    -------
    info : list
        DESCRIPTION.

    '''
    
    #Se define la trama que se va a enviar, en función de la información deseada
    if (modo == 1) | ((modo >= 12) & (modo <= 22)):
        trama = __genera_trama(num_estacion, modo)
    else:
        print('Error en el modo seleccionado.\n')
        return -1
    
    
    #Se comprueba que la estación pertenece a las estaciones existentes
    if not num_estacion in Estaciones:
        print('Error en la selección de la estación, número de estación incorrecto.\n')
        return -1
    
    #Se compruba el modo de comunicación
    if modo_comm.lower() == 'socket':
        #Se comprueba que dir_socket es válido
        if not(dir_socket == None) & (type(dir_socket) == str):
            #Se comprueba que la dirrecion tiene un formato adecuado
            for num in dir_socket.split('.'):
                if (num < 0) | (num > 255):
                    print('Error en el formato de la dirrección IP.\n')
                    return -1
            
            num_bytes = 193 #Según el protocolo de geonica, la trama recibida por la estacion es de 193 bytes (Esto no se cumple si se solicita sincronización de hora)
           
            #Una vez hechas las comprbaciones, comienza la comunicación
            lectura = __socket((dir_socket, str(PORT)), trama, num_bytes)
            
            #Lectura errónea
            if lectura == -1:
                return -1
            
        else:
            print('Por favor, indique una dirreción IP.\n')
            return -1
        
    elif modo_comm.lower() == 'serial':
        #Se comprueba que dir_serie es válido
        if not(dir_serie == None) & (type(dir_socket) == str):
            #Se compruba que la dirrecion tiene un formato adecuado
            with str.upper().split('M') as puerto:
                cond_tipo = (puerto[0].isalpha() & puerto[1].isdigit()) 
                cond_formato = len(puerto) == 2
                if (not cond_tipo) | (not cond_formato):
                    print('Error en el formato de la dirrección de puerto serie.\n')
                    return -1
            
            #Una vez hechas las comprbaciones, comienza la comunicación
            lectura = __serial(dir_serie,trama)
            
            #Lectura errónea
            if lectura == -1:
                return -1
            
        else:
            print('Por favor, indique una dirreción de puerto serie.\n')
            return -1
    else:
        print('Error en la selección del modo de comunicación, modo no válido.\n')
        return -1
    
    #Tratamiento de la lectura de la estación
    
    #Se comprueba si la transmisión ha sido correcta
    estado_recepcion = __comprobar_recepcion(lectura, num_estacion)
    
    '''
    En caso de que se produzca un error, se devuelve el número del error
    Si el estado de la recepcion es correcto se devuelve un True
    En cualquier otro caso, p.ej. el número de bytes recibidos no es el esperado, el valor devuelto es un False
    ''' 
    if estado_recepcion != True:
        print("Error en la comunicacion con la estación.\n")
        return estado_recepcion
    
    #Si hay algo que leer...
    if lectura:
        #Obtencion de la fecha de la estación
        fecha = __decodificar_FechayHora(lectura)
        print('La fecha de la estación es: ')
        print(fecha + '\n')
        
        #Obtencion de las medidas instantáneas
        medidas = __decodificar_medidas(lectura)
        # print('Las medidas obtenidas son:\n')
        # print(medidas + '\n')
        
    else:
        print("Error en la recepción.\n")
        return -1
    
    #Al finalizar la comunicación, se devuelve la fecha y las medidas obtenidas
    return [fecha, medidas]


def sincronizar_estacion(num_estacion = NUMERO_ESTACION, modo_comm='socket', dir_socket=None, dir_serie=None, hora=dt.datetime.now()):
    '''

    Parameters
    ----------
    num_estacion : str, opcional 
        Por defecto es NUMERO_ESTACION.
    modo_comm : str, opcional
        Por defecto es 'socket'.
    dir_socket : str, opcional
        Por defecto es None.
    dir_serie : str, opcional
        Por defecto es None.
    hora : dt.datetime, opcional
        Por defecto es la hora actual.
    Returns
    -------
    esatdo_recepcion
        Devuelve True si se ha sincronizado la hora o
        el número del error recibido.

    '''
    
    #Se define la trama que se va a enviar, en función de la información deseada
    trama = __genera_trama(num_estacion, None, hora)
    
    #Se comprueba que la estación pertenece a las estaciones existentes
    if not num_estacion in Estaciones:
        print('Error en la selección de la estación, número de estación incorrecto.\n')
        return -1
    
    #Se compruba el modo de comunicación
    if modo_comm.lower() == 'socket':
        #Se comprueba que dir_socket es válido
        if not(dir_socket == None) & (type(dir_socket) == str):
            #Se comprueba que la dirrecion tiene un formato adecuado
            for num in dir_socket.split('.'):
                if (num < 0) | (num > 255):
                    print('Error en el formato de la dirrección IP.\n')
                    return -1     
                
            num_bytes = 13 #Según el protocolo de geonica, la trama recibida por la estacion es de 13 bytes
            #Una vez hechas las comprbaciones, comienza la comunicación
            lectura = __socket((dir_socket, str(PORT)), trama, num_bytes)
            
            #Lectura errónea
            if lectura == -1:
                return -1
            
        else:
            print('Por favor, indique una dirreción IP.\n')
            return -1
        
    elif modo_comm.lower() == 'serial':
        #Se comprueba que dir_serie es válido
        if not(dir_serie == None) & (type(dir_socket) == str):
            #Se compruba que la dirrecion tiene un formato adecuado
            with str.upper().split('M') as puerto:
                cond_tipo = (puerto[0].isalpha() & puerto[1].isdigit()) 
                cond_formato = len(puerto) == 2
                if (not cond_tipo) | (not cond_formato):
                    print('Error en el formato de la dirrección de puerto serie.\n')
                    return -1
            
            
            #Una vez hechas las comprbaciones, comienza la comunicación
            lectura = __serial(dir_serie,trama)
            
            #Lectura errónea
            if lectura == -1:
                return -1
            
        else:
            print('Por favor, indique una dirreción de puerto serie.\n')
            return -1
    else:
        print('Error en la selección del modo de comunicación, modo no válido.\n')
        return -1
    
    #Se compurba que la sincronización ha sido correcta
    estado_recepcion = __comprobar_recepcion(lectura, num_estacion)
    if estado_recepcion == True:
        print('Fecha sincronizada.\n')
        return True
    else:   
        print("Error en la comunicacion con la estación.\n")
        print(estado_recepcion)
        return False
    
    
    
    
    