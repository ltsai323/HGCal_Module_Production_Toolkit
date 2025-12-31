
# -*- coding: utf-8 -*-

from pymeasure.instruments.keithley import Keithley2400
from optparse import OptionParser
import time
from datetime import datetime
import os, sys
import numpy as np
import yaml
import psycopg2

class Keithley2410(Keithley2400):

    def __init__(self, adapter:str = "GPIB0::24::INSTR") -> None:
        super().__init__(
                adapter,
                )

        self.reset()
        self.use_front_terminals()

        # Sets the compliance current to 10 V
        self.apply_voltage(compliance_current = 1e-4)

        # Sets the source voltage to 0 V
        self.source_voltage = 0
        # Enables the source output
        self.enable_source()

        # Sets up to measure current
        self.measure_current(current=1e-4, auto_range=False)

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

                if abs(self.current) > 1e-4:
                    self.source_voltage = voltages[i-1]
                    isbreak = True
                    print('Due to a limited current of 1e-4, the voltage can be only raised to {self.source_voltage} !!')
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

    def iv_scan(self, final_voltage:float, initial_voltage:float = 0.) -> tuple[np.array, np.array]:

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

        output_voltage = []
        output_current = []
        output_resistance = []

        step = abs( int( ( final_voltage - initial_voltage ) / 10 ) )
        voltages = np.linspace( initial_voltage, final_voltage, step+1 )

        for i_step, voltage in enumerate(voltages):

            self.source_voltage = voltage

            time.sleep(2)

            current = self.current

            print(voltage, current)

            output_voltage.append( abs(voltage) )
            output_current.append( abs(current) )
            output_resistance.append( voltage/current )

            if abs(current) >= 9.5e-5:
                break

        return output_voltage, output_current, output_resistance

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
            help='Module name'
            )
    parser.add_option('-T', '--temperature',
            type='str', dest='temperature', default='20',
            help='Temperature'
            )
    parser.add_option('-H', '--humidity',
            type='str', dest='humidity', default='60',
            help='Humidity'
            )

    (options, args) = parser.parse_args(argv)
    return options

if __name__ == '__main__':
    ##### load config. ###
    ''' content of configuration.yaml
### used for run.IVscan.sh
RS232:
  switch_vitek: 'ASRL/dev/DAQrs232_HVswitch::INSTR'
  HV_keithley: 'ASRL/dev/DAQrs232_keithley::INSTR'

## configs in run.IVscan.sh
DBDatabase: 'hgcdb'
DBHostname: '192.168.50.213'
DBPassword: ''
DBUsername: 'postgres'
inspector: NTULab
    '''
    with open('configuration.yaml') as config_file:
        config = yaml.safe_load(config_file)

    options = Option_Parser(sys.argv[1:])

    keithley = Keithley2410(config['RS232']['HV_keithley'])
    voltage, current, resistance = keithley.iv_scan(-500)

#    if voltage[-1] > -300.:
#        keithley.ramp_up_to_voltage(-300.)
#    else:
#        keithley.ramp_down_to_voltage(-300.)
#
#    with open('dat_pre_series/{}_{}T_IV.txt'.format(options.module, options.temperature), 'w') as f:
#        for i in range(len(voltage)):
#            f.write(f'{voltage[i]} {current[i]} \n')
#
#    try:
#        while True:
#            time.sleep(1)
#            print("Wait for the pedestal/Noise test!")
#
#    except KeyboardInterrupt:
#        keithley.ramp_down_to_voltage(-2.)
#
#    try:
#        while True:
#            time.sleep(1)
#            print("Wait for the pedestal/Noise test!")
#
#    except KeyboardInterrupt:
#        keithley.ramp_down_to_voltage(0.)
#        keithley.shutdown()


#    with open('{}_{}T_IV.txt'.format(options.module, options.temperature), 'w') as f:
#        for i in range(len(voltage)):
#            f.write(f'{voltage[i]} {current[i]} \n')

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
        'inspector'        : config['inspector'],
        'program_v'        : voltage,
        'meas_v'           : voltage,
        'meas_i'           : current,
        'meas_r'           : resistance,
        'status'           : 8,
        'status_desc'      : 'Bolted'
    }

    module_data_column = ', '.join(module_iv_data.keys())
    module_data_column_placeholders = ', '.join(['%s'] * len(module_iv_data))

    # Connect to database
    with psycopg2.connect(
        dbname   = config['DBDatabase'],
        user     = config['DBUsername'],
        password = config['DBPassword'],
        host     = config['DBHostname'],
        port     = 5432
    ) as connection:
        with connection.cursor() as cursor:

            #is_module_exist(cursor, options.module, config['DBDatabase'])

            print(module_iv_data)
            # Module data insertion
            insert_query = f"""
                INSERT INTO module_iv_test ({module_data_column})
                VALUES ({module_data_column_placeholders});
            """

            cursor.execute(insert_query, tuple(module_iv_data.values()))
            connection.commit()

            #print(f"{module_name} has been inserted to config['database_name'] successfully.")
