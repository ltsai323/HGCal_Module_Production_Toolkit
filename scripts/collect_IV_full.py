#!/usr/bin/env python3

import csv
import time
import argparse
from pathlib import Path

from pymeasure.instruments.keithley import Keithley2400
KRIA_ADDR = 'ASRL/dev/serial/by-id/usb-FTDI_USB_Serial_Converter_FT9GC67T-if00-port0'

COMPLIANCE_CURRENT_UPPERLIMIT = 1e-3 ## 1mA

DEFAULT_STEP_DURATION = 10 ## seconds

PREVIOUS_PROGRAM_V = 0

def configure_keithley(k: Keithley2400, compliance_current: float):
    k.reset()
    time.sleep(1)
    k.use_rear_terminals()

    # Basic source mode
    k.apply_voltage(compliance_current=compliance_current)

    k.write(":SENS:CURR:RANG:AUTO ON")
    k.write(":SYST:AZER OFF")
    k.write(":DISP:ENAB OFF")

    # Return voltage, current, instrument time, status

def read_voltage(k: Keithley2400):
    k.write(":SENS:FUNC 'VOLT'")
    k.write(f":SENS:VOLT:NPLC 1")
    k.write(":FORM:ELEM VOLT,TIME,STAT")
    raw = k.ask(":READ?")
    values = raw.strip().split(",")

   #voltage = float(values[0])
    voltage = float(values[0])
   #current = float(values[0])
    current = 0
    inst_time = float(values[1])
    status = int(float(values[2]))

    return voltage, current, inst_time, status
def read_current(k: Keithley2400):
    raw = k.ask(":READ?")
    values = raw.strip().split(",")

   #voltage = float(values[0])
    voltage = 0
    current = float(values[0])
    inst_time = float(values[1])
    status = int(float(values[2]))

    return voltage, current, inst_time, status

def read_voltage_current(k: Keithley2400):
    raw = k.ask(":READ?")
    values = raw.strip().split(",")

    voltage = float(values[0])
    current = float(values[1])
    inst_time = float(values[2])
    status = int(float(values[3]))

    return voltage, current, inst_time, status


def acquire_one_voltage_step(
    k: Keithley2400,
    writer: csv.writer,
    voltage_setpoint: float,
    global_t0_ns: int,
    step_index: int,
    comment: str,
    duration: float,
    nPLC: float,
):
    global PREVIOUS_PROGRAM_V
    program_V0 = PREVIOUS_PROGRAM_V
    program_V1 = voltage_setpoint
    PREVIOUS_PROGRAM_V = voltage_setpoint

    ### set nPLC for measuring currents
    n_plc = f'{nPLC:.0f}' if nPLC >= 1 else '{nPLC:.2f}'

    # Faster/stable measurement settings
    k.write(":SENS:FUNC:CONC OFF")
    k.write(":SENS:FUNC 'CURR'") ### sense current only
    k.write(f":SENS:CURR:NPLC {n_plc}")
    k.write(":FORM:ELEM CURR,TIME,STAT")

    k.source_voltage = -1. * voltage_setpoint ### forward voltage
   #k.ramp_to_voltage( -1. * voltage_setpoint ) ### forward voltage
    local_t0_ns = time.monotonic_ns()
   #time.sleep(0.5)  # short settling time after voltage change

    step_t0_ns = time.monotonic_ns()

    n_samples = 0
    i=0
    while True:
        i+=1
        new_ns = time.monotonic_ns()
        if (new_ns-step_t0_ns) / 1e9 > duration:
            break

        try:
           #meas_v, meas_i, inst_time, status = read_voltage_current(k)
            _     , meas_i, inst_time, status = read_current(k)
            actual_ns = time.monotonic_ns()
            error = ""

            keithley_hit_compliance_limit_statuscode = bool(status& (1<<3)) ## check bit3 turned on or not
            if abs(meas_i) > COMPLIANCE_CURRENT_UPPERLIMIT * 0.95 or keithley_hit_compliance_limit_statuscode:
                print(f'[HitComplianceCurrentLimit] current {meas_i:.2e} hit compliance, break')
                break
        except Exception as exc:
            meas_v, meas_i, inst_time, status = "", "", "", ""
            error = repr(exc)

       # not to measure voltage
       #meas_v, _, inst_time, status = read_voltage(k)
       #meas_v = abs(meas_v)
        meas_v = 0
        writer.writerow([
            step_index * 10000 + i,
            program_V0,
            program_V1,
            meas_v,
            meas_i,
            (actual_ns - global_t0_ns) / 1e9,
            (actual_ns - local_t0_ns) / 1e9,
            status,
            error,
            comment
        ])
        n_samples+=1
    
    now_ns = time.monotonic_ns()
    print(f'[TimeSummary] taking {n_samples} samples using {(now_ns-local_t0_ns)/1e9} second without sleep')


def main():
    def float_range(mini,maxi):
        """Return function handle of an argument type function for 
        ArgumentParser checking a float range: mini <= arg <= maxi
            mini - minimum acceptable argument
            maxi - maximum acceptable argument"""

        # Define the function with default arguments
        def float_range_checker(arg):
            """New Type function for argparse - a float within predefined range."""

            try:
                f = float(arg)
            except ValueError:    
                raise argparse.ArgumentTypeError("must be a floating point number")
            if f < mini or f > maxi:
                raise argparse.ArgumentTypeError("must be in range [" + str(mini) + " .. " + str(maxi)+"]")
            return f

        # Return function handle to checking function
        return float_range_checker
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--comment',
        required=True,
        help="Add comment for this run for identifying in DB",
    )
    parser.add_argument(
        '--no_csv_title',
        action='store_true',
        help="Remove the csv file to put content into DB",
    )
    parser.add_argument(
        "--resource",
        default=KRIA_ADDR,
        help="PyVISA resource, e.g. ASRL/dev/ttyUSB0::INSTR or ASRL1::INSTR",
    )
    parser.add_argument(
        "--output",
        default="iv_0_to_50V_10Hz.csv",
        help="Output CSV filename",
    )
    parser.add_argument(
        "--compliance-current",
        type=float,
        default=1e-3,
        help="Compliance current in ampere. Default: 1e-3 A",
    )
    parser.add_argument(
        "--NPLC",
        type=float,
        default=1.0,
        help="NPLC set to current measurment, range is 0.01 to 10",
    )
    parser.add_argument(
        "--max-voltage",
        type=float_range(0,850),
        default=50.0,
    )
    parser.add_argument(
        "--min-voltage",
        type=float_range(0,400),
        default=0,
    )
    parser.add_argument(
        "--step-voltage",
        type=float,
        default=25.0,
    )
    parser.add_argument(
        "--duration",
        type=float,
        help=f"set the testing duration, default is {DEFAULT_STEP_DURATION} second",
        default=DEFAULT_STEP_DURATION,
    )
    args = parser.parse_args()

    if float(args.NPLC) < 0.01 and float(args.NPLC) > 10:
        raise IOError(f'[InvalidNPLC] NPLC should locate in range (0.01,10). value "{args.NPLC}" is out of range')

    output = Path(args.output)

    k = Keithley2400(args.resource)
    k.use_rear_terminals()


    print(f'[Configs] Each step used {args.duration} second')
    print(f'[Configs]   scan voltage range ({args.min_voltage},{args.max_voltage})V for every step {args.step_voltage}V')
    try:
        configure_keithley(k, args.compliance_current)

        k.source_voltage = 0
        k.enable_source()
        time.sleep(3)

        first_voltage = int(args.min_voltage)
        if first_voltage != 0:
            if first_voltage > 400: raise IOError(f'[Invalid Config] voltage {first_voltage} is not acceptable')
            k.source_voltage = first_voltage
            global PREVIOUS_PROGRAM_V
            PREVIOUS_PROGRAM_V = first_voltage
            time.sleep(3)


        voltages = [
            v for v in range(
                first_voltage,
                int(args.max_voltage) + int(args.step_voltage),
                int(args.step_voltage),
            ) if v != 0 ### remove 0 V scan
        ]

        with output.open("w", newline="", buffering=1024 * 1024) as f:
            writer = csv.writer(f)
            if args.no_csv_title is False:
                writer.writerow([
                    'step_index',
                    'progV0',
                    'progV1',
                    'measV',
                    'measI',
                    'absTime',
                    'relTime',
                    'stat',
                    'error',
                    'comment',
                ])
           #writer.writerow([
           #    "step_index",
           #    "voltage_setpoint_V",
           #    "sample_index",
           #    "global_elapsed_s",
           #    "step_elapsed_s",
           #    "late_s",
           #    "measured_voltage_V",
           #    "measured_current_A",
           #    "keithley_time_s",
           #    "status",
           #    "error",
           #])

            global_t0_ns = time.monotonic_ns()

            for step_index, voltage in enumerate(voltages):
                print(f"[INFO] Step {step_index}: set voltage = {voltage} V")
                acquire_one_voltage_step(
                    k=k,
                    writer=writer,
                    voltage_setpoint=voltage,
                    global_t0_ns=global_t0_ns,
                    step_index=step_index,
                    comment=args.comment,
                    duration=args.duration,
                    nPLC = float(args.NPLC),
                )
                f.flush()

    finally:
        print("[INFO] Ramping down and disabling source...")
        try:
            k.source_voltage = 0
            time.sleep(1)
            k.disable_source()
            k.write(":DISP:ENAB ON")
        except Exception:
            pass


if __name__ == "__main__":
    ### python3 this.py \
    ###     --resource='ASRL/dev/serial/by-id/usb-FTDI_USB_Serial_Converter_FT9GC67T-if00-port0' \
    ###     --output=ivtest.csv \
    ###     --compliance-current=1e-3 \
    ###     --max-voltage=50 \
    ###     --step-voltage=25
    PREVIOUS_PROGRAM_V = 0
    main()
