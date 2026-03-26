#!/usr/bin/env python3
import logging
import sys

log = logging.getLogger(__name__)


import psycopg
from psycopg.rows import dict_row
import numpy as np
import yaml

def is_module_exist(cursor, module_name:str, db_name:str) -> None:

    """
        Check if the module is in the database from assembly and QC.
    """

    tables = [
        'module_assembly',
        'proto_assembly',
        'proto_inspect',
        'module_inspect',
        'module_iv_test',
        'module_pedestal_test'
        ]

    proto_name = ''

    for table in tables:

        item = 'module_name' if table.find('module') != -1 else 'proto_name'

        query = f"""
            SELECT 1
            FROM public.{table}
            WHERE {item} = %s
            LIMIT 1;
        """

        log.debug(f'[SQLCMD] Try to find module "{module_name}" in table "{table}".'%(module_name if table.find('module') != -1 else proto_name,))
        log.debug(f'[SQL] \n{query}')
        log.debug(f'[SQL ENDED]')
        cursor.execute(query, (module_name if table.find('module') != -1 else proto_name,))
        result = cursor.fetchone()

        if not result:
            #print(query)
            #print(item, module_name if table.find('module') != -1 else proto_name )
            log.info(f"Value '{module_name}' does not exist in tabel {table} of '{db_name}' database.")
            exit(1)

        if table == 'module_assembly':

            query = f"""
                SELECT proto_name FROM public.module_assembly
                WHERE module_name = %s
                ORDER BY module_ass ASC
            """
            log.debug( '[SQLCMD] Un connected channels. Put this CMD try block to avoid no 2V bias measurements') # asdfg
            log.debug(f'[SQL] \n{query}')
            log.debug(f'[SQL ENDED]')
            cursor.execute(query, (module_name,))
            results = cursor.fetchall()[-1]
            proto_name = results['proto_name']

def readout_info(cursor, module_name):

    # Un connected channels
    # Make 'try' to avoid no 2V bias measurements
    try:
        query = f"""
            SELECT adc_stdd, cell, channeltype FROM public.module_pedestal_test
            WHERE module_name = %s AND inspector != 'test' AND bias_vol = 2
            ORDER BY mod_pedtest_no ASC
        """

        log.debug( '[SQLCMD] Un connected channels. Put this CMD try block to avoid no 2V bias measurements')
        log.debug(f'[SQL] \n{query}')
        log.debug(f'[SQL ENDED]')
        cursor.execute(query, (module_name,))
        results = cursor.fetchall()[-1]

        noise    = np.array(results['adc_stdd'])
        cellid   = np.array(results['cell'])
        celltype = np.array(results['channeltype'])

        norm_mask = (celltype == 0) & (cellid > 0)
        calib_mask = (celltype == 1)

        uncon = (noise[norm_mask | calib_mask] < 1.2) & (noise[norm_mask | calib_mask] > 0.)
        unconcells = cellid[norm_mask | calib_mask][uncon]

    except Exception as e:
        log.info('No 2 V bias measurements. Assume no unconnected channel')
        unconcells = np.array([])

    # Dead channels and noisy channels
    status = 8
    query = f"""
        SELECT 1
        FROM public.module_pedestal_test
        WHERE module_name = %s AND status = 8 AND inspector != 'test' AND bias_vol != 2
        LIMIT 1;
    """

    log.debug(f'[SQLCMD] Check there is electric QC for "{module_name}" in thermal cycle step (status = 8). If DB returns nothing, switch to electronic QC in completely bonded step (status = 5)')
    log.debug(f'[SQL] \n{query}')
    log.debug(f'[SQL ENDED]')
    cursor.execute(query, (module_name,))
    result = cursor.fetchone()

    if not result:
        print(f"There is no electronic QC for {module_name} in thermal cycle step (status = 8). Switch to electronic QC in completely bonded step (status = 5)")
        status = 5

    query = f"""
        SELECT cell, channeltype, list_dead_cells, list_noisy_cells FROM public.module_pedestal_test
        WHERE module_name = %s AND status = {status} AND inspector != 'test' AND bias_vol != 2
        ORDER BY mod_pedtest_no ASC
    """

    log.debug( '[SQLCMD] According to check result, extract required information from DB')
    log.debug(f'[SQL] \n{query}')
    log.debug(f'[SQL ENDED]')
    cursor.execute(query, (module_name,))
    results = cursor.fetchall()[-1]

    cellid   = np.array(results['cell'])
    celltype = np.array(results['channeltype'])

    norm_mask = (celltype == 0) & (cellid > 0)
    calib_mask = (celltype == 1)

    deadcells  = np.array(results['list_dead_cells'])
    noisycells = np.array(results['list_noisy_cells'])

    badcell = np.concatenate((unconcells, deadcells, noisycells))
    badfrac = len(badcell) / len(cellid[norm_mask | calib_mask])

    return unconcells.tolist(), deadcells.tolist(), noisycells.tolist(), [], badcell.tolist(), badfrac

def iv_info(cursor, module_name):

    # Dead channels and noisy channels
    query = f"""
        SELECT program_v, meas_i FROM public.module_iv_test
        WHERE module_name = %s AND temp_c::REAL >= 20 AND inspector != 'test'
        ORDER BY mod_ivtest_no ASC
    """
    log.debug( '[SQLCMD] Dead channels and noisy channels')
    log.debug(f'[SQL] \n{query}')
    log.debug(f'[SQL ENDED]')
    cursor.execute(query, (module_name,))
    results = cursor.fetchall()[-1]

    voltage  = np.abs( np.array(results['program_v']) )
    current  = np.abs( np.array(results['meas_i']) )

    i_500v = current[voltage==500.]

    return float(i_500v[0]) if len(i_500v) != 0 else 1e-4

def assembly_info(cursor, module_name):

    # Find proto module name from module name
    query = f"""
        SELECT proto_name FROM public.module_assembly
        WHERE module_name = %s
        ORDER BY module_ass ASC
    """
    log.debug( '[SQLCMD] Find proto module name from module name')
    log.debug(f'[SQL] \n{query}')
    log.debug(f'[SQL ENDED]')
    cursor.execute(query, (module_name,))
    results = cursor.fetchall()[-1]
    proto_name = results['proto_name']

    # Fetch proto module QC
    query = f"""
        SELECT x_offset_mu, y_offset_mu, ang_offset_deg FROM public.proto_inspect
        WHERE proto_name = %s AND inspector != 'test'
        ORDER BY proto_row_no ASC
    """
    log.debug( '[SQLCMD] Fetch proto module QC')
    log.debug(f'[SQL] \n{query}')
    log.debug(f'[SQL ENDED]')
    cursor.execute(query, (proto_name,))
    results = cursor.fetchall()[-1]

    pxoffset = results['x_offset_mu']
    pyoffset = results['y_offset_mu']
    pangoffset = results['ang_offset_deg']

    # Fetch module QC
    query = f"""
        SELECT avg_thickness, flatness, x_offset_mu, y_offset_mu, ang_offset_deg, max_thickness FROM public.module_inspect
        WHERE module_name = %s AND inspector != 'test'
        ORDER BY module_row_no ASC
    """
    log.debug( '[SQLCMD] Fetch module QC')
    log.debug(f'[SQL] \n{query}')
    log.debug(f'[SQL ENDED]')
    cursor.execute(query, (module_name,))
    results = cursor.fetchall()[-1]

    mthickness     = results['avg_thickness']
    mflatness      = results['flatness']
    mxoffset       = results['x_offset_mu']
    myoffset       = results['y_offset_mu']
    mangoffset     = results['ang_offset_deg']
    mmaxthickness  = results['max_thickness']

    return None, None, pxoffset, pyoffset, pangoffset, mthickness, mflatness, mxoffset, myoffset, mangoffset, None, mmaxthickness

# Copy from https://gitlab.cern.ch/acrobert/hgcal-module-testing-gui/-/blob/master/InteractionGUI.py?ref_type=heads#L1216-1382
def grade_module(cursor, module_name):

    unconcells, deadcells, noisycells, groundedcells, badcell, badfrac = readout_info(cursor, module_name)
    i_500v = iv_info(cursor, module_name)
    pthickness, pflatness, pxoffset, pyoffset, pangoffset, mthickness, mflatness, mxoffset, myoffset, mangoffset, pmaxthickness, mmaxthickness = assembly_info(cursor, module_name)

    # four individual grades
    # last updated 2025/4/7 by adapting https://indico.cern.ch/event/1523208/contributions/6408499/attachments/3034525/5358749/ModuleProdNumbers_Mar19_2025.pdf
    #final_grade_def = '2025/4/7 https://indico.cern.ch/event/1523208/contributions/6408499/attachments/3034525/5358749/ModuleProdNumbers_Mar19_2025.pdf'
    #proto_grade_def = 'grade A: xy offsets < 100 um, ang offset < 0.02 deg; grade B: xy offsets < 200 um, ang offset < 0.04 deg; grade C otherwise'
    #module_grade_def = 'grade A: xy offsets < 100 um, ang offset < 0.02 deg; grade B: xy offsets < 250 um, ang offset < 0.06 deg; grade C otherwise'
    final_grade_def = '2025/6/4 https://indico.cern.ch/event/1554499/contributions/6545989/attachments/3080366/5452243/ModuleProdNumbers_June04_2025.pdf'
    proto_grade_def = 'grade A: xy offsets < 50 um, ang offset < 0.04 deg; grade B: xy offsets < 100 um, ang offset < 0.04 deg; grade C otherwise'
    module_grade_def = 'grade A: xy offsets < 75 um, ang offset < 0.04 deg; grade B: xy offsets < 110 (CE-H)/120 (CE-E) um, ang offset < 0.04 deg OR xy offsets < 75 (CE-H)/85 (CE-E) um, ang offset < 0.1 deg; grade C otherwise'
    readout_grade_def = 'grade A: bad channel fraction < 2%; grade B: bad channel fraction < 4%; grade C otherwise'
    iv_grade_def = 'grade A: I(500V) < 100uA; grade B: I(500V) < 1mA; grade C otherwise'
    # grade_f_criteria?
    if i_500v < 1e-4:
        iv_grade = 'A'
    elif i_500v < 9.95e-4: # not quite one milliamp so exactly one mA fails grade B 
        iv_grade = 'B'
    else:
        iv_grade = 'C'

    if badfrac < 0.02:
        readout_grade = 'A'
    elif badfrac < 0.04:
        readout_grade = 'B'
    else:
        readout_grade = 'C'

    if abs(pxoffset) < 50 and abs(pyoffset) < 50 and abs(pangoffset) < 0.04:
        proto_grade = 'A'
    elif abs(pxoffset) < 100 and abs(pyoffset) < 100 and abs(pangoffset) < 0.04:
        proto_grade = 'B'
    else:
        proto_grade = 'C'

    bgrade_1 = 110 if module_name[7] == 'T' else 120
    bgrade_2 = 75  if module_name[7] == 'T' else 85

    if abs(mxoffset) < 75 and abs(myoffset) < 75 and abs(mangoffset) < 0.04:
        module_grade = 'A'
    elif abs(mxoffset) < bgrade_1 and abs(myoffset) < bgrade_1 and abs(mangoffset) < 0.04:
        module_grade = 'B'
    elif abs(mxoffset) < bgrade_2 and abs(myoffset) < bgrade_2 and abs(mangoffset) < 0.1:
        module_grade = 'B'
    else:
        module_grade = 'C'

    # determine overall grade = minimum indiv grade     
    grade_list = [iv_grade, readout_grade, proto_grade, module_grade]
    if grade_list.count('A') == 4:
        final_grade = 'A'
    elif grade_list.count('C') == 0:
        final_grade = 'B'
    else:
        final_grade = 'C'

    # pop-up window to show grade and enter comments   
    qc_summary = {'module_name': module_name,
                  'final_grade': final_grade,
                  'final_grade_def': final_grade_def,
                  'proto_flatness': pflatness,
                  'proto_avg_thickness': pthickness,
                  'proto_x_offset': pxoffset,
                  'proto_y_offset': pyoffset,
                  'proto_ang_offset': pangoffset,
                  'proto_grade': proto_grade,
                  'proto_grade_def': proto_grade_def,
                  'module_flatness': mflatness,
                  'module_avg_thickness': mthickness,
                  'module_x_offset': mxoffset,
                  'module_y_offset': myoffset,
                  'module_ang_offset': mangoffset,
                  'module_grade': module_grade,
                  'module_grade_def': module_grade_def,
                  'module_weight': None,
                  'count_back_unbonded': None,
                  'front_pull_avg': None,
                  'front_pull_std': None,
                  'list_cells_unbonded': unconcells,
                  'list_cells_grounded': groundedcells,
                  'count_bad_cells': len(badcell),
                  'list_noisy_cells': noisycells,
                  'list_dead_cells': deadcells,
                  'readout_grade': readout_grade,
                  'readout_grade_def': readout_grade_def,
                  #'i_at_600v': i_500v,
                  #'i_ratio_850v_600v': i_850v/i_600v,
                  'ref_volt_a': 500,
                  'ref_volt_b': 1e10, # not taking IV past 500V
                  'i_at_ref_a': i_500v,
                  'i_ratio_ref_b_over_a': 1e10, # not taking IV past 500V
                  'iv_grade': iv_grade,
                  'iv_grade_def': iv_grade_def,
                  'proto_max_thickness': pmaxthickness,
                  'module_max_thickness': mmaxthickness,
                  #'grade_version': 'preproduction_1_2024-10-16',   
                  'comments_all': None
                  }

    return qc_summary


def module_detection(cursor):

    # List the modules which pass the final step (Bolt step, status = 8)
    query = f"""
        SELECT module_name FROM public.module_pedestal_test
        WHERE status = 8 AND inspector != 'test' AND bias_vol != 2
    """

    log.debug( '[SQLCMD] List the modules which pass the final step (Bolt step, status = 8)')
    log.debug(f'[SQL] \n{query}')
    log.debug(f'[SQL ENDED]')
    cursor.execute(query)
    result = cursor.fetchall()
    test_module = set( [ r['module_name'] for r in result ] )

    # List the modules put in module_qc_summary table
    query = f"""
        SELECT module_name FROM public.module_qc_summary
        WHERE module_name != 'test'
    """

    log.debug( '[SQLCMD] List the modules put in module_qc_summary table')
    log.debug(f'[SQL] \n{query}')
    log.debug(f'[SQL ENDED]')
    cursor.execute(query)
    result = cursor.fetchall()
    existing_module = set( [ r['module_name'] for r in result ] )

    # Get the modules that havn't put into module_qc_summary
    # [1,2,3,4,6,7,8] - [1,2,3,4,5,6,7] = [8]
    return list(test_module - existing_module)

def module_grading(config) -> None:

    # Connect to database
    with psycopg.connect(
        dbname   = config['DBDatabase'],
        user     = config['DBUsername'],
        password = config['DBPassword'],
        host     = config['DBHostname'],
        port     = 5432
    ) as connection:
        with connection.cursor(row_factory=dict_row) as cursor:


            module_names = module_detection(cursor)

            for module_name in module_names:

                is_module_exist(cursor, module_name, config['DBDatabase'])
                module_qc_summary = grade_module(cursor, module_name)

                # Module data insertion
                module_qc_summary_column = ', '.join(module_qc_summary.keys())
                module_qc_summary_column_placeholders = ', '.join(['%s'] * len(module_qc_summary))

                insert_query = f"""
                    INSERT INTO module_qc_summary ({module_qc_summary_column})
                    VALUES ({module_qc_summary_column_placeholders});
                """

                log.debug(f'[SQLCMD] insert query from module "{module_name}":')
                log.debug(f'[SQL] \n{insert_query}')
                log.debug(f'[SQL ENDED]')
                cursor.execute(insert_query, tuple(module_qc_summary.values()))
                connection.commit()

                log.info(f"{module_name} has been inserted to config['DBDatabase'] successfully.")

if __name__ == '__main__':
    import os
    loglevel = os.environ.get('LOG_LEVEL', 'INFO') # DEBUG, INFO, WARNING
    DEBUG_MODE = True if loglevel == 'DEBUG' else False
    logLEVEL = getattr(logging, loglevel)
    logging.basicConfig(stream=sys.stdout,level=logLEVEL,
    format=f'%(levelname)-7s%(filename)s#%(lineno)s %(funcName)s() >>> %(message)s',
    datefmt='%H:%M:%S')

    with open('configuration.yaml') as config_file:
        config = yaml.safe_load(config_file)

    module_grading(config)
