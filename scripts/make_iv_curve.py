import os
import psycopg
import yaml
import matplotlib.pyplot as plt
import numpy as np

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

def make_iv_curve(modules: list, config) -> None:

    modules_data_room_temp    = []
    modules_data_minus40_temp = []
    modules_data_20_temp      = []

    for module_name in modules:

        plot1 = None
        plot2 = None
        plot3 = None
        with psycopg.connect(
            dbname   = config['database_name'],
            user     = config['user'],
            password = config['password'],
            host     = config['host'],
            port     = 5432
        ) as connection:
            with connection.cursor() as cursor:

                if data := iv_data_query(cursor, module_name, temperature='> 20'):
                    plot1 = data
                    modules_data_room_temp.append( data )

                if data := iv_data_query(cursor, module_name, temperature = '= -40'):
                    plot2 = data
                    modules_data_minus40_temp.append( data )

                if data := iv_data_query(cursor, module_name, temperature = '= 20'):
                    plot3 = data
                    modules_data_20_temp.append( data )

       #makeplot(module_name, modules_data_room_temp[-1:], modules_data_minus40_temp[-1:], modules_data_20_temp[-1:])
        makeplot(module_name, plot1, plot2, plot3)

    makeplot('summary', modules_data_room_temp, modules_data_minus40_temp, modules_data_20_temp, islegend=False)


if __name__ == '__main__':


    with open('configuration.yaml') as config_file:
        config = yaml.safe_load(config_file)
    os.environ['FRAMEWORK_PATH'] = config['framework_path']


    modules = [


#        "320MHL1WDNT0169",
#        "320MHL1WDNT0170",
#        "320MHL1WDNT0171",
#        "320MHL1WDNT0172",
#        "320MHR1WDNT0173",
#        "320MHR1WDNT0174",
#        "320MHR1WDNT0175",
#        "320MHR1WDNT0176",

        "320MHL1WDNT0169",
        "320MHL1WDNT0170",
        "320MHL1WDNT0171",
        "320MHL1WDNT0172",
        "320MHR1WDNT0173",
        "320MHR1WDNT0174",
        "320MHR1WDNT0175",
        "320MHR1WDNT0176",
        "320MHB1WDNT0177",
        "320MHB1WDNT0178",
        "320MHB1WDNT0179",
        "320MHB1WDNT0180",
        "320MLL3WCNT0181",
        "320MLL3WCNT0182",
        "320MLR3WCNT0183",
        "320MLR3WCNT0184",




    ]

    make_iv_curve(modules, config)
