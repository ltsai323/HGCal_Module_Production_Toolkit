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
from collections import deque
from itertools import pairwise

log = logging.getLogger(__name__)

COMPLIANCE_CURRENT_UPPERLIMIT = 1e-3 ## 1mA
PROGRAM_ACTIVATE_TIME = datetime.now()


#SAMPLE_RATE_HZ = 10.0 ### evaluate current for every 0.2 second
SAMPLE_RATE_HZ = 4.0 ### evaluate current for every 0.2 second
#SAMPLE_RATE_HZ = 4.0 ### evaluate current for every 0.2 second
#NUM_CURRENT_AVG = 10 ### for stable situation, it may required 0.35 second to take 1 data point. (related to NPLC current)
NUM_CURRENT_AVG =  4 ### for stable situation, it may required 0.35 second to take 1 data point. (related to NPLC current)
SAMPLE_PERIOD = 1.0 / SAMPLE_RATE_HZ
#MAX_STEP_DURATION = 20 ## seconds
MAX_STEP_DURATION = 10 ## seconds

import pandas as pd
#KEYTHLEY_FAKE_CSV_DATA = 'storedcsv/ivtest_1R_0to200V_10Hz_dur10s_July06_13-08.csv'
#KEYTHLEY_FAKE_CSV_DATA = 'storedcsv/ivtest_1R_0to200V_5Hz_dur10s_July06_12-57.csv'
KEYTHLEY_FAKE_CSV_DATA = None
USE_FAKE_KEITHLEY = True if KEYTHLEY_FAKE_CSV_DATA else False



'''
step_index,progV0,progV1,measV,measI,absTime,relTime,stat,error,comment
'''
class FakeKeithley:
    def __init__(self, csv_file):
        self.df_all = pd.read_csv(csv_file)
        self.select_voltage(None)

        wiresPOLARIZATION = 'Forward'
        if   wiresPOLARIZATION == 'Forward':
            self.voltage_multiplier = -1.0
        elif wiresPOLARIZATION == 'Reverse':
            self.voltage_multiplier =  1.0

    def select_voltage(self, voltage):
        """Select which voltage to simulate.

        voltage=None means use all rows.
        """
        if voltage is None:
            self.df = self.df_all.reset_index(drop=True)
        else:
            self.df = (
                self.df_all[self.df_all["progV1"] == voltage]
                .reset_index(drop=True)
            )

            if len(self.df) == 0:
                raise ValueError(f"No data found for voltage={voltage}")

        self.idx = 0

    def ask(self, cmd):
        assert cmd == ":READ?"

        if self.idx >= len(self.df):
            raise StopIteration("End of selected data")

        row = self.df.iloc[self.idx]
        self.idx += 1

        return f"{row.measV},{row.measI},{row.absTime},aa"

fake_keithley = FakeKeithley(KEYTHLEY_FAKE_CSV_DATA) if USE_FAKE_KEITHLEY else None



def read_voltage(k: Keithley2400):
    if not USE_FAKE_KEITHLEY:
        k.write(":SENS:FUNC 'VOLT'")
        k.write(":SENS:VOLT:NPLC 1")
        k.write(":FORM:ELEM VOLT,TIME,STAT")
    raw = k.ask(":READ?")
    values = raw.strip().split(",")

    if USE_FAKE_KEITHLEY:
        voltage = float(values[0])
        current = float(values[1])
        inst_time = 0
        status = 0
        return voltage, inst_time, status

    voltage = float(values[0])
    inst_time = float(values[1])
    status = int(float(values[2]))


    return voltage, inst_time, status
def read_current(k: Keithley2400):
    raw = k.ask(":READ?")
    values = raw.strip().split(",")

    if USE_FAKE_KEITHLEY:
        voltage = float(values[0])
        current = float(values[1])
        inst_time = 0
        status = 0
        return current, inst_time, status


    ### real data
    current = float(values[0])
    inst_time = float(values[1])
    status = int(float(values[2]))

    return current, inst_time, status
def read_voltage_current(k: Keithley2400):
    raw = k.ask(":READ?")
    values = raw.strip().split(",")

    if USE_FAKE_KEITHLEY:
        voltage = float(values[0])
        current = float(values[1])
        inst_time = 0
        status = 0
        return voltage, current, inst_time, status


    ### real data
    voltage = float(values[0])
    current = float(values[1])
    inst_time = float(values[2])
    status = int(float(values[3]))

    return voltage, current, inst_time, status

def acquire_one_voltage_step(
    k: Keithley2400,
    voltage_setpoint: float,
):
    if int(voltage_setpoint) < 200+1:
        return acquire_one_voltage_step_0to200(k, voltage_setpoint)
   #if int(voltage_setpoint) < 400+1:
   #    return acquire_one_voltage_step_200to400(k, voltage_setpoint)
    return acquire_one_voltage_step_above200II(k, voltage_setpoint)
   #return acquire_one_voltage_step_above200(k, voltage_setpoint)
   #return acquire_one_voltage_step_lazy(k, voltage_setpoint)
   #return acquire_one_voltage_step_lazy2(k, voltage_setpoint)


    
def acquire_one_voltage_step_lazy2(
    k: Keithley2400,
    voltage_setpoint: float,
):
    ### require NPLC = 10
    program_V1 = abs(voltage_setpoint)
    k.source_voltage = k.voltage_multiplier * program_V1 ### set forward or backword voltage

    if USE_FAKE_KEITHLEY:
        log.warning(f'[FakeData] acquire_one_voltage_step() read fake keithley data for testing algorithm')
        fake_keithley.select_voltage(program_V1)
        k = fake_keithley

   #time.sleep(0.5)  # short settling time after voltage change ### not to waiting for 0.5 second
    step_t0_ns = time.monotonic_ns()

    max_num_samples = int(MAX_STEP_DURATION * SAMPLE_RATE_HZ)
    period_ns = int(SAMPLE_PERIOD * 1e9)

    current_queue = deque(maxlen=3) ### average latest 1 second current measurement
    noisy_current_sum, noisy_current_num = 0., 0. ### once noisey current found, sum up the current of whole history and take average ( except first 0.5 second)


    abs_meas_v = 0
    mean_meas_i = 0
    got_positive_current = False
    while True:
        step_time_ns = time.monotonic_ns()
        current_time_second = (step_time_ns-step_t0_ns) / 1e9
        if current_time_second > 20.0: ### maximum data taking time is 20 second
            break

        try:
            meas_v, meas_i, inst_time, status = read_voltage_current(k)
            current_queue.append(meas_i)

            if current_time_second < 2.0: continue ### only record current after 2.0 second
            abs_meas_v = abs(meas_v)
            mean_meas_i = np.asarray(current_queue).mean()
            break
        except Exception as exc:
            abs_meas_v, mean_meas_i, inst_time, status = "", "", "", ""
            error = repr(exc)
            log.error(f'[GotError] error message "{error}"\n\n')

    actual_ns = time.monotonic_ns()
    log.info(f'[MeasureResult] measure {voltage_setpoint}V: abs_meas_V {abs_meas_v} and meas_I {mean_meas_i}, this measurement used {(actual_ns-step_t0_ns) / 1e9 :.1f} second')
    return abs_meas_v, mean_meas_i
def acquire_one_voltage_step_lazy(
    k: Keithley2400,
    voltage_setpoint: float,
):
    ### require NPLC = 10
    program_V1 = abs(voltage_setpoint)
    k.source_voltage = k.voltage_multiplier * program_V1 ### set forward or backword voltage

    if USE_FAKE_KEITHLEY:
        log.warning(f'[FakeData] acquire_one_voltage_step() read fake keithley data for testing algorithm')
        fake_keithley.select_voltage(program_V1)
        k = fake_keithley

   #time.sleep(0.5)  # short settling time after voltage change ### not to waiting for 0.5 second
    step_t0_ns = time.monotonic_ns()

    max_num_samples = int(MAX_STEP_DURATION * SAMPLE_RATE_HZ)
    period_ns = int(SAMPLE_PERIOD * 1e9)

    current_queue = deque(maxlen=int(NUM_CURRENT_AVG)) ### average latest 1 second current measurement
    noisy_current_sum, noisy_current_num = 0., 0. ### once noisey current found, sum up the current of whole history and take average ( except first 0.5 second)


    abs_meas_v = 0
    mean_meas_i = 0
    got_positive_current = False
    while True:
        step_time_ns = time.monotonic_ns()
        current_time_second = (step_time_ns-step_t0_ns) / 1e9
        if current_time_second > 20.0: ### maximum data taking time is 20 second
            break

        try:
            meas_v, meas_i, inst_time, status = read_voltage_current(k)

            if current_time_second < 2.0: continue ### only record current after 2.0 second
            abs_meas_v = abs(meas_v)
            mean_meas_i = meas_i
            break
        except Exception as exc:
            abs_meas_v, mean_meas_i, inst_time, status = "", "", "", ""
            error = repr(exc)
            log.error(f'[GotError] error message "{error}"\n\n')

    actual_ns = time.monotonic_ns()
    log.info(f'[MeasureResult] measure {voltage_setpoint}V: abs_meas_V {abs_meas_v} and meas_I {mean_meas_i}, this measurement used {(actual_ns-step_t0_ns) / 1e9 :.1f} second')
    return abs_meas_v, mean_meas_i

def acquire_one_voltage_step_0to200(
    k: Keithley2400,
    voltage_setpoint: float,
):
    ''' monitor current. once stable current measured, then read voltage '''
    k.write(":SENS:FUNC:CONC OFF")
    k.write(":SENS:FUNC 'CURR'")
    k.write(":FORM:ELEM CURR,TIME,STAT")
    program_V1 = abs(voltage_setpoint)
    k.source_voltage = k.voltage_multiplier * program_V1 ### set forward or backword voltage
    k.write(':SENS:CURR:NPLC 8')
    current_queue = deque(maxlen=5)

    current_queue.clear()


    if USE_FAKE_KEITHLEY:
        log.warning(f'[FakeData] acquire_one_voltage_step() read fake keithley data for testing algorithm')
        fake_keithley.select_voltage(program_V1)
        k = fake_keithley

    step_t0_ns = time.monotonic_ns()


    abs_meas_v = 0
    mean_meas_i = None

    skip_number = 0
    while True:
        step_time_ns = time.monotonic_ns()
        current_time_second = (step_time_ns-step_t0_ns) / 1e9
        if current_time_second > 20.0: ### maximum data taking time is 20 second
            log.warning(f'[TimeoutHappened] single current measurement takes over 20 second, use latest current value.')
            break

        try:
           #meas_v, meas_i, inst_time, status = read_voltage_current(k)
            meas_i, inst_time, status = read_current(k)

            ### case 1 : hit compliance current, use last value
            keithley_hit_compliance_limit_statuscode = bool(status& (1<<3)) ## check bit3 turned on or not
            keithley_hit_compliance_limit_numerical  = abs(meas_i) > COMPLIANCE_CURRENT_UPPERLIMIT * 0.95
            if keithley_hit_compliance_limit_statuscode or keithley_hit_compliance_limit_numerical:
                mean_meas_i = meas_i
                log.warning(f'[HitComplianceCurrentLimit] current "{meas_i:.1e}" hits limit {COMPLIANCE_CURRENT_UPPERLIMIT:.1e}. keithley_status {keithley_hit_compliance_limit_statuscode} and myprogram {keithley_hit_compliance_limit_numerical}')
                break



            if current_time_second < 1.5: continue ### only record current after 1.5 second
            current_queue.append(meas_i)


            ### normal case
            if len(current_queue) < current_queue.maxlen:
                continue ### keep collecting current if the deque is not full

            currents = np.asarray(current_queue)

            sorted_current = np.sort(currents)
            mean_meas_i = sorted_current[:-1].mean() if sorted_current[:-1].std() < sorted_current[1:].std() else sorted_current[1:].mean() ### remove one point
            actual_ns = time.monotonic_ns()
            log.info(f'[MeasureResult] measure {voltage_setpoint}V: meas_I {mean_meas_i}, this measurement used {(actual_ns-step_t0_ns) / 1e9 :.1f} second')
            break
        except Exception as exc:
            mean_meas_i, inst_time, status = "", "", ""
            error = repr(exc)
            log.error(f'[GotError] error message "{error}"\n\n')

    meas_v, inst_time, status = read_voltage(k) ### read voltage at the end
    abs_meas_v = abs(meas_v)
    ### if mean_meas_i == 0, that means the current hits upper limit or some error. So use the record the last value
    if mean_meas_i == None or mean_meas_i == "":
        log.warning(f'[NoAvgCurrent] Use latest current measurement. This message probably raised due to upper limit')
        mean_meas_i = current_queue[-1]

    if abs(mean_meas_i) < 1e-12:
        log.warning(f'[0 Current] MANUAL ASSIGN 0 CURRENT TO 1e-12. maybe some error happened')
        log.warning(f'[ raw data] currents = "{current_queue}". So the mean value is "{mean_meas_i}"')
        mean_meas_i = 1e-12 * k.voltage_multiplier
    return abs_meas_v, mean_meas_i

def acquire_one_voltage_step_above200II(
    k: Keithley2400,
    voltage_setpoint: float,
):
    ''' monitor current. once stable current measured, then read voltage '''
    k.write(":SENS:FUNC:CONC OFF")
    k.write(":SENS:FUNC 'CURR'")
    k.write(":FORM:ELEM CURR,TIME,STAT")
    program_V1 = abs(voltage_setpoint)
    k.source_voltage = k.voltage_multiplier * program_V1 ### set forward or backword voltage

    k.write(":SENS:CURR:NPLC 2" )
    current_queue = deque(maxlen=11) ### average latest 1 second current measurement
    current_queue.clear()


    if USE_FAKE_KEITHLEY:
        log.warning(f'[FakeData] acquire_one_voltage_step() read fake keithley data for testing algorithm')
        fake_keithley.select_voltage(program_V1)
        k = fake_keithley

    step_t0_ns = time.monotonic_ns()


    abs_meas_v = 0
    mean_meas_i = None

    skip_number = 0
    while True:
        step_time_ns = time.monotonic_ns()
        current_time_second = (step_time_ns-step_t0_ns) / 1e9
        if current_time_second > 20.0: ### maximum data taking time is 20 second
            log.warning(f'[TimeoutHappened] single current measurement takes over 20 second, use latest current value.')
            break

        try:
           #meas_v, meas_i, inst_time, status = read_voltage_current(k)
            meas_i, inst_time, status = read_current(k)

            ### case 1 : hit compliance current, use last value
            keithley_hit_compliance_limit_statuscode = bool(status& (1<<3)) ## check bit3 turned on or not
            keithley_hit_compliance_limit_numerical  = abs(meas_i) > COMPLIANCE_CURRENT_UPPERLIMIT * 0.95
            if keithley_hit_compliance_limit_statuscode or keithley_hit_compliance_limit_numerical:
                mean_meas_i = meas_i
                log.warning(f'[HitComplianceCurrentLimit] current "{meas_i:.1e}" hits limit {COMPLIANCE_CURRENT_UPPERLIMIT:.1e}. keithley_status {keithley_hit_compliance_limit_statuscode} and myprogram {keithley_hit_compliance_limit_numerical}')
                break



            if current_time_second < 1.5: continue ### only record current after 1.5 second
            current_queue.append(meas_i)


            if skip_number > 0: ### skip N data point if recorded data is monotonic increasing or decreasing
                skip_number -= 1
                continue

            currents = np.asarray(current_queue)

            ### normal case
            if len(current_queue) < current_queue.maxlen:
                continue ### keep collecting current if the deque is not full


            sorted_current = np.sort(currents)
            mean_meas_i = sorted_current[:-1].mean() if sorted_current[:-1].std() < sorted_current[1:].std() else sorted_current[1:].mean() ### remove one point
            actual_ns = time.monotonic_ns()
            log.info(f'[MeasureResult] measure {voltage_setpoint}V: meas_I {mean_meas_i}, this measurement used {(actual_ns-step_t0_ns) / 1e9 :.1f} second')
            break
        except Exception as exc:
            mean_meas_i, inst_time, status = "", "", ""
            error = repr(exc)
            log.error(f'[GotError] error message "{error}"\n\n')

    meas_v, inst_time, status = read_voltage(k) ### read voltage at the end
    abs_meas_v = abs(meas_v)
    ### if mean_meas_i == 0, that means the current hits upper limit or some error. So use the record the last value
    if mean_meas_i == None:
        log.warning(f'[NoAvgCurrent] Use latest current measurement. This message probably raised due to upper limit')
        mean_meas_i = current_queue[-1]

    if abs(mean_meas_i) < 1e-12:
        log.warning(f'[0 Current] MANUAL ASSIGN 0 CURRENT TO 1e-12. maybe some error happened')
        log.warning(f'[ raw data] currents = "{current_queue}". So the mean value is "{mean_meas_i}"')
        mean_meas_i = 1e-12 * k.voltage_multiplier
    return abs_meas_v, mean_meas_i

def acquire_one_voltage_step_above200(
    k: Keithley2400,
    voltage_setpoint: float,
):
    program_V1 = abs(voltage_setpoint)
    k.source_voltage = k.voltage_multiplier * program_V1 ### set forward or backword voltage
    k.write(":SENS:CURR:NPLC 10" if program_V1 < 250 else ":SENS:CURR:NPLC 3" )

    if USE_FAKE_KEITHLEY:
        log.warning(f'[FakeData] acquire_one_voltage_step() read fake keithley data for testing algorithm')
        fake_keithley.select_voltage(program_V1)
        k = fake_keithley

    step_t0_ns = time.monotonic_ns()

    max_num_samples = int(MAX_STEP_DURATION * SAMPLE_RATE_HZ)
    period_ns = int(SAMPLE_PERIOD * 1e9)

    current_queue = deque(maxlen=int(NUM_CURRENT_AVG)+2) ### average latest 1 second current measurement
    noisy_current_sum, noisy_current_num = 0., 0. ### once noisey current found, sum up the current of whole history and take average ( except first 0.5 second)


    abs_meas_v = 0
    mean_meas_i = 0
    got_positive_current = False

    skip_number = 0
    while True:
        step_time_ns = time.monotonic_ns()
        current_time_second = (step_time_ns-step_t0_ns) / 1e9
        if current_time_second > 20.0: ### maximum data taking time is 20 second
            break

        try:
            meas_v, meas_i, inst_time, status = read_voltage_current(k)

            if current_time_second < 1.5: continue ### only record current after 1.5 second


            current_queue.append(meas_i)
            noisy_current_num += 1.0
            noisy_current_sum += meas_i

            if got_positive_current is False:
                if meas_i * k.voltage_multiplier * -1 > 0: ### if test voltage is -500V, then try to check positive current
                    got_positive_current = True
                    log.warning(f'[GotPosCurrent] {meas_i}. Take additional 5 second for averaging the current')

            ### case 1 : hit compliance current, use last value
            if abs(meas_i) > COMPLIANCE_CURRENT_UPPERLIMIT:
                mean_meas_i = meas_i
                break


            if skip_number > 0: ### skip N data point if recorded data is monotonic increasing or decreasing
                skip_number -= 1
                continue

            abs_meas_v = abs(meas_v)
            currents = np.asarray(current_queue)

            if got_positive_current:
                ### case 2 : once there exists positive current, the output current is averaged over 1.5+5 = 6.5 second
                if noisy_current_num < NUM_CURRENT_AVG * 2: continue ### use 2 times longer period for taking average

                mean_meas_i = noisy_current_sum / float(noisy_current_num)
                log.info(f'[LowerCurrentLimit] the measured current is noisy due to too small current. Take average of them')
                break ### if some current flips its sign, that means keithley measures TOO LOW current. directly use mean value
            else:
                ### normal case
                if len(current_queue) < current_queue.maxlen:
                    continue ### keep collecting current if the deque is not full

                log.debug( f'max{currents.max()} - min({currents.min()}  / mean({currents.mean()}) ) [[{abs(( currents.max() - currents.min() ) / currents.mean() )}]] > 0.5?')
                if abs( ( currents.max() - currents.min() ) / currents.mean() ) > 0.5: ### if range larger than 50%, keep collect current
                    skip_number = 4
                    continue ### keep collect current

                mean_meas_i = np.sort(currents)[1:-1].mean() ## remove min and max value than take average
                actual_ns = time.monotonic_ns()
                log.info(f'[MeasureResult] measure {voltage_setpoint}V: abs_meas_V {abs_meas_v} and meas_I {mean_meas_i}, this measurement used {(actual_ns-step_t0_ns) / 1e9 :.1f} second')
                break
        except Exception as exc:
            abs_meas_v, mean_meas_i, inst_time, status = "", "", "", ""
            error = repr(exc)
            log.error(f'[GotError] error message "{error}"\n\n')

    ### if mean_meas_i == 0, that means the current hits upper limit or some error. So use the record the last value
    if mean_meas_i == 0:
        log.warning(f'[NoAvgCurrent] Use latest current measurement. This message probably raised due to upper limit')
        mean_meas_i = current_queue[-1]

    if abs(mean_meas_i) < 1e-12:
        log.warning(f'[0 Current] MANUAL ASSIGN 0 CURRENT TO 1e-12. maybe some error happened')
        log.warning(f'[ raw data] currents = "{current_queue}". So the mean value is "{mean_meas_i}"')
        mean_meas_i = 1e-12 * k.voltage_multiplier
    return abs_meas_v, mean_meas_i



class Keithley2410(Keithley2400):

    def __init__(self,
                 resource:str = "ASRL/dev/ttyUSB0::INSTR",
                 terminal:str = 'Front', ## Front or Rear
                 wiresPOLARIZATION:str = 'Forward', ## Forward or Reverse
	 	         baudRATE:int = 9600,
                 ) -> None:
        super().__init__(
                resource,
                baud_rate=baudRATE
                )

        self.reset()
        time.sleep(1)

        if terminal == 'Front':
            self.use_front_terminals()
        elif terminal == 'Rear':
            self.use_rear_terminals()

        if   wiresPOLARIZATION == 'Forward':
            self.voltage_multiplier = -1.0
        elif wiresPOLARIZATION == 'Reverse':
            self.voltage_multiplier =  1.0


        # Basic source mode
        self.apply_voltage(compliance_current=COMPLIANCE_CURRENT_UPPERLIMIT)

        # Faster/stable measurement settings
        self.write(":SENS:FUNC 'VOLT','CURR'")
        self.write(":SENS:VOLT:NPLC 0.1")
       #self.write(":SENS:CURR:NPLC 7" )
        self.write(":SENS:CURR:NPLC 10" )
        self.write(":SENS:CURR:RANG:AUTO ON")
        self.write(":SYST:AZER OFF")
        self.write(":DISP:ENAB OFF")

        # Return voltage, current, instrument time, status
        self.write(":FORM:ELEM VOLT,CURR,TIME,STAT")
       ## Enables the source output
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
            if int(voltage) == 0 : continue
            meas_v, meas_i = acquire_one_voltage_step(self, voltage)

            current = meas_i
            measure_v = meas_v

            log.info(f'[Recorded value] i_step{i_step:2d} sourceV:{voltage} measure_V:{measure_v} measure_I:{current}')

            ### convert value from np.float64 to float
            assign_voltage.append( float( abs(voltage) ) )
            output_voltage.append( float( abs(measure_v) ) )
            output_current.append( float( abs(current) ) )
            output_resistance.append( output_voltage[-1]/output_current[-1] )

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
    parser.add_option('-S', '--station',
            type='str', dest='station', default='test',
            help='station name like "MMTS_5L" or "test"'
            )
    parser.add_option('-m', '--message',
            type='str', dest='message', default='',
            help='external message put in "comment"'
    )
    parser.add_option('-I', '--iteration',
            type='str', dest='iteration', default='test',
            help='iteration of thermal cycling. ex: stage_1, stage_2, stage_3, testing'
    )
    parser.add_option('-B', '--batch',
            type='str', dest='batch', default=PROGRAM_ACTIVATE_TIME.strftime('%Y%m%d-%H%M%S'),
            help='Time stamp to start a batch of IV scan. The format would be YYYYMMDD-HHMMSS'
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
        self.baud_rate = conf['MMTS_hardwares']['keithley'].get('BaudRate', None)
        if self.baud_rate is None:
            log.warning(f'[DefaultBaudRate] Since no BaudRate in mmts_configuration.yaml:MMTS_hardwares/keithley, use default value 9600')
            self.baud_rate = 9600
        self.baud_rate = int(self.baud_rate)
        log.info(f'[UsedBaudRate] Use baud rate {self.baud_rate} to connect keithley')





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

    
def testfunc_show_message():

    options = Option_Parser(sys.argv[1:])
    externalMESSAGE = options.message
    print(externalMESSAGE)

def testfunc_show_station():

    options = Option_Parser(sys.argv[1:])
    print(options.station)

def testfunc_put_something_to_DB_AND_skip_keithley():

    options = Option_Parser(sys.argv[1:])

    conf = LoadConf('configuration.yaml')
    ping_rs232_dev(conf)
    

  # keithley = Keithley2410(conf.resource, conf.terminal, conf.wire_polarization, conf.baud_rate)
  # #keithley = Keithley2410(config['RS232']['HV_keithley'])



  # if options.initialize:
  #     initialize_test(conf, keithley)
  #     exit(0)

  # ### if '0' as module name: stop keithley
  # if options.module == '0':
  #     log.info(f'[StopKeithley] Received a stop command')
  #     keithley.ramp_down_to_voltage(0.)
  #     keithley.shutdown()
  #     exit(0)

  # ### asdfasfasdfa need to add try and except for make stop
  # if True:
  #     ### normal running
  #     voltage_destination = abs(options.max_voltage) * keithley.voltage_multiplier
  #     log.info(f'[MaxVoltage] {voltage_destination} was set as target voltage in the IV scan.')
  #     program_v, voltage, current, resistance = keithley.iv_scan(voltage_destination)


  # keithley.ramp_down_to_voltage(0.)
  # keithley.shutdown()

    ##########################################
    #                 Database               #
    ##########################################



    module_iv_data = {
        'module_name'      : options.module,
        'rel_hum'          : options.humidity,
        'temp_c'           : options.temperature,
        'date_test'        : PROGRAM_ACTIVATE_TIME.date().strftime("%Y-%m-%d"),
        'time_test'        : PROGRAM_ACTIVATE_TIME.time().strftime("%H:%M:%S"),
        'inspector'        : conf.inspector,
        'program_v'        : [],
        'meas_v'           : [],
        'meas_i'           : [],
        'meas_r'           : [],
        'status'           : 8,
        'status_desc'      : 'Bolted',
        'comment'          : options.message,
        'station_name'     : options.station,
        'batch_name'       : options.batch,
        'iteration'        : options.iteration
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

def testfunc():
   #testfunc_show_message()
   #testfunc_show_station()
    testfunc_put_something_to_DB_AND_skip_keithley()

def mainfunc():

    options = Option_Parser(sys.argv[1:])

    conf = LoadConf('configuration.yaml')
    ping_rs232_dev(conf)
    

    keithley = Keithley2410(conf.resource, conf.terminal, conf.wire_polarization, conf.baud_rate)
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



    module_iv_data = {
        'module_name'      : options.module,
        'rel_hum'          : options.humidity,
        'temp_c'           : options.temperature,
        'date_test'        : PROGRAM_ACTIVATE_TIME.date().strftime("%Y-%m-%d"),
        'time_test'        : PROGRAM_ACTIVATE_TIME.time().strftime("%H:%M:%S"),
        'inspector'        : conf.inspector,
        'program_v'        : program_v,
        'meas_v'           : voltage,
        'meas_i'           : current,
        'meas_r'           : resistance,
        'status'           : 8,
        'status_desc'      : 'Bolted',
        'comment'          : options.message,
        'station_name'     : options.station,
        'batch_name'       : options.batch,
        'iteration'        : options.iteration
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



