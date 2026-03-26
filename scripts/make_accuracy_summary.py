import os
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import MultipleLocator
import matplotlib as mpl
from matplotlib.gridspec import GridSpec
import yaml
import psycopg
mpl.use('Agg')

def make_accuracy_plot(data_list: list, outdir:str = './') -> None:

    """
    # Data list
    [
        [Module_name, offset_sensor_X, offset_sensor_Y, offset_pcb_X, offset_pcb_Y, offset_sensor_angle, offset_pcb_angle],
    ]

    Module name : Module name
    offset_sensor_X : relative X of sensor w.r.t. baseplate [unit : mm]
    offset_sensor_Y : relative Y of sensor w.r.t. baseplate [unit : mm]
    offset_pcb_X    : relative X of pcb w.r.t. baseplate    [unit : mm]
    offset_pcb_Y    : relative Y of pcb w.r.t. baseplate    [unit : mm]
    offset_sensor_angle : relative angle of sensor w.r.t. baseplate [unit : degree]
    offset_pcb_angle    : relative angle of pcb w.r.t. baseplate    [unit : degree]
    """

    module_name = ""

    if len(data_list) == 1:
        module_name = data_list[0][0]
    elif len(data_list) > 1:
        module_name = "Merged"

    fig = plt.figure(figsize=(12, 10), constrained_layout=False)
    gs = fig.add_gridspec(nrows=2, ncols=2, width_ratios=(5, 5), wspace=0.5)


    #################################
    #          Offset part          #
    #################################

    edge_limit = 200
    nbin = 80

    ax = fig.add_subplot(gs[0,0])
    ax.set_aspect('equal')
    ax_histx = ax.inset_axes([0, 1.0, 1, 0.25], sharex=ax)
    ax_histy = ax.inset_axes([1.0, 0, 0.25, 1], sharey=ax)

    ax.set_xlabel('$\Delta x$ [$\mu m$]',  fontsize=18)
    ax.set_ylabel('$\Delta y$ [$\mu m$]', fontsize=18)
    ax.xaxis.set_major_locator(MultipleLocator(100))
    ax.yaxis.set_major_locator(MultipleLocator(100))
    ax.xaxis.set_minor_locator(MultipleLocator(25))
    ax.yaxis.set_minor_locator(MultipleLocator(25))
    ax.set_xlim(-edge_limit, edge_limit)
    ax.set_ylim(-edge_limit, edge_limit)
    ax.vlines(-50, -50, 50, colors='b')
    ax.vlines( 50, -50, 50, colors='b')
    ax.hlines(-50, -50, 50, colors='b')
    ax.hlines( 50, -50, 50, colors='b')
    ax.text(-50, 55, '50 $\mu m$', color='b', fontsize=12)
    ax.vlines(-100, -100, 100, colors='r')
    ax.vlines( 100, -100, 100, colors='r')
    ax.hlines(-100, -100, 100, colors='r')
    ax.hlines( 100, -100, 100, colors='r')
    ax.text(-100, 105,'100 $\mu m$', color='r', fontsize=12)

    m_rel_sensor_X_list = []
    m_rel_sensor_Y_list = []
    m_rel_pcb_X_list    = []
    m_rel_pcb_Y_list    = []


    for data in data_list:

        rel_sensor_X = data[1]
        rel_sensor_Y = data[2]
        rel_pcb_X    = data[3]
        rel_pcb_Y    = data[4]

        limit_func = lambda x: 115. if x > 100. else -115. if x < -100. else x

        m_rel_sensor_X = limit_func( rel_sensor_X )
        m_rel_sensor_Y = limit_func( rel_sensor_Y )
        m_rel_pcb_X    = limit_func( rel_pcb_X    )
        m_rel_pcb_Y    = limit_func( rel_pcb_Y    )

        m_rel_sensor_X_list.append(  m_rel_sensor_X  )
        m_rel_sensor_Y_list.append(  m_rel_sensor_Y  )
        m_rel_pcb_X_list   .append(  m_rel_pcb_X     )
        m_rel_pcb_Y_list   .append(  m_rel_pcb_Y     )

        if abs(m_rel_sensor_X) > 100. or abs(m_rel_sensor_Y) > 100.:
            ax.text(m_rel_sensor_X, m_rel_sensor_Y, f'({rel_sensor_X:.0f}, {rel_sensor_Y:.0f})', color='#ff7f0e',
                    ha='right' if m_rel_sensor_X < -100. else 'left', va='top' if m_rel_sensor_Y < -100. else 'bottom')

        if abs(m_rel_pcb_X) > 100. or abs(m_rel_pcb_Y) > 100.:
            ax.text(m_rel_pcb_X, m_rel_pcb_Y, f'({rel_pcb_X:.0f}, {rel_pcb_Y:.0f})', color='#2ca02c',
                    ha='right' if m_rel_sensor_X < -100. else 'left', va='top' if m_rel_sensor_Y < -100. else 'bottom')

    ax.scatter(np.array(m_rel_sensor_X_list), np.array(m_rel_sensor_Y_list), marker='.', c='#ff7f0e', linestyle = 'None', label = 'Sensor')
    ax.scatter(np.array(m_rel_pcb_X_list), np.array(m_rel_pcb_Y_list), marker='.', c='#2ca02c', linestyle = 'None', label = 'PCB')

    nxp, _, _ = ax_histx.hist(np.array(m_rel_pcb_X_list), range=(-edge_limit, edge_limit), bins=nbin, color="#2ca02c", alpha=0.7)
    nyp, _, _ = ax_histy.hist(np.array(m_rel_pcb_Y_list), range=(-edge_limit, edge_limit), bins=nbin, color="#2ca02c", orientation='horizontal', alpha=0.7)
    nxs, _, _ = ax_histx.hist(np.array(m_rel_sensor_X_list), range=(-edge_limit, edge_limit), bins=nbin, color="#ff7f0e", alpha=0.7)
    nys, _, _ = ax_histy.hist(np.array(m_rel_sensor_Y_list), range=(-edge_limit, edge_limit), bins=nbin, color="#ff7f0e", orientation='horizontal', alpha=0.7)

    ax_histx.axis("off")
    ax_histy.axis("off")

    ax_histx.set_ylim(0, np.concatenate((nxs, nxp)).max()*1.3)
    ax_histy.set_xlim(0, np.concatenate((nys, nyp)).max()*1.3)

    plt.tick_params(axis='both', which='minor', direction='in', labelsize=0, length=5, width=1, right=True, top=True)
    plt.tick_params(axis='both', which='major', direction='in', labelsize=18, length=7, width=1.5, right=True, top=True)

    # Legend is hardcore 
    legend_elements = [ Line2D([0], [0], marker='o', color='w', label='Sensor w.r.t. Baseplate', markerfacecolor='#ff7f0e'),
                        Line2D([0], [0], marker='o', color='w', label='PCB w.r.t. Baseplate',    markerfacecolor='#2ca02c'),
                        ]

    ax.legend(bbox_to_anchor=(0.2, 0.83, 0.7, 0.93), loc='lower right', ncol=1, borderaxespad=0., handles=legend_elements)

    # Outside boundary region
    ax.fill_between([-125, 125], 100, 125, color='r', alpha=0.05, linewidth=0)
    ax.fill_between([-125, 125], -100, -125, color='r', alpha=0.05, linewidth=0)
    ax.fill_between([-125, -100], -100, 100, color='r', alpha=0.05, linewidth=0)
    ax.fill_between([125, 100], -100, 100, color='r', alpha=0.05, linewidth=0)
#    ax_sub.fill_between(-1. * node, 0, 2, color='r', alpha=0.1)

    #################################
    #      Rotation angle part      #
    #################################

    gauge_angle_max  = 0.04
    gauge_angle_unit = 0.02
    orig_gauge_angle_max  = 40.
    transfer_factor = orig_gauge_angle_max / gauge_angle_max
    orig_gauge_angle_unit = transfer_factor * gauge_angle_unit

    ax_sub = fig.add_subplot(gs[0,1],  polar=True)
    ax_polar_hist = ax_sub.inset_axes([-0.8, 0.04, 2.6, 1.6], sharex=ax_sub, polar=True)

    ax_sub.set_rmax(2)
    ax_sub.get_yaxis().set_visible(False)
    ax_sub.grid(False)
    ax_sub.set_theta_offset(np.pi/2)
    ax_sub.set_thetamin(-orig_gauge_angle_max*1.2)
    ax_sub.set_thetamax(orig_gauge_angle_max*1.2)
    ax_sub.set_rorigin(-2.5)

    ax_polar_hist.axis("off")
    ax_polar_hist.grid(False)
    ax_polar_hist.set_theta_offset(np.pi/2)
    ax_polar_hist.set_thetamin(-orig_gauge_angle_max*1.2)
    ax_polar_hist.set_thetamax(orig_gauge_angle_max*1.2)

    tick = [ax_sub.get_rmax(),ax_sub.get_rmax()*0.97]
    for t  in np.deg2rad(np.arange(0,360,orig_gauge_angle_unit*0.5)):
        ax_sub.plot([t,t], tick, lw=0.72, color="k")

    tick = [ax_sub.get_rmax(),ax_sub.get_rmax()*0.9]
    for t  in np.deg2rad(np.arange(0,360,orig_gauge_angle_unit)):
        ax_sub.plot([t,t], tick, lw=0.72, color="k")

    degree = ['{}°'.format(deg) for deg in np.round(np.arange(gauge_angle_max, -gauge_angle_max-gauge_angle_unit, -gauge_angle_unit), decimals=2)]

    ax_sub.set_thetagrids( np.arange(orig_gauge_angle_max, -orig_gauge_angle_max-orig_gauge_angle_unit, -orig_gauge_angle_unit) )
    ax_sub.set_xticklabels( degree, fontsize=14 )

    orig_rel_sensor_angle_list = []
    orig_rel_pcb_angle_list = []

    for data in data_list:
        rel_sensor_angle = data[5]
        rel_pcb_angle    = data[6]

        limit_angle_func = lambda x: orig_gauge_angle_max * 1.1 if x > orig_gauge_angle_max else -orig_gauge_angle_max * 1.1 if x < -orig_gauge_angle_max else x

        orig_rel_sensor_angle = limit_angle_func(transfer_factor * rel_sensor_angle)
        orig_rel_pcb_angle    = limit_angle_func(transfer_factor * rel_pcb_angle)

        if abs(orig_rel_sensor_angle) > orig_gauge_angle_max:
            ax_sub.text( orig_rel_sensor_angle * np.pi / 180., 2, f'({rel_sensor_angle:.2f}°)', color='#ff7f0e',
                    ha='left' if orig_rel_sensor_angle < -orig_gauge_angle_max else 'right', va='bottom')

        if abs(orig_rel_pcb_angle) > orig_gauge_angle_max:
            ax_sub.text( (orig_rel_pcb_angle + (15 if orig_rel_pcb_angle > 0 else -15)) * np.pi / 180., 1.0, f'({rel_pcb_angle:.2f}°)', color='#2ca02c',
                    ha='left' if orig_rel_pcb_angle < -orig_gauge_angle_max else 'right', va='bottom')


        ax_sub.annotate('', xy        = (orig_rel_sensor_angle * np.pi / 180., 2),
                        xytext    = (0., -2.5),
                        arrowprops= dict(color    ='#ff7f0e',
                                         arrowstyle="->"),
                    )
        ax_sub.annotate('', xy        = (orig_rel_pcb_angle * np.pi / 180., 1.6),
                        xytext    = (0., -2.5),
                        arrowprops= dict(color    ='#2ca02c',
                                         arrowstyle="->"),
                    )

        orig_rel_sensor_angle_list .append( orig_rel_sensor_angle * np.pi / 180. )
        orig_rel_pcb_angle_list    .append( orig_rel_pcb_angle    * np.pi / 180. )

    ax_sub.annotate('', xy        = (transfer_factor * 0.02 * np.pi / 180., 2),
                    xytext    = (transfer_factor * 0.02 * np.pi / 180., 0.),
                    arrowprops= dict(color    ='b',
                                     arrowstyle="-",
                                     linestyle ="dotted"
                                     ),
                )
    ax_sub.annotate('', xy        = (transfer_factor * -0.02 * np.pi / 180., 2),
                    xytext    = (transfer_factor * -0.02 * np.pi / 180., 0.),
                    arrowprops= dict(color    ='b',
                                     arrowstyle="-",
                                     linestyle ="dotted"
                                     ),
                )
    ax_sub.annotate('', xy        = (transfer_factor * 0.04 * np.pi / 180., 2),
                    xytext    = (transfer_factor * 0.04 * np.pi / 180., 0.),
                    arrowprops= dict(color    ='r',
                                     arrowstyle="-",
                                     linestyle ="dotted"
                                     ),
                )
    ax_sub.annotate('', xy        = (transfer_factor * -0.04 * np.pi / 180., 2),
                    xytext    = (transfer_factor * -0.04 * np.pi / 180., 0.),
                    arrowprops= dict(color    ='r',
                                     arrowstyle="-",
                                     linestyle ="dotted"
                                     ),
                )

    # Outside boundary region
    node = np.linspace(orig_gauge_angle_max * np.pi / 180., orig_gauge_angle_max * 1.2 * np.pi / 180., 50)
    ax_sub.fill_between(node, 0, 2, color='r', alpha=0.05)
    ax_sub.fill_between(-1. * node, 0, 2, color='r', alpha=0.05)

    # Polar histogram for angle projection
    p_polar_bin_content, _, _ = ax_polar_hist.hist(np.array(orig_rel_pcb_angle_list), bins=80,
            range=(-orig_gauge_angle_max*1.2* np.pi / 180., orig_gauge_angle_max*1.2* np.pi / 180.), color ='#2ca02c', alpha=0.7)

    s_polar_bin_content, _, _ = ax_polar_hist.hist(np.array(orig_rel_sensor_angle_list), bins=80,
            range=(-orig_gauge_angle_max*1.2* np.pi / 180., orig_gauge_angle_max*1.2* np.pi / 180.), color ='#ff7f0e', alpha=0.7)

    ax_polar_hist.set_rorigin(-3.5 * np.concatenate((s_polar_bin_content, p_polar_bin_content)).max() )

    #################################
    #      Flatness part            #
    #################################

    flatness  = [ data[7] for data in data_list ]

    ax_flat = fig.add_subplot(gs[1,0])
    #ax.set_aspect('equal')

    ax_flat.hist( np.array(flatness), bins=42, range=(0, 0.42))

    ax_flat.set_xlabel('Flatness [mm]', size=14)
    ax_flat.set_xlim(0, 0.42)
    ax_flat.set_ylim(bottom=0)
    plt.tick_params(axis='both', which='minor', direction='in', labelsize=14, length=5, width=1, right=True, top=True)
    plt.tick_params(axis='both', which='major', direction='in', labelsize=14, length=7, width=1.5, right=True, top=True)


    #################################
    #      Thickness part           #
    #################################

    thickness = [ data[8] for data in data_list ]

    ax_thick = fig.add_subplot(gs[1,1])
    #ax.set_aspect('equal')

    ax_thick.hist( np.array(thickness), bins=40, range=(3.0, 3.8))

    ax_thick.set_xlabel('Thickness [mm]', size=14)
    ax_thick.set_xlim(3.0, 3.8)
    ax_thick.set_ylim(bottom=0)

    plt.tick_params(axis='both', which='minor', direction='in', labelsize=14, length=5, width=1, right=True, top=True)
    plt.tick_params(axis='both', which='major', direction='in', labelsize=14, length=7, width=1.5, right=True, top=True)


    plt.savefig(f'{outdir}/out/Summary_accuracy.png')
    plt.savefig(f'{outdir}/out/Summary_accuracy.pdf')
    plt.close()


def main() -> None:

    with open('configuration.yaml') as config_file:
        config = yaml.safe_load(config_file)
    os.environ['FRAMEWORK_PATH'] = config['framework_path']

    # Input txt file with module names
    with open (os.environ['FRAMEWORK_PATH'] + "/make_accuracy_summary_ID.txt") as f:
        module_names = f.read().splitlines()

    modules = []
    for m in module_names:
        if m.find('#') != -1:
            continue
        modules.append(m)

    # Connect to database
    qc_data = []
    with psycopg.connect(
        dbname   = config['DBDatabase'],
        user     = config['DBUsername'],
        password = config['DBPassword'],
        host     = config['DBHostname'],
        port     = 5432
    ) as connection:
        with connection.cursor() as cursor:

            for module_name in modules:

                query = f"""
                    SELECT flatness, avg_thickness, x_offset_mu, y_offset_mu, ang_offset_deg FROM public.module_inspect
                    WHERE module_name = %s
                    ORDER BY module_row_no ASC
                """
                cursor.execute(query, (module_name,))
                results = cursor.fetchall()

                if len(results) == 0:
                    print(f"Module '{module_name}' QC data is not in database.")
                    exit(1)
                else:
                    results_module = results[-1]

                # Search for proto module name
                query = f"""
                    SELECT proto_name FROM public.module_assembly
                    WHERE module_name = %s
                    ORDER BY module_ass ASC
                """
                cursor.execute(query, (module_name,))
                proto_name = cursor.fetchall()[-1][-1]

                query = f"""
                    SELECT x_offset_mu, y_offset_mu, ang_offset_deg FROM public.proto_inspect
                    WHERE proto_name = %s
                    ORDER BY proto_row_no ASC
                """
                cursor.execute(query, (proto_name,))
                results_proto = cursor.fetchall()[-1]

                qc_data.append([

                    module_name,
                    results_proto[0],
                    results_proto[1],
                    results_module[2],
                    results_module[3],
                    results_proto[2],
                    results_module[4],
                    results_module[0],
                    results_module[1],

                ])


    make_accuracy_plot(qc_data, os.environ['FRAMEWORK_PATH'])


if __name__ == '__main__':
    main()
