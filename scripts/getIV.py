#!/usr/bin/env python3

# -*- coding: utf-8 -*-

from pymeasure.instruments.keithley import Keithley2400
from optparse import OptionParser
import time
from datetime import datetime
import os, sys
import numpy as np
import yaml
import psycopg2
import logging
import sys

log = logging.getLogger(__name__)

COMPLIANCE_CURRENT_UPPERLIMIT = 1e-3 ## 1mA


class Keithley2410(Keithley2400):

    def __init__(self,
                 resource:str = "ASRL/dev/ttyUSB0::INSTR",
                 terminal:str = 'Front', ## Front or Rear
                 wiresPOLARIZATION:str = 'Forward', ## Forward or Reverse
                 ) -> None:
        super().__init__(
                resource,
                )

        self.reset()

        if terminal == 'Front':
            self.use_front_terminals()
        elif terminal == 'Rear':
            self.use_rear_terminals()

        if   wiresPOLARIZATION == 'Forward':
            self.voltage_multiplier = -1.0
        elif wiresPOLARIZATION == 'Reverse':
            self.voltage_multiplier =  1.0

        # Sets the compliance current to 10 V
        self.apply_voltage(compliance_current = COMPLIANCE_CURRENT_UPPERLIMIT)

        # Sets the source voltage to 0 V
        self.source_voltage = 0

       ## Sets up to measure current
       #self.measure_all()  ## Measure current (A), voltage (V), resistance (Ohm), time (s), and status concurrently.
        # Enable both measurements

        # Enables the source output
        self.enable_source()

    def _is_larger_than_current_voltage(self, voltage:float) -> bool:

        return abs(voltage) > abs(self.source_voltage)

    def _is_equal_voltage(self, voltage:float) -> bool:

        return abs(voltage) == abs(self.source_voltage)

    def ramp_up_to_voltage(self, target_voltage:float) -> tuple[float, float, bool]:

        """
            Ramp up the voltage to target_voltage voltage.
            If the current measured is larger than compliance_current, the voltage will stop raising.
        """

        if self._is_equal_voltage(target_voltage):
            print('So far the voltage is equal to the target_voltage. Nothing to do !!')
            return target_voltage, self.current

        elif not self._is_larger_than_current_voltage(target_voltage):
            print('So far the voltage is larger than the target_voltage you want to raise up ! Do you mean `ramp_down_to_voltage(target_voltage)` ?')
            pass

        else:

            step = abs( int( ( self.source_voltage - target_voltage ) / 10 ) )
            voltages = np.linspace( self.source_voltage, target_voltage, step+1 )
            isbreak = False

            for i, voltage in enumerate( voltages ):

                self.source_voltage = voltage
                time.sleep(0.5)

                if abs(self.current) > COMPLIANCE_CURRENT_UPPERLIMIT:
                    self.source_voltage = voltages[i-1]
                    isbreak = True
                    print('Due to a limited current of {COMPLIANCE_CURRENT_UPPERLIMIT}, the voltage can be only raised to {self.source_voltage} !!')
                    break

            print(f'Ramp up to a voltage of {target_voltage} and a current of {self.current}')

            return self.source_voltage, self.current, isbreak

    def ramp_down_to_voltage(self, target_voltage:float) -> tuple[float, float]:

        """
            Ramp down the voltage to target_voltage voltage.
        """

        if self._is_equal_voltage(target_voltage):
            print('So far the voltage is equal to the target_voltage. Nothing to do !!')
            return target_voltage, self.current

        elif self._is_larger_than_current_voltage(target_voltage):
            print('So far the voltage is smaller than the target_voltage you want to lower down ! Do you mean `ramp_up_to_voltage(target_voltage)` ?')
            pass
        else:
            self.ramp_to_voltage(target_voltage, steps=60, pause=0.2)

            print(f'Ramp down to a voltage of {target_voltage} and a current of {self.current}')

            return target_voltage, self.current

    def iv_scan(self, final_voltage:float, initial_voltage:float = 0.) -> tuple[np.array, np.array, np.array, np.array]:

        """
            IV scan.
        """

        # Need set to the initial_voltage
        if self._is_equal_voltage(initial_voltage):
            pass
        elif self._is_larger_than_current_voltage(initial_voltage):
            _, _, isbreak = self.ramp_up_to_voltage(initial_voltage)

            if isbreak:
                print('initial_voltage has got a limited current. Stop doing the IV scan!')
                return None, None
        else:
            self.ramp_down_to_voltage(initial_voltage)

        assign_voltage = []
        output_voltage = []
        output_current = []
        output_resistance = []

        step = abs( int( ( final_voltage - initial_voltage ) / 25 ) ) ## scan voltage for every 25V
        voltages = np.linspace( initial_voltage, final_voltage, step+1 )

        self.write(":SENS:FUNC 'CURR','VOLT'")

        for i_step, voltage in enumerate(voltages):

            self.source_voltage = voltage

            time.sleep(2)
            '''
            if I set `self.write(":SENS:FUNC 'CURR','VOLT'")`
            The variables self.current and self.voltage would record the same value:[-49.93948, -4.947062e-06, 9.91e+37, 1916922.0, 23552.0].
            which is an array of [voltage, current, resistance, ?, ?]
            '''
            current = self.current[1]
            measure_v = self.current[0]

            log.info(f'[Recorded value] i_step{i_step:2d} sourceV:{voltage} measure_V:{measure_v} measure_I:{current}')

            ### convert value from np.float64 to float
            assign_voltage.append( float( abs(voltage) ) )
            output_voltage.append( float( abs(measure_v) ) )
            output_current.append( float( abs(current) ) )
            output_resistance.append( output_voltage[-1]/output_current[-1] )

           # no need to break the data taking since the keithley will handle the compliance current
           #if abs(current) >= COMPLIANCE_CURRENT_UPPERLIMIT:
           #    log.warning(f'[EarlyShotdown] Measured current {self.current} exceed compliance current {COMPLIANCE_CURRENT_UPPERLIMIT}')
           #    break

        return assign_voltage, output_voltage, output_current, output_resistance

def is_module_exist(cursor, module_name:str, db_name:str) -> None:

    """
        Check if the module is in the database from assembly.
    """

    query = f"""
        SELECT 1
        FROM public.module_assembly
        WHERE module_name = %s
        LIMIT 1;
    """

    cursor.execute(query, (module_name,))
    result = cursor.fetchone()

    if not result:
        print(f"Value '{module_name}' does not exist in tabel 'module_assembly' of '{db_name}' database.")
        exit(1)

def Option_Parser(argv):

    usage='usage: %prog [options] arg\n'
    parser = OptionParser(usage=usage)

    parser.add_option('-M', '--module',
            type='str', dest='module', default='M57',
            help='Module name. if module name is "0", shutdown keithley'
            )
    parser.add_option('-T', '--temperature',
            type='str', dest='temperature', default='20',
            help='Temperature'
            )
    parser.add_option('-H', '--humidity',
            type='str', dest='humidity', default='60',
            help='Humidity'
            )
    parser.add_option('-m', '--message',
            type='str', dest='message', default='',
            help='external message put in "comment". Currently used for put thermal cycle ID'
    )
    parser.add_option('-v', '--max_voltage',
                      type='int', dest='max_voltage', default=500,
                      help='absolute maximum voltage for this thermal cycle. '
                           '(modify "MMTS_hardwares/keithley/WiresPolarization=Reverse" in configuration.yaml for negative voltage")')

    parser.add_option('-i', dest='initialize', action='store_true', help='initialize step. Check hardware connection and other requirement')
    (options, args) = parser.parse_args(argv)
    return options


class LoadConf:
    ##### load config. ###
    ''' content of configuration.yaml
### used for run.IVscan.sh
MMTS_hardwares:
  keithley:
    Resource: ASRL/dev/DAQrs232_keithley::INSTR
    Terminal: Rear
    WiresPolarization: Reverse

## configs in run.IVscan.sh
DBDatabase: 'hgcdb'
DBHostname: '192.168.50.213'
DBPassword: ''
DBUsername: 'postgres'
inspector: NTULab
    '''
    def __init__(self,confFILE):
        with open(confFILE, 'r') as fin:
            conf = yaml.safe_load(fin)
        self.DBDatabase = conf['DBDatabase']
        self.DBHostname = conf['DBHostname']
        self.DBPassword = conf['DBPassword']
        self.DBUsername = conf['DBUsername']

        self.inspector = conf['inspector']
        self.resource = conf['MMTS_hardwares']['keithley']['Resource']

        
        allowed_terminal = [ 'Front', 'Rear' ]
        self.terminal = conf['MMTS_hardwares']['keithley']['Terminal']
        if self.terminal not in allowed_terminal:
            raise ValueError(
                   f'[InvalidConfig] terminal supports {allowed_terminal}. '
                   f'Option "{self.terminal}" is an invalid option. '
                    'Please check "MMTS_hardwares/keithley/Terminal" option.'
            )

        allowed_wires_polarization = [ 'Forward', 'Reverse' ]
        self.wire_polarization = conf['MMTS_hardwares']['keithley']['WiresPolarization']
        if self.wire_polarization not in allowed_wires_polarization:
            raise ValueError(
                   f'[InvalidConfig] WiresPolarization supports {allowed_wires_polarization}. '
                   f'Option "{self.wire_polarization}" is an invalid option. '
                    'Please check "MMTS_hardwares/keithley/WiresPolarization" option.'
            )

def initialize_test(conf, keithleyINST):
    ''' initialize used hardwares for checking '''

    ### asdf need to add additional test.
    keithleyINST.beep( 432, 0.5 ) ### check keithley connection looks good 
    log.info(f'[GoodConnectToKeithley] Everything passed')

    exit(0)

def ping_rs232_dev(conf):
    import pyvisa
    rm = pyvisa.ResourceManager()
    inst = rm.open_resource(conf.resource)

    print(inst.query("*IDN?"))

    
def testfunc():

    options = Option_Parser(sys.argv[1:])
    externalMESSAGE = options.message
    print(externalMESSAGE)


def mainfunc():

    options = Option_Parser(sys.argv[1:])
    externalMESSAGE = options.message

    conf = LoadConf('configuration.yaml')
    ping_rs232_dev(conf)
    

    keithley = Keithley2410(conf.resource, conf.terminal, conf.wire_polarization)
    #keithley = Keithley2410(config['RS232']['HV_keithley'])



    if options.initialize:
        initialize_test(conf, keithley)
        exit(0)

    ### if '0' as module name: stop keithley
    if options.module == '0':
        log.info(f'[StopKeithley] Received a stop command')
        keithley.ramp_down_to_voltage(0.)
        keithley.shutdown()
        exit(0)

    ### asdfasfasdfa need to add try and except for make stop
    if True:
        ### normal running
        voltage_destination = abs(options.max_voltage) * keithley.voltage_multiplier
        log.info(f'[MaxVoltage] {voltage_destination} was set as target voltage in the IV scan.')
        program_v, voltage, current, resistance = keithley.iv_scan(voltage_destination)


    keithley.ramp_down_to_voltage(0.)
    keithley.shutdown()

    ##########################################
    #                 Database               #
    ##########################################

    now = datetime.now()


    module_iv_data = {
        'module_name'      : options.module,
        'rel_hum'          : options.humidity,
        'temp_c'           : options.temperature,
        'date_test'        : now.date().strftime("%Y-%m-%d"),
        'time_test'        : now.time().strftime("%H:%M:%S"),
        'inspector'        : conf.inspector,
        'program_v'        : program_v,
        'meas_v'           : voltage,
        'meas_i'           : current,
        'meas_r'           : resistance,
        'status'           : 8,
        'status_desc'      : 'Bolted',
        'comment'          : externalMESSAGE,
    }

    module_data_column = ', '.join(module_iv_data.keys())
    module_data_column_placeholders = ', '.join(['%s'] * len(module_iv_data))


    # Connect to database
    with psycopg2.connect(
        dbname   = conf.DBDatabase,
        user     = conf.DBUsername,
        password = conf.DBPassword,
        host     = conf.DBHostname,
        port     = 5432
    ) as connection:
        with connection.cursor() as cursor:


            print(module_iv_data)
            # Module data insertion
            insert_query = f"""
                INSERT INTO module_iv_test ({module_data_column})
                VALUES ({module_data_column_placeholders});
            """

            cursor.execute(insert_query, tuple(module_iv_data.values()))
            connection.commit()



if __name__ == '__main__':
    import os
    loglevel = os.environ.get('LOG_LEVEL', 'INFO') # DEBUG, INFO, WARNING
    DEBUG_MODE = True if loglevel == 'DEBUG' else False
    logLEVEL = getattr(logging, loglevel)
    logging.basicConfig(stream=sys.stdout,level=logLEVEL,
            format=f'%(levelname)-7s%(filename)s#%(lineno)s %(funcName)s() >>> %(message)s',
            datefmt='%H:%M:%S')

    mainfunc()
   #testfunc()


