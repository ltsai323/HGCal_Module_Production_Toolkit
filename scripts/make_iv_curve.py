#!/usr/bin/env python3
import os
import psycopg
import yaml
import matplotlib.pyplot as plt
import numpy as np
import argparse
import logging
import sys

log = logging.getLogger(__name__)



def iv_data_query(cursor, module_name:str, temperature:str = '= 20') -> tuple:

    query = f"""
        SELECT program_v, meas_i, temp_c, rel_hum FROM public.module_iv_test
        WHERE module_name = %s AND (temp_c::REAL) {temperature}
        ORDER BY mod_ivtest_no ASC
    """
    cursor.execute(query, (module_name,))
    results = cursor.fetchall()

    if len(results) != 0:
        return results[-1]
    else:
        print(f'IV data for {module_name} does not exist at temperature {temperature} !')
        return None

def makesummaryplot(plotNAME:str, modules_data_room_temp:dict=None, modules_data_minus40_temp:dict=None,
        modules_data_20_temp:dict=None, islegend:bool = True) -> tuple:

    fig, ax = plt.subplots(figsize=(8.5, 5), layout='constrained')
    ax.grid()

    #### if module not found in database, it will received a None
    run_type = None
    if modules_data_room_temp is not None:
        run_type = 'room_temp'
        for module_name, modules_data in  modules_data_room_temp.items():
            for voltage, current, temperature, humidity in modules_data:
                ax.plot(np.abs(np.array(voltage)), np.array(current)*(1e6), label = module_name, linestyle='-')

    if modules_data_minus40_temp is not None:
        run_type = 'minus 40'
        for module_name, modules_data in modules_data_minus40_temp.items():
            for voltage, current, temperature, humidity in modules_data:
                ax.plot(np.abs(np.array(voltage)), np.array(current)*(1e6), label = module_name, linestyle=':')

    if modules_data_20_temp is not None:
        run_type = 'plus 20'
        for module_name, modules_data in modules_data_20_temp.items():
            for voltage, current, temperature, humidity in modules_data:
                ax.plot(np.abs(np.array(voltage)), np.array(current)*(1e6), label = module_name, linestyle=':')
    if run_type == None:
        return

    ax.set_title(f'{plotNAME} IV', fontdict={'fontsize':20})
    ax.set_xlabel('Voltage [V]',  fontsize=18)
    ax.set_ylabel('Current [$\mu$A]', fontsize=18)
    ax.set_yscale('log')
#    ax.xaxis.set_minor_locator(MultipleLocator(50))
    ax.set_ylim(0.0004, 100)
    #ax.legend(bbox_to_anchor=(0., 1.02, 1., .102), loc='lower right', ncol=2, borderaxespad=0.)
    #ax.legend(bbox_to_anchor=(1., 0., 1.1, .5), loc='lower right', borderaxespad=0.)
    if islegend:
        ax.legend(bbox_to_anchor=(1.01, 0., 0.25, .5), loc='lower left', borderaxespad=0., title=run_type)
    plt.tick_params(axis='both', which='minor', direction='in', labelsize=0, length=5, width=1, right=True)
    plt.tick_params(axis='both', which='major', direction='in', labelsize=18, length=7, width=1.5, right=True)
    plt.savefig(f'out/{plotNAME}_IV.png')
    plt.savefig(f'out/{plotNAME}_IV.pdf')
    plt.close()
def makeplot(module_name:str, modules_data_room_temp:list=None, modules_data_minus40_temp:list=None,
        modules_data_20_temp:list=None, islegend:bool = True) -> tuple:

    fig, ax = plt.subplots(figsize=(8.5, 5), layout='constrained')
    ax.grid()

    #### if module not found in database, it will received a None
    nothing_plotted = True
    if modules_data_room_temp is not None:
        nothing_plotted = False
        for voltage, current, temperature, humidity in modules_data_room_temp:
            ax.plot(np.abs(np.array(voltage)), np.array(current)*(1e6), label = f'temperature = {temperature}, humidity = {humidity}', linestyle='-')

    if modules_data_minus40_temp is not None:
        nothing_plotted = False
        for voltage, current, temperature, humidity in modules_data_minus40_temp:
            ax.plot(np.abs(np.array(voltage)), np.array(current)*(1e6), label = f'temperature = {temperature}, humidity = {humidity}', linestyle=':')

    if modules_data_20_temp is not None:
        nothing_plotted = False
        for voltage, current, temperature, humidity in modules_data_20_temp:
            ax.plot(np.abs(np.array(voltage)), np.array(current)*(1e6), label = f'temperature = {temperature}, humidity = {humidity}', linestyle=':')
    if nothing_plotted:
        return

    ax.set_title(f'{module_name} IV', fontdict={'fontsize':20})
    ax.set_xlabel('Voltage [V]',  fontsize=18)
    ax.set_ylabel('Current [$\mu$A]', fontsize=18)
    ax.set_yscale('log')
#    ax.xaxis.set_minor_locator(MultipleLocator(50))
    ax.set_ylim(0.0004, 100)
    #ax.legend(bbox_to_anchor=(0., 1.02, 1., .102), loc='lower right', ncol=2, borderaxespad=0.)
    #ax.legend(bbox_to_anchor=(1., 0., 1.1, .5), loc='lower right', borderaxespad=0.)
    if islegend:
        ax.legend(bbox_to_anchor=(1.01, 0., 0.25, .5), loc='lower left', borderaxespad=0.)
    plt.tick_params(axis='both', which='minor', direction='in', labelsize=0, length=5, width=1, right=True)
    plt.tick_params(axis='both', which='major', direction='in', labelsize=18, length=7, width=1.5, right=True)
    plt.savefig(f'out/{module_name}_IV.png')
    plt.savefig(f'out/{module_name}_IV.pdf')
    plt.close()

def make_iv_curve(modules: list, generateSUMMARY:bool, config) -> None:
    '''
    summaryNEEDED: True or False
    '''

    modules_data_room_temp    = {}
    modules_data_minus40_temp = {}
    modules_data_20_temp      = {}

    for module_name in modules:

        with psycopg.connect(
            dbname   = config['database_name'],
            user     = config['user'],
            password = config['password'],
            host     = config['host'],
            port     = 5432
        ) as connection:
            with connection.cursor() as cursor:

                if data := iv_data_query(cursor, module_name, temperature='> 20'):
                    modules_data_room_temp[module_name] = [data] if data is not None else None

                if data := iv_data_query(cursor, module_name, temperature = '= -40'):
                    modules_data_minus40_temp[module_name] = [data] if data is not None else None

                if data := iv_data_query(cursor, module_name, temperature = '= 20'):
                    modules_data_20_temp[module_name] = [data] if data is not None else None

        if generateSUMMARY is False:
            makeplot(module_name, modules_data_room_temp[module_name], modules_data_minus40_temp[module_name], modules_data_20_temp[module_name])

    if generateSUMMARY is True:
        makesummaryplot('summary0_ZoomTemp', modules_data_room_temp, None                     , None                , islegend=True)
        makesummaryplot('summary1_Minus40' , None                  , modules_data_minus40_temp, None                , islegend=True)
        makesummaryplot('summary2_Plus20'  , None                  , None                     , modules_data_20_temp, islegend=True)

def ArgParses():
    parser = argparse.ArgumentParser(description="Valid RS232 device connected to this computer")
    
    # The `nargs='+'` allows one or more arguments to be captured as a list
    required_opts = parser.add_argument_group('required arguments')
    required_opts.add_argument('modules', nargs='+', type=str, help='input module IDs for drawing. Separated with space.')

    # Add an optional argument for a custom string
    parser.add_argument('-s', '--summary', action='store_true', help='Generate summary plot. Ignore module ID if ID not found in database.')
    args = parser.parse_args()
    
    # args.strings will be a list of input strings
    log.debug(f"Received yaml entry: {args}")
    return args

if __name__ == '__main__':
    import os
    loglevel = os.environ.get('LOG_LEVEL', 'INFO') # DEBUG, INFO, WARNING
    DEBUG_MODE = True if loglevel == 'DEBUG' else False
    logLEVEL = getattr(logging, loglevel)
    if logLEVEL == logging.INFO:
        logLEVEL = logging.WARNING ### disable unwanted warning on fontsize is 0
    logging.basicConfig(stream=sys.stdout,level=logLEVEL,
                        format=f'%(levelname)-7s%(filename)s#%(lineno)s %(funcName)s() >>> %(message)s',
                        datefmt='%H:%M:%S')


    args = ArgParses()
    with open('configuration.yaml') as config_file:
        config = yaml.safe_load(config_file)
    os.environ['FRAMEWORK_PATH'] = config['framework_path']
    make_iv_curve(args.modules, args.summary, config)
   #make_iv_curve(
   #        [ 'test10M', 'test1M' ],
   #   #    [
   #   #"320MHB1WDNT0180",
   #   #"320MLL3WCNT0181",
   #   #"320MLL3WCNT0182",
   #   #"320MLR3WCNT0183",
   #   #"320MLR3WCNT0184",
   #   #],
   #        True,
   #        config
   #)
