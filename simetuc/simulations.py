# -*- coding: utf-8 -*-
"""
Created on Mon Nov  9 14:22:41 2015

@author: Villanueva
"""
# pylint: disable=E1101
# unused arguments, needed for ODE solver
# pylint: disable=W0613


import time
# read exp data
import csv
import logging
import warnings
import copy
import pickle

import numpy as np
import matplotlib.pyplot as plt

from scipy.sparse import csc_matrix
import scipy.signal as signal
from scipy.integrate import ode
import scipy.interpolate as interpolate

# nice progress bar
from tqdm import tqdm

import simetuc.setup as setup

#@profile
def _rate_eq_pulse(t, y, abs_matrix, decay_matrix, UC_matrix, N_indices):
    ''' Calculates the rhs of the ODE for the excitation pulse
    '''
    N_prod_sel = y[N_indices[:, 0]]*y[N_indices[:, 1]]
    UC_matrix = UC_matrix.dot(N_prod_sel)

    return abs_matrix.dot(y) + decay_matrix.dot(y) + UC_matrix

#@profile
def _jac_rate_eq_pulse(t, y, abs_matrix, decay_matrix, UC_matrix, jac_indices):
    ''' Calculates the jacobian of the ODE for the excitation pulse
    '''
    y_values = y[jac_indices[:, 2]]
    nJ_matrix = csc_matrix((y_values, (jac_indices[:, 0], jac_indices[:, 1])),
                           shape=(UC_matrix.shape[1], UC_matrix.shape[0]), dtype=np.float64)
    UC_J_matrix = UC_matrix.dot(nJ_matrix)

    return abs_matrix.toarray() + decay_matrix.toarray() + UC_J_matrix.toarray()

#@profile
def _rate_eq(t, y, decay_matrix, UC_matrix, N_indices):
    ''' Calculates the rhs of the ODE for the relaxation
    '''
    N_prod_sel = y[N_indices[:, 0]]*y[N_indices[:, 1]]
    UC_matrix = UC_matrix.dot(N_prod_sel)

    return decay_matrix.dot(y) + UC_matrix

#@profile
def _jac_rate_eq(t, y, decay_matrix, UC_matrix, jac_indices):
    ''' Calculates the jacobian of the ODE for the relaxation
    '''
    y_values = y[jac_indices[:, 2]]
    nJ_matrix = csc_matrix((y_values, (jac_indices[:, 0], jac_indices[:, 1])),
                           shape=(UC_matrix.shape[1], UC_matrix.shape[0]), dtype=np.float64)
    UC_J_matrix = UC_matrix.dot(nJ_matrix)
    jacobian = UC_J_matrix.toarray() + decay_matrix.toarray()

    return jacobian


class Solution():
    '''Base class for solutions of rate equation problems'''

    def __init__(self):
        self.t_sol = np.array([])
        self.y_sol = np.array([])
        self._list_avg_data = np.array([])
        self.cte_copy = {}
        self.index_S_i = np.array([])
        self.index_A_j = np.array([])

    def __bool__(self):
        '''Instance is True if all its data structures have been filled out'''
        return (self.t_sol != np.array([]) and self.y_sol != np.array([])
                and self.cte_copy  != np.array([])\
                and self.index_S_i  != np.array([]) and self.index_A_j != np.array([]))

    def _calculate_avg_populations(self):
        '''Returs the average populations of each state. First S then A states.'''

        cte = self.cte_copy
        index_S_i = self.index_S_i
        index_A_j = self.index_A_j
        y_sol = self.y_sol

        # average population of the ground and excited states of S
        if cte['ions']['sensitizers'] is not 0:
            sim_data_Sensitizer = []
            for state in range(cte['states']['sensitizer_states']):
                population = np.sum([y_sol[:, index_S_i[i]+state]
                                     for i in range(cte['ions']['total'])
                                     if index_S_i[i] != -1], 0)/cte['ions']['sensitizers']
                sim_data_Sensitizer.append(population)
        else:
            sim_data_Sensitizer = cte['states']['sensitizer_states']*[np.zeros((y_sol.shape[0],))]
        # average population of the ground and excited states of A
        if cte['ions']['activators'] is not 0:
            sim_data_Activator = []
            for state in range(cte['states']['activator_states']):
                population = np.sum([y_sol[:, index_A_j[i]+state]
                                     for i in range(cte['ions']['total'])
                                     if index_A_j[i] != -1], 0)/cte['ions']['activators']
                sim_data_Activator.append(population)
        else:
            sim_data_Activator = cte['states']['activator_states']*[np.zeros((y_sol.shape[0],))]

        return sim_data_Sensitizer+sim_data_Activator

    @property
    def list_avg_data(self):
        '''List of average populations for each state in the solution'''
        # if empty, calculate
        if not len(self._list_avg_data):
            self._list_avg_data = self._calculate_avg_populations()
        return self._list_avg_data

    def add_sim_data(self, t_sol, y_sol):
        '''Add the simulated solution data'''
        self.t_sol = t_sol
        self.y_sol = y_sol

    def copy_settings(self, cte):
        '''Copy the settings related to this solution'''
        self.cte_copy = copy.deepcopy(cte)

    def save(self, filename=None):
        '''Save all instance vars to disk (including those of derived classes)'''
        if filename is None:
            filename = str(solution.__class__).split('\'')[1].split('.')[1]
        with open(filename, 'wb') as file:
            pickle.dump(self.__dict__, file)

    def load(self, filename=None):
        '''Load all instance vars from disk (including those of derived classes)'''
        if filename is None:
            filename = str(solution.__class__).split('\'')[1].split('.')[1]
        with open(filename, 'rb') as file:
            tmp_dict = pickle.load(file)
        self.__dict__.update(tmp_dict)



class SteadyStateSolution(Solution):
    '''Class representing the solution to a steady state problem'''

    def __init__(self):
        super(SteadyStateSolution, self).__init__()
        self._final_populations = np.array([])

    def _calculate_final_populations(self):
        list_avg_data = self.list_avg_data
        return [curve[-1] for curve in list_avg_data]

    @property
    def stead_state_populations(self):
        '''List of final steady-state populations for each state in the solution'''
        # if empty, calculate
        if not len(self._final_populations):
            self._final_populations = self._calculate_final_populations()
        return self._final_populations


class DynamicsSolution(Solution):
    '''Class representing the solution to a dynamics problem.
        It handles the loading of experimetal decay data and calculates errors.'''

    def __init__(self):
        super(DynamicsSolution, self).__init__()

        self._list_exp_data = []
        self._list_avg_data_ofs = []

        self._total_error = None
        self._errors = np.array([])

    #@profile
    @staticmethod
    def _load_exp_data(filename, lattice_name, filter_window=11):
        ''' load data, two columns of numbers, first is time (seconds), second intensity
        '''
        if filename is None:
            return 0

        path = 'expData/'+lattice_name+'/'+filename
        try:
            with open(path, 'rt') as file:
                try:
                    data = csv.reader(file, delimiter='\t')
                    data = [row for row in data if row[0][0] is not '#']
                    data = np.array(data, dtype=np.float64)
                except ValueError:
                    data = csv.reader(file, delimiter=',')
                    data = [row for row in data if row[0][0] is not '#']
                    data = np.array(data, dtype=np.float64)
    #        data = np.loadtxt(path, usecols=(0, 1)) # 10x slower
        except FileNotFoundError:
            return 0

        if len(data) == 0:
            return 0

        # smooth the data to get an "average" of the maximum
        smooth_data = signal.savgol_filter(data[:, 1], filter_window, 2, mode='nearest')

        # normalize data
        data[:, 1] = (data[:, 1]-min(smooth_data))/(max(smooth_data)-min(smooth_data))

        # set negative values to zero
        data = data.clip(min=0)

        return data

    #@profile
    @staticmethod
    def _correct_background(exp_data, sim_data, offset_points=50):
        ''' expData is already normalized
        '''
        if not np.any(exp_data): # if there's no experimental data, don't do anything
            return sim_data
        if not np.any(sim_data):
            return 0

        last_points = exp_data[-offset_points:, 1] # get last points
        offset = np.mean(last_points[last_points > 0])*max(sim_data)

        if np.isnan(offset): # offset-correct simulated data
            sim_data_ofs = sim_data
        else:
            sim_data_ofs = sim_data+offset

        return sim_data_ofs

    #@profile
    @staticmethod
    def _interpolate_sim_data(exp_time, sim_data):
        ''' interpolated simulated data. Returns a callable object
        '''
        interp_sim_data = interpolate.interp1d(exp_time, sim_data, fill_value='extrapolate')
        return interp_sim_data

    #@profile
    def _calc_errors(self):
        ''' calculate root-square-deviation between experiment and simulation
        '''
        # first iterpolate simulation to experimental data points
        list_iterp_sim_funcs = [DynamicsSolution._interpolate_sim_data(self.t_sol, simData_corr)
                                if simData_corr is not 0 else 0
                                for simData_corr in self.list_avg_data_ofs]
        list_iterp_sim_data = [iterpFun(expData[:, 0])
                               if (expData is not 0) and (iterpFun is not 0) else 0
                               for (iterpFun, expData) in zip(list_iterp_sim_funcs,
                                                              self.list_exp_data)]

        # calculate the relative mean square deviation
        # error = 1/mean(y)*sqrt(sum( (y-yexp)^2 )/N )
        rmdevs = [(sim-exp[:, 1]*np.max(sim))**2
                  if (exp is not 0) and (sim is not 0) else 0
                  for (sim, exp) in zip(list_iterp_sim_data, self.list_exp_data)]
        errors = [1/np.mean(sim)*np.sqrt(1/len(sim)*np.sum(rmdev))
                  if rmdev is not 0 else 0
                  for (rmdev, sim) in zip(rmdevs, list_iterp_sim_data)]
        errors = np.array(errors)

        return errors

    def _correct_dynamics_sim_data(self):
        '''Return the corrected simulated data accounting for the experimental background'''

        list_avg_data_ofs = [DynamicsSolution._correct_background(expData, simData)
                             for expData, simData in zip(self.list_exp_data, self.list_avg_data)]

        return list_avg_data_ofs

    def _get_ion_state_labels(self) -> list:
        '''Returns a list of ion_state labels'''

        cte = self.cte_copy
        sensitizer_labels = [cte['states']['sensitizer_ion_label'] + '_' + s
                             for s in cte['states']['sensitizer_states_labels']]
        activator_labels = [cte['states']['activator_ion_label'] + '_' + s
                            for s in cte['states']['activator_states_labels']]
        state_labels = sensitizer_labels + activator_labels

        return state_labels

    def _load_decay_data(self):
        '''Loads the decay experimental data.
        '''
        # get filenames from the ion_state labels
        state_labels = self._get_ion_state_labels()
        active_exc_labels = [label for label, exc_dict in self.cte_copy['excitations'].items()
                             if exc_dict['active']]
        exc_label = '_'.join(active_exc_labels)
        exp_data_filenames = ['decay_' + label + '_exc_' + exc_label + '.txt'
                              for label in state_labels]
        # if exp data doesn't exist, it's set to zero inside the function
        list_exp_data = [self._load_exp_data(filename, self.cte_copy['lattice']['name'])
                         for filename in exp_data_filenames]

        return list_exp_data

    def log_errors(self):
        '''Simulate dynamics, load exp data and calculate errors. No plots'''
        logger = logging.getLogger(__name__)

        # get state labels
        state_labels = self._get_ion_state_labels()

        # log errors them
        if state_labels is not None:
            logger.info('State errors: ')
            for (label, error) in zip(state_labels, self.errors):
                logger.info('%s: %.4e', label, error)
        logger.info('Total error: %.4e', self.total_error)

    @property
    def errors(self):
        '''List of root-square-deviation between experiment and simulation
            for each state in the solution
        '''
        # if empty, calculate
        if not len(self._errors):
            self._errors = self._calc_errors()
        return self._errors

    @property
    def total_error(self):
        '''Total root-square-deviation between experiment and simulation'''
        # if none, calculate
        if not self._total_error:
            if np.any(self.errors):
                total_error = np.sqrt(np.mean(np.square(self.errors[self.errors > 0])))
            else:
                total_error = 0
            self._total_error = total_error
        return self._total_error

    @property
    def list_avg_data_ofs(self):
        '''List of ofset-corrected average populations for each state in the solution'''
        # if empty, calculate
        if not self._list_avg_data_ofs:
            self._list_avg_data_ofs = self._correct_dynamics_sim_data()
        return self._list_avg_data_ofs

    @property
    def list_exp_data(self):
        '''List of ofset-corrected average populations for each state in the solution'''
        # if empty, calculate
        if not self._list_exp_data:
            self._list_exp_data = self._load_decay_data()
        return self._list_exp_data


class Plotter():
    '''Plot different solutions to rate equations problems'''

    @staticmethod
    def plot_avg_decay_data(solution: Solution, state_labels=None, atol=1e-15):
        ''' Plots the list of experimental and average simulated data against t_sol in solution
        '''

        # if we have simulated data that has been offset-corrected, use it
        if hasattr(solution, 'list_avg_data_ofs'):
            list_sim_data = solution.list_avg_data_ofs[:]
        else:
            list_sim_data = solution.list_avg_data[:]

        num_plots = len(list_sim_data)
        num_rows = 3
        num_cols = int(np.ceil(num_plots/3))
        t_sol = solution.t_sol[:]*1000 # convert to ms

        if not hasattr(solution, 'list_exp_data') or solution.list_exp_data is None:
            list_exp_data = len(list_sim_data)*[0]
        else:
            list_exp_data = solution.list_exp_data[:] # make copy

        if state_labels is None:
            state_labels = len(list_sim_data)*[' ']

        for num, (sim_data_corr, exp_data, state_label)\
        in enumerate(zip(list_sim_data, list_exp_data, state_labels)):
            if sim_data_corr is 0:
                continue
            if (np.isnan(sim_data_corr)).any() or not np.any(sim_data_corr > 0):
                continue

            plt.subplot(num_rows, num_cols, num+1)

            if exp_data is 0: # no exp data: either a GS or simply no exp data available
                # nonposy='clip': clip non positive values to a very small positive number
                plt.semilogy(t_sol, sim_data_corr, 'r', label=state_label, nonposy='clip')
                plt.yscale('log', nonposy='clip')
                plt.axis('tight')
                # add some white space above and below
                margin_factor = np.array([0.7, 1.3])
                plt.ylim(*np.array(plt.ylim())*margin_factor)
                if plt.ylim()[0] < atol:
                    plt.ylim(ymin=atol) # don't show noise below atol
                    # detect when the simulation goes above and below atol
                    above = sim_data_corr > atol
                    change_indices = np.where(np.roll(above, 1) != above)[0]
                    if change_indices.size > 0:
                        # last time it changes
                        max_index = change_indices[-1]
                        # show simData until it falls below atol
                        plt.xlim(xmax=t_sol[max_index])
            else: # exp data available
                # convert exp_data time to ms
                plt.semilogy(exp_data[:, 0]*1000, exp_data[:, 1]*np.max(sim_data_corr),
                             'k', t_sol, sim_data_corr, 'r', label=state_label)
                plt.axis('tight')
                plt.ylim(ymax=plt.ylim()[1]*1.2) # add some white space on top
                plt.xlim(xmax=exp_data[-1, 0]*1000) # don't show beyond expData

            plt.legend(loc="best")
            plt.xlabel('t (ms)')

    @staticmethod
    def plot_state_decay_data(t_sol, sim_data_array, state_label=None, atol=1e-15):
        ''' Plots a state's simulated data against t_sol
        '''
        t_sol *= 1000 # convert to ms

        if sim_data_array is 0:
            return
        if (np.isnan(sim_data_array)).any() or not np.any(sim_data_array):
            return

        avg_sim = np.mean(sim_data_array, axis=1)

        # nonposy='clip': clip non positive values to a very small positive number
        plt.semilogy(t_sol, sim_data_array, 'k', nonposy='clip')
        plt.semilogy(t_sol, avg_sim, 'r', nonposy='clip', linewidth=5)
        plt.yscale('log', nonposy='clip')
        plt.axis('tight')
        # add some white space above and below
        margin_factor = np.array([0.7, 1.3])
        plt.ylim(*np.array(plt.ylim())*margin_factor)
        if plt.ylim()[0] < atol:
            plt.ylim(ymin=atol) # don't show noise below atol
            # detect when the simulation goes above and below atol
            above = sim_data_array > atol
            change_indices = np.where(np.roll(above, 1) != above)[0]
            if change_indices.size > 0:
                # last time it changes
                max_index = change_indices[-1]
                # show simData until it falls below atol
                plt.xlim(xmax=t_sol[max_index])

        plt.legend([state_label], loc="best")
        plt.xlabel('t (ms)')

    @staticmethod
    def plot_power_dependence(power_dens_arr, sim_data_arr,
                              state_labels=None, exp_data_arr=None, slopes=None):
        ''' Plots the intensity as a function of power density for each state
        '''
        num_plots = len(state_labels)
        num_rows = 3
        num_cols = int(np.ceil(num_plots/3))

        for num, state_label in enumerate(state_labels):
            sim_data = sim_data_arr[:, num]
            if not np.any(sim_data):
                continue

            axis = plt.subplot(num_rows, num_cols, num+1)

            plt.loglog(power_dens_arr, sim_data, '.-r', mfc='k', ms=10, label=state_label)
            plt.axis('tight')
            margin_factor = np.array([0.7, 1.3])
            plt.ylim(*np.array(plt.ylim())*margin_factor) # add some white space on top
            plt.xlim(*np.array(plt.xlim())*margin_factor)

            plt.legend(loc="best")
            plt.xlabel('Power density / W/cm^2')

            if slopes is not None:
                for i, txt in enumerate(slopes[num]):
                    axis.annotate(txt, (power_dens_arr[i], sim_data[i]), xytext=(5, -7),
                                  xycoords='data', textcoords='offset points')

    @staticmethod
    def plot_concentration_dependence(concentration_list, conc_dependence, state_labels=None):
        '''Plots the concentration dependence of the emission'''
        pass


class Simulations():
    '''Setup and solve a dynamics or a steady state problem'''

    def __init__(self, cte):
        self.cte = cte
        self.plotter = Plotter()

    def get_settings(self):
        '''Get the settings dictionary'''
        return self.cte

    def modify_ET_param_value(self, process, value):
        '''Modify a ET parameter'''
        self.cte['ET'][process]['value'] = value

    #@profile
    @staticmethod
    def _solve_ode(t_arr, fun, fargs, jfun, jargs, initial_population,
                   rtol=1e-3, atol=1e-5, nsteps=500, method='bdf', quiet=True):
        ''' Solve the ode for the times t_arr using rhs fun and jac jfun
            with their arguments as tuples.
        '''
        logger = logging.getLogger(__name__)

        N_steps = len(t_arr)
        y_arr = np.zeros((N_steps, len(initial_population)), dtype=np.float64)

        # setup the ode solver with the method
        ode_obj = ode(fun, jfun)
        ode_obj.set_integrator('vode', rtol=rtol, atol=atol, method=method, nsteps=nsteps)
        ode_obj.set_initial_value(initial_population, t_arr[0])
        ode_obj.set_f_params(*fargs)
        ode_obj.set_jac_params(*jargs)

        # initial conditions
        y_arr[0, :] = initial_population
        step = 1

        # console bar enabled for INFO
        # this doesn't work, as there are two handlers with different levels
        cmd_bar_disable = quiet
        pbar_cmd = tqdm(total=N_steps, unit='step', smoothing=0.1,
                        disable=cmd_bar_disable, desc='ODE progress')

        # catch numpy warnings and log them
        # DVODE (the internal routine used by the integrator 'vode') will throw a warning
        # if it needs too many steps to solve the ode.
        np.seterr(all='raise')
        with warnings.catch_warnings():
            # transform warnings into exceptions that we can catch
            warnings.filterwarnings('error')
            try:
                while ode_obj.successful() and step < N_steps:
                    # advance ode to the next time step
                    y_arr[step, :] = ode_obj.integrate(t_arr[step])
                    step += 1
                    pbar_cmd.update(1)
            except UserWarning as err:
                logger.warning(err)
                logger.warning('Most likely the ode solver is taking too many steps.')
                logger.warning('Either change your settings or increase "nsteps".')
                logger.warning('The program will continue, but the accuracy of the ' +
                               'results cannot be guaranteed.')
        np.seterr(all='ignore') # restore settings

        pbar_cmd.update(1)
        pbar_cmd.close()

        return y_arr

    def _get_ion_state_labels(self) -> list:
        '''Returns a list of ion_state labels'''

        cte = self.cte
        sensitizer_labels = [cte['states']['sensitizer_ion_label'] + '_' + s
                             for s in cte['states']['sensitizer_states_labels']]
        activator_labels = [cte['states']['activator_ion_label'] + '_' + s
                            for s in cte['states']['activator_states_labels']]
        state_labels = sensitizer_labels + activator_labels

        return state_labels

    def plot_solution(self, solution: Solution, state=None):
        '''Plot the soltion of a problem.
            If state is given, the population of only that state for all ions
            is shown along with the average.
        '''

        # get ion_state labels
        state_labels = self._get_ion_state_labels()

        if state is None:
            self.plotter.plot_avg_decay_data(solution,
                                             state_labels=state_labels, atol=1e-15)
        elif state < len(state_labels):
            if state < self.cte['states']['sensitizer_states']:
                indices = solution.index_S_i
            else:
                indices = solution.index_A_j
            label = state_labels[state]
            population = np.array([solution.y_sol[:, index+state]
                                   for index in indices if index != -1])
            self.plotter.plot_state_decay_data(solution.t_sol, population.T,
                                               state_label=label, atol=1e-18)

    #@profile
    def simulate_dynamics(self) -> DynamicsSolution:
        ''' Simulates the absorption, decay and energy transfer processes contained in cte
            Returns  (t_sol, list_avg_data, y_sol) and stores it in the dynamics_sol instance var
        '''
        logger = logging.getLogger(__name__)

        #psutil.cpu_percent() # reset cpu usage counter
        #mem_usage = memory_usage(-1, interval=.2, timeout=1) # record RAM usage
        start_time = time.time()
        logger.info('Starting simulation...')

        # get matrices of interaction, initial conditions, abs, decay, etc
        (cte, initial_population, index_S_i, index_A_j,
         total_abs_matrix, decay_matrix,
         UC_matrix,
         N_indices, jac_indices) = setup.precalculate(self.cte)

        self.cte = cte

        # initial and final times for excitation and relaxation
        t0 = 0
        tf = (10*np.max(setup.get_lifetimes(cte))).round(8) # total simulation time
        t0_p = t0
        # make sure t_pulse exists and get the active one
        try:
            for exc_dict in self.cte['excitations'].values():
                if exc_dict['active']:
                    tf_p = exc_dict['t_pulse'] # pulse width.
                    break
            type(tf_p)
        except (KeyError, NameError):
            logger.error('t_pulse value not found!')
            logger.error('Please add t_pulse to your excitation settings.')
            raise
        N_steps_pulse = 2 #self.cte['simulation_params']['N_steps_pulse']
        t0_sol = tf_p
        tf_sol = tf
        N_steps = self.cte['simulation_params']['N_steps']

        rtol = self.cte['simulation_params']['rtol']
        atol = self.cte['simulation_params']['atol']

        start_time_ODE = time.time()
        logger.info('Solving equations...')

        # excitation pulse
        logger.info('Solving excitation pulse...')
        t_pulse = np.linspace(t0_p, tf_p, N_steps_pulse, dtype=np.float64)
        y_pulse = self._solve_ode(t_pulse, _rate_eq_pulse,
                                  (total_abs_matrix, decay_matrix, UC_matrix, N_indices),
                                  _jac_rate_eq_pulse,
                                  (total_abs_matrix, decay_matrix, UC_matrix, jac_indices),
                                  initial_population.transpose(), method='adams',
                                  rtol=rtol, atol=atol, quiet=self.cte['no_console'])

        # relaxation
        logger.info('Solving relaxation...')
        t_sol = np.logspace(np.log10(t0_sol), np.log10(tf_sol), N_steps, dtype=np.float64)
        y_sol = self._solve_ode(t_sol, _rate_eq, (decay_matrix, UC_matrix, N_indices),
                                _jac_rate_eq, (decay_matrix, UC_matrix, jac_indices),
                                y_pulse[-1, :], rtol=rtol, atol=atol,
                                nsteps=1000, quiet=self.cte['no_console'])

        formatted_time = time.strftime("%Mm %Ss", time.localtime(time.time()-start_time_ODE))
        logger.info('Equations solved! Total time: %s.', formatted_time)
        total_time = time.time()-start_time
        formatted_time = time.strftime("%Mm %Ss", time.localtime(total_time))
        logger.info('Simulation finished! Total time: %s.', formatted_time)

        # store solution and settings
        dynamics_sol = DynamicsSolution()
        dynamics_sol.add_sim_data(t_sol, y_sol)
        dynamics_sol.copy_settings(cte)
        dynamics_sol.index_S_i = index_S_i
        dynamics_sol.index_A_j = index_A_j

        return dynamics_sol

    def simulate_steady_state(self):
        ''' Simulates the steady state of the problem
            Returns (final_populations, total_time, cte)
        '''
        logger = logging.getLogger(__name__)

        cte = self.cte

        start_time = time.time()
        logger.info('Starting simulation...')

        # get matrices of interaction, initial conditions, abs, decay, etc
        (cte, initial_population, index_S_i, index_A_j,
         total_abs_matrix, decay_matrix,
         UC_matrix,
         N_indices, jac_indices) = setup.precalculate(cte)

        # initial and final times for excitation and relaxation
        t0 = 0
        tf = (10*np.max(setup.get_lifetimes(cte))).round(8) # total simulation time
        t0_p = t0
        tf_p = tf
        N_steps_pulse = cte['simulation_params']['N_steps']

        rtol = cte['simulation_params']['rtol']
        atol = cte['simulation_params']['atol']

        start_time_ODE = time.time()
        logger.info('Solving equations...')

        # steady state
        logger.info('Solving steady state...')
        t_pulse = np.linspace(t0_p, tf_p, N_steps_pulse)
        y_pulse = self._solve_ode(t_pulse, _rate_eq_pulse,
                                  (total_abs_matrix, decay_matrix, UC_matrix, N_indices),
                                  _jac_rate_eq_pulse,
                                  (total_abs_matrix, decay_matrix, UC_matrix, jac_indices),
                                  initial_population.transpose(), nsteps=1000,
                                  rtol=rtol, atol=atol, quiet=cte['no_console'])

        logger.info('Equations solved! Total time: %.2fs.', time.time()-start_time_ODE)

        # store solution and settings
        steady_sol = SteadyStateSolution()
        steady_sol.add_sim_data(t_pulse, y_pulse)
        steady_sol.copy_settings(cte)
        steady_sol.index_S_i = index_S_i
        steady_sol.index_A_j = index_A_j

        # get filenames from the ion_state labels
        state_labels = self._get_ion_state_labels()

        logger.info('Steady state populations: ')
        for (label, population) in zip(state_labels, steady_sol.stead_state_populations):
            logger.info('%s: %.4e', label, population)

        total_time = time.time()-start_time
        formatted_time = time.strftime("%Mm %Ss", time.localtime(total_time))
        logger.info('Simulation finished! Total time: %s.', formatted_time)

        return steady_sol

    def simulate_power_dependence(self, power_dens_list):
        ''' Simulates the power dependence
            Returns an array with columns for the power dependence of the state emission
            The first column is power_dens_list
        '''
        logger = logging.getLogger(__name__)
        logger.info('Simulating power dependence curves...')

        cte = self.cte

        start_time = time.time()

        old_no_plot = cte['no_plot']
        cte['no_plot'] = True

        num_states = cte['states']['sensitizer_states'] + cte['states']['activator_states']
        num_power_steps = len(power_dens_list)
        power_dependence = np.zeros((num_power_steps, num_states), dtype=np.float64)

        for num, power_dens in tqdm(enumerate(power_dens_list), unit='points',
                                    total=num_power_steps, disable=cte['no_console'],
                                    desc='Total progress'):
            # update power density
            for excitation in cte['excitations'].keys():
                cte['excitations'][excitation]['power_dens'] = power_dens
            # calculate steady state populations
            steady_sol = self.simulate_steady_state()
            power_dependence[num, :] = np.array(steady_sol.stead_state_populations)


        cte['no_plot'] = old_no_plot
        # get state labels
        state_labels = self._get_ion_state_labels()

        # calculate the slopes for each consecutive pair of points in the curves
        Y = np.log10(power_dependence)[:-1, :]
        X = np.log10(power_dens_list)
        dX = (np.roll(X, -1, axis=0) - X)[:-1]
        # list of slopes
        slopes = [np.gradient(Y_arr, dX) for Y_arr in Y.T]
        slopes = np.around(slopes, 1)

        # plot power dependence curves
        if not cte['no_plot']:
            self.plotter.plot_power_dependence(power_dens_list, power_dependence,
                                               state_labels, slopes=slopes)

        total_time = time.time()-start_time
        formatted_time = time.strftime("%Mm %Ss", time.localtime(total_time))
        logger.info('Power dependence curves finished! Total time: %s.', formatted_time)

        return power_dependence

    def simulate_concentration_dependence(self, concentration_list):
        ''' Simulates the concentration dependence of the emission
            Returns an array with columns for the concentration dependence of the state emission
            The firs columns is concentration_list, a list of tuples with the S and A concentrations
        '''
        logger = logging.getLogger(__name__)
        logger.info('Simulating power dependence curves...')

        cte = self.cte

        start_time = time.time()

        old_no_plot = cte['no_plot']
        cte['no_plot'] = True

        num_conc_steps = len(concentration_list)
        conc_dependence = []

        for concs in tqdm(concentration_list, unit='points',
                          total=num_conc_steps, disable=cte['no_console'],
                          desc='Total progress'):
            # update concentrations
            cte['lattice']['S_conc'] = concs[0]
            cte['lattice']['A_conc'] = concs[1]
            # calculate avg populations
            solution = self.simulate_dynamics()
            conc_dependence.append(np.array(solution.list_avg_data))


        cte['no_plot'] = old_no_plot
        # get state labels
        state_labels = self._get_ion_state_labels()

        # plot concentration dependence curves
        if not cte['no_plot']:
            self.plotter.plot_concentration_dependence(concentration_list,
                                                       conc_dependence, state_labels)

        total_time = time.time()-start_time
        formatted_time = time.strftime("%Mm %Ss", time.localtime(total_time))
        logger.info('Power dependence curves finished! Total time: %s.', formatted_time)

        return conc_dependence


if __name__ == "__main__":
    logger = logging.getLogger()
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s')

    logger.info('Called from cmd.')

    import simetuc.settings as settings
    cte = settings.load('config_file.txt')

    cte['no_console'] = False
    cte['no_plot'] = False

    sim = Simulations(cte)

    solution = sim.simulate_dynamics()
    solution.log_errors()

#    solution = sim.simulate_steady_state()

    sim.plot_solution(solution)


#    power_dens_list = np.logspace(1, 8, 8-1+1)
#    power_dependence = sim.simulate_power_dependence(power_dens_list)

#    conc_list = [(0, 0.1), (0, 0.3)]
#    conc_dependence = sim.simulate_concentration_dependence(conc_list)
