from cycler import cycler

plot_style = {
        'axes.prop_cycle': cycler(
            'color',
            ['#1f17f4',
            '#ffa40e',
            '#ff3487',
            '#008b00',
            '#17becf',
            '#850085'
            ]
            ) + cycler('marker', ['o', 's', '^', 'v', 'D', 'd']),
        'axes.edgecolor': '0.3',
        'xtick.color': '0.3',
        'ytick.color': '0.3',
        'xtick.labelsize': '15',
        'ytick.labelsize': '15',
        'axes.labelcolor': 'black',
        'axes.grid': True,
        'grid.color': '#E68F6B',
        'grid.alpha': '0.8',
        'grid.linestyle': '--',
        'axes.labelsize':'20',
        'font.size': '15',
        'lines.linewidth': '1',
        'figure.figsize': '12, 6',
        'lines.markeredgewidth': '0',
        'lines.markersize': '2',
        'axes.spines.right': True,
        'axes.spines.top': True,
        'xtick.minor.visible': True,
        'ytick.minor.visible': True,
        'savefig.dpi': '180'
        }