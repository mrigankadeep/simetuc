# -*- coding: utf-8 -*-
"""
Created on Fri Nov 18 17:22:18 2016

@author: Pedro
"""
import pytest
import numpy as np

from lmfit import Parameters

import simetuc.optimize as optimize
import simetuc.simulations as simulations
from simetuc.util import Excitation, IonType, DecayTransition, EneryTransferProcess, Transition
from simetuc.util import temp_bin_filename

@pytest.fixture(scope='function')
def setup_cte():
    '''Load the cte data structure'''

    class Cte(dict):
        __getattr__= dict.__getitem__
        __setattr__= dict.__setitem__
        __delattr__= dict.__delitem__

    cte = Cte({'energy_transfer': {
              'CR50': EneryTransferProcess([Transition(IonType.A, 5, 3),
                                            Transition(IonType.A, 0, 2)],
                                           mult=6, strength=2893199540.0, name='CR50'),
              'ETU53': EneryTransferProcess([Transition(IonType.A, 5, 6),
                                             Transition(IonType.A, 3, 1)],
                                            mult=6, strength=254295690.0, name='ETU53'),
              'ETU55': EneryTransferProcess([Transition(IonType.A, 5, 6),
                                             Transition(IonType.A, 5, 4)],
                                            mult=6, strength=0.0, name='ETU55'),
              'BackET': EneryTransferProcess([Transition(IonType.A, 3, 0),
                                              Transition(IonType.S, 0, 1)],
                                             mult=6, strength=4502.0, name='BackET'),
              'EM': EneryTransferProcess([Transition(IonType.S, 1, 0),
                                          Transition(IonType.S, 0, 1)],
                                         mult=6, strength=45022061400.0, name='EM'),
              'ETU1': EneryTransferProcess([Transition(IonType.S, 1, 0),
                                            Transition(IonType.A, 0, 2)],
                                           mult=6, strength=10000.0, name='ETU1')
              },
         'decay': {'branching_A': {DecayTransition(IonType.A, 1, 0, branching_ratio=1.0),
                DecayTransition(IonType.A, 2, 1, branching_ratio=0.4),
                DecayTransition(IonType.A, 3, 1, branching_ratio=0.3),
                DecayTransition(IonType.A, 4, 3, branching_ratio=0.999),
                DecayTransition(IonType.A, 5, 1, branching_ratio=0.15),
                DecayTransition(IonType.A, 5, 2, branching_ratio=0.16),
                DecayTransition(IonType.A, 5, 3, branching_ratio=0.04),
                DecayTransition(IonType.A, 5, 4, branching_ratio=0.0),
                DecayTransition(IonType.A, 6, 1, branching_ratio=0.43)},
               'branching_S': {DecayTransition(IonType.S, 1, 0, branching_ratio=1.0)},
               'decay_A': {DecayTransition(IonType.A, 1, 0, decay_rate=83.33333333333333),
                DecayTransition(IonType.A, 2, 0, decay_rate=40000.0),
                DecayTransition(IonType.A, 3, 0, decay_rate=500.0),
                DecayTransition(IonType.A, 4, 0, decay_rate=500000.0),
                DecayTransition(IonType.A, 5, 0, decay_rate=1315.7894736842104),
                DecayTransition(IonType.A, 6, 0, decay_rate=14814.814814814814)},
               'decay_S': {DecayTransition(IonType.S, 1, 0, decay_rate=400.0)}},
         'excitations': {
                  'NIR_1470': [Excitation(IonType.A, 5, 6, False, 9/5, 2e-4, 1e7, 1e-8)],
                 'NIR_800': [Excitation(IonType.A, 0, 3, False, 13/9, 0.0044, 1e7, 1e-8),
                             Excitation(IonType.A, 2, 5, False, 11/9, 0.002, 1e7, 1e-8)],
                 'NIR_980': [Excitation(IonType.S, 0, 1, False, 4/3, 0.0044, 1e7, 1e-8)],
                 'Vis_473': [Excitation(IonType.A, 0, 5, True, 13/9, 0.00093, 1e6, 1e-8)]},
         'ions': {'activators': 113, 'sensitizers': 0, 'total': 113},
         'lattice': {'A_conc': 0.3,
          'N_uc': 20,
          'S_conc': 0.3,
          'a': 5.9738,
          'alpha': 90.0,
          'b': 5.9738,
          'beta': 90.0,
          'c': 3.5297,
          'gamma': 120.0,
          'd_max': 100.0,
          'd_max_coop': 25.0,
          'name': 'bNaYF4',
          'sites_occ': [1.0, 0.5],
          'sites_pos': [(0.0, 0.0, 0.0),
           (0.6666666666666666, 0.3333333333333333, 0.5)],
          'spacegroup': 'P-6'},
         'no_console': False,
         'no_plot': False,
         'optimization': {'method': 'leastsq',
                          'processes': [EneryTransferProcess([Transition(IonType.A, 5, 3), Transition(IonType.A, 0, 2)],
                                                             mult=6, strength=2893199540.0, name='CR50'),
                                        DecayTransition(IonType.A, 3, 1, branching_ratio=0.3)],
                          'options': {}},
         'simulation_params': {'N_steps': 1000,
          'N_steps_pulse': 100,
          'atol': 1e-15,
          'rtol': 0.001},
         'states': {'activator_ion_label': 'Tm',
          'activator_states': 7,
          'activator_states_labels': ['3H6', '3F4', '3H5', '3H4', '3F3', '1G4', '1D2'],
          'energy_states': 791,
          'sensitizer_ion_label': 'Yb',
          'sensitizer_states': 2,
          'sensitizer_states_labels': ['GS', 'ES']}})

    cte['no_console'] = False
    cte['no_plot'] = True
    return cte

B_43 = DecayTransition(IonType.A, 3, 1, branching_ratio=0.3)
CR50 = EneryTransferProcess([Transition(IonType.A, 5, 3), Transition(IonType.A, 0, 2)],
                            mult=6, strength=2893199540.0, name='CR50')
def idfn_param(param):
    '''Returns the name of the test according to the parameters'''
    return 'method={}'.format(param)
def idfn_avg(param):
    '''Returns the name of the test according to the parameters'''
    return 'avg={}'.format(param)
def idfn_proc(param):
    '''Returns the name of the test according to the parameters'''
    return 'num={}'.format(len(param))
@pytest.mark.parametrize('method', ['COBYLA', 'L-BFGS-B', 'TNC',
                                    'SLSQP', 'brute_force', 'leastsq'],
                                    ids=idfn_param)
@pytest.mark.parametrize('average', [True, False], ids=idfn_avg)
@pytest.mark.parametrize('processes', [[CR50, B_43],
                                       [CR50],
                                       [B_43]], ids=idfn_proc)
@pytest.mark.parametrize('excitations', [[], ['Vis_473'],  ['Vis_473', 'NIR_980']],
                         ids=['default_exc', 'one_exc', 'two_exc'])
def test_optim(setup_cte, mocker, method, average, processes, excitations):
    '''Test that the optimization works'''
    # mock the simulation by returning an error that goes to 0
    init_param = np.array([proc.value for proc in processes])
    def mocked_optim_fun(params, sim, average):
        return 2 + (np.array([val for val in params.valuesdict().values()]) - 1.1*init_param)**2
    mocker.patch('simetuc.optimize.optim_fun', new=mocked_optim_fun)

    setup_cte['optimization']['method'] = method
    setup_cte['optimization']['processes'] = processes
    setup_cte['optimization']['excitations'] = excitations
    with temp_bin_filename() as temp_filename:
        best_x, min_f, res = optimize.optimize_dynamics(setup_cte, average=average,
                                                        full_path=temp_filename)

    assert len(best_x) == len(processes)
    if method in 'brute_force':
        assert min_f == np.sqrt(res.candidates[0].score)
    else:
        assert min_f == np.sqrt((res.residual**2).sum())

def test_optim_no_dict_params(setup_cte, mocker):
    '''Test that the optimization works with an empty optimization dict'''
    # mock the simulation by returning an error that goes to 0
    init_param = np.array([proc.value for proc in setup_cte.energy_transfer.values() if proc.value != 0])
    def mocked_optim_fun(params, sim, average):
        return 2 + (np.array([val for val in params.valuesdict().values()]) - 1.1*init_param)**2
    mocker.patch('simetuc.optimize.optim_fun', new=mocked_optim_fun)

    setup_cte['optimization'] = {}
    setup_cte['optimization']['processes'] = [proc for proc in setup_cte.energy_transfer.values() if proc.value != 0]
    setup_cte['optimization']['options'] = {}
    with temp_bin_filename() as temp_filename:
        best_x, min_f, res = optimize.optimize_dynamics(setup_cte, full_path=temp_filename)

    assert len(best_x) == len(init_param)
    assert min_f == np.sqrt((res.residual**2).sum())


def test_optim_wrong_method(setup_cte, mocker):
    '''Test that the optimization works without the optimization params being present in cte'''
    # mock the simulation by returning an error that goes to 0
    init_param = np.array([proc.value for proc in setup_cte['optimization']['processes']])
    def mocked_optim_fun(params, sim, average):
        return 2 + (np.array([val for val in params.valuesdict().values()]) - 1.1*init_param)**2
    mocker.patch('simetuc.optimize.optim_fun', new=mocked_optim_fun)

    setup_cte['optimization']['method'] = 'wrong_method'

    with pytest.raises(ValueError) as excinfo:
        with temp_bin_filename() as temp_filename:
            optimize.optimize_dynamics(setup_cte, full_path=temp_filename)
    assert excinfo.match(r"Wrong optimization method")
    assert excinfo.type == ValueError


@pytest.mark.parametrize('excitations', [[], ['Vis_473'],  ['Vis_473', 'NIR_980']],
                         ids=['default_exc', 'one_exc', 'two_exc'])
def test_optim_fun(setup_cte, mocker, excitations):
    '''Test optim_fun_factory'''
    mocked_dyn = mocker.patch('simetuc.simulations.Simulations.simulate_dynamics')
    class mocked_dyn_res:
        errors = np.ones((setup_cte.states['activator_states'] +
                          setup_cte.states['sensitizer_states'],), dtype=np.float64)
    mocked_dyn.return_value = mocked_dyn_res

    sim = simulations.Simulations(setup_cte)
    sim.cte['optimization']['excitations'] = excitations

    # Processes to optimize. If not given, all ET parameters will be optimized
    process_list = setup_cte.optimization['processes']
    # create a set of Parameters
    params = Parameters()
    for process in process_list:
        max_val = 1e15 if isinstance(process, EneryTransferProcess) else 1
        # don't let ET processes go to zero.
        min_val = 1 if isinstance(process, EneryTransferProcess) else 0
        params.add(process.name, value=process.value, min=min_val, max=max_val)

    optimize.optim_fun(params, sim, average=False)

    assert mocked_dyn.called

