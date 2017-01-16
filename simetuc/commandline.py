# -*- coding: utf-8 -*-
"""
Created on Sun Oct 16 11:53:51 2016

@author: Villanueva
"""

# TODO: INCLUDE PULSE FREQUENCY IN STEADY STATE FOR NON CW-LASER EXCITATION
# notTODO: INCLUDE .CIF FILE GENERATION OF LATTICE -> doesn't work with multiple sites...
# TODO: cooperative sensitization: in progress

import sys
import logging
import logging.config
import argparse
# nice debug printing of settings
import pprint
import datetime
import os
from pkg_resources import resource_string
from typing import Any, Union, List

#import numpy as np
import matplotlib.pyplot as plt
import yaml

import simetuc.lattice as lattice
import simetuc.simulations as simulations
import simetuc.settings as settings
import simetuc.optimize as optimize

from simetuc import VERSION
from simetuc import DESCRIPTION


# Union used in a # type: comment, but pylint and flake8 don't see it
Union  # pylint: disable=W0104


def _change_console_logger(level: int) -> None:  # pragma: no cover
    ''' change the logging level of the console handler '''
    logger = logging.getLogger()
    for handler in logger.handlers:
        if isinstance(handler, logging.StreamHandler):
            if handler.stream == sys.stdout:  # type: ignore
                handler.setLevel(level)


def parse_args(args: Any) -> argparse.Namespace:
    '''Create a argparser and parse the args'''
    # parse arguments
    parser = argparse.ArgumentParser(description=DESCRIPTION+' '+VERSION)
    parser.add_argument('--version', action='version', version=DESCRIPTION+' '+VERSION)
    # verbose or quiet options
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-v", "--verbose", help='show warnings and progress information',
                       action="store_true")
    group.add_argument("-q", "--quiet", help='show only errors', action="store_true")
    # no plot
    parser.add_argument("--no-plot", help='don\'t show plots', action="store_true")

    # average rate equations
    parser.add_argument("--average", help=('use average rate equations' +
                                           ' instead of microscopic'), action="store_true")
    # config file
    parser.add_argument(metavar='configFilename', dest='filename', help='configuration filename')

    # main options: load config file, lattice, simulate or optimize
    group = parser.add_mutually_exclusive_group()
    group.add_argument('-l', '--lattice', help='generate and plot the lattice',
                       action='store_true')
    group.add_argument('-d', '--dynamics', help='simulate dynamics',
                       action='store_true')
    group.add_argument('-s', '--steady-state', help='simulate steady state',
                       action='store_true')
    group.add_argument('-p', '--power-dependence', help='simulate power dependence of steady state',
                       action='store_true')
    group.add_argument('-c', '--conc-dep', dest='conc_dependence',
                       metavar='d', nargs='?', const='s',
                       help=('simulate concentration dependence of' +
                             ' the steady state (default) or dynamics (d)'),
                       action='store')
    group.add_argument('-o', '--optimize', help='optimize the energy transfer parameters',
                       action='store_true')

    # save data
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument('--no-save', help='don\'t save results',
                       action="store_true")
    group.add_argument('--save-txt', help='save some results in text format',
                       action="store_true")

    # add plot subcommand
#    subparsers = parser.add_subparsers(dest="plot")
#    foo_parser = subparsers.add_parser('foo')
#    foo_parser.add_argument('-c', '--count')

    parsed_args = parser.parse_args(args)
    return parsed_args


def _setup_logging(console_level: int) -> None:
    '''Load logging settings from file and apply them.'''
    # read logging settings from file
    # use the file located where the package is installed
    _log_config_file = 'log_config.cfg'
    # resource_string opens the file and gets it as a string. Works inside .egg too
    try:
        _log_config_location = resource_string(__name__, os.path.join('config', _log_config_file))
    except NotImplementedError:  # pragma: no cover
        print('ERROR! Logging settings file ({}) not found!'.format(_log_config_file))
        print('Logging won\'t be available!!')
        # minimum settings without errors
        log_settings = {'version': 1}  # type: Dict
    else:
        try:
            log_settings = yaml.safe_load(_log_config_location)
            # modify logging to console that the user wants
            log_settings['handlers']['console']['level'] = console_level
        except OSError:  # pragma: no cover
            print('ERROR! Logging settings file not found at {}!'.format(_log_config_location))
            print('Logging won\'t be available!!')
            log_settings = {'version': 1}  # minimum settings without errors
        else:
            os.makedirs('logs', exist_ok=True)

    # load settings and rollover any rotating file handlers
    # so each execution of this program is logged to a fresh file
    logging.config.dictConfig(log_settings)
    logger = logging.getLogger('simetuc')
    for handler in logging.getLogger().handlers:  # pragma: no cover
        if isinstance(handler, logging.handlers.RotatingFileHandler):  # type: ignore
            handler.doRollover()  # type: ignore

    logger.debug('Log settings dump:')
    logger.debug(pprint.pformat(log_settings))


def main(ext_args: List[str] = None) -> None:
    '''Main entry point for the command line interface'''
    if ext_args is None:  # pragma: no cover
        args = parse_args(sys.argv[1:])  # skip the program name
    else:
        args = parse_args(ext_args)

    # choose console logger level
    no_console = True
    if args.verbose:
        console_level = logging.INFO
        no_console = False
    elif args.quiet:
        console_level = logging.ERROR
        no_console = True
    else:
        console_level = logging.WARNING
        no_console = False

    # show plots or not
    no_plot = False
    if args.no_plot:
        no_plot = True

    _setup_logging(console_level)
    logger = logging.getLogger('simetuc')

    logger.info('Starting program...')
    logger.debug('Called from cmd with arguments: %s.', args)

    # load config file
    logger.info('Loading configuration...')
    cte = settings.load(args.filename)
    cte['no_console'] = no_console
    cte['no_plot'] = no_plot

    # solution of the simulation
    solution = None  # type: Union[simulations.Solution, simulations.SolutionList]

    # choose what to do
    if args.lattice:  # create lattice
        logger.info('Creating and plotting lattice...')
        lattice.generate(cte)

    elif args.dynamics:  # simulate dynamics
        logger.info('Simulating dynamics...')
        sim = simulations.Simulations(cte)
        solution = sim.simulate_dynamics(average=args.average)
        solution.log_errors()

    elif args.steady_state:  # simulate steady state
        logger.info('Simulating steady state...')
        sim = simulations.Simulations(cte)
        solution = sim.simulate_steady_state(average=args.average)
        solution.log_populations()

    elif args.power_dependence:  # simulate power dependence
        logger.info('Simulating power dependence...')
        sim = simulations.Simulations(cte)
        power_dens_list = cte['power_dependence']

        # change the logging level of the console handler
        # so it only prints warnings to screen while calculating all solutions
        _change_console_logger(logging.WARNING)
        solution = sim.simulate_power_dependence(power_dens_list, average=args.average)
        # restore old level value
        _change_console_logger(console_level)
        print('')

    elif args.conc_dependence:  # simulate concentration dependence
        sim = simulations.Simulations(cte)

        conc_list = cte['conc_dependence']

        dynamics = False
        if args.conc_dependence == 'd':
            dynamics = True
            logger.info('Simulating concentration dependence of dynamics...')
        else:
            logger.info('Simulating concentration dependence of steady state...')

        # change the logging level of the console handler
        # so it only prints warnings to screen while calculating all solutions
        _change_console_logger(logging.WARNING)
        solution = sim.simulate_concentration_dependence(conc_list, dynamics=dynamics,
                                                         average=args.average)
        # restore old level value
        _change_console_logger(console_level)
        print('')

    elif args.optimize:  # optimize
        logger.info('Optimizing ET parameters...')

        method = cte.get('optimize_method', None)
        logger.info('Optimization method: %s.', method)

        # read the starting values from the settings
        if 'optimization_processes' in cte and cte['optimization_processes'] is not None:
            # optimize only those ET parameters that the user has selected
            process_list = [process for process in cte['ET']
                            if process in cte['optimization_processes']]
        else:
            process_list = [process for process in cte['ET']]

        _change_console_logger(logging.WARNING)
        start_time = datetime.datetime.now()
        best_x, min_f = optimize.optimize_dynamics(cte, method, average=args.average)

        _change_console_logger(console_level)
#        print('\n')  # jump to the line after the progress bar

        total_time = datetime.datetime.now() - start_time
        hours, remainder = divmod(total_time.total_seconds(), 3600)
        minutes, seconds = divmod(remainder, 60)
        formatted_time = '{:.0f}h {:02.0f}m {:02.0f}s'.format(hours, minutes, seconds)
        logger.info('Minimum reached! Total time: %s.', formatted_time)
        logger.info('Optimized RMS error: %.3e.', min_f)
        for proc, best_val in zip(process_list, best_x.T):
            logger.info('%s: %.3e.', proc, best_val)

    # save results to disk
    if solution is not None:
        logger.info('Saving results to file.')
        solution.save()  # always save
        if args.save_txt:
            solution.save_txt()

    logger.info('Program finished!')

    # show all plots
    # the user needs to close the window to exit the program
    if not cte['no_plot']:
        if solution is not None:
            solution.plot()
        logger.info('Close the plot window to exit.')
        plt.show()


if __name__ == "__main__":
#    ext_args = ['config_file.cfg', '-c d']
    main()
