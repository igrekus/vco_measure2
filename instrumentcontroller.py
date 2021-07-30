import ast
import time

import numpy as np

from collections import defaultdict
from PyQt5.QtCore import QObject, pyqtSlot, pyqtSignal

from instr.instrumentfactory import mock_enabled, GeneratorFactory, SourceFactory, MultimeterFactory, AnalyzerFactory
from measureresult import MeasureResult
from util.file import load_ast_if_exists, pprint_to_file

GIGA = 1_000_000_000
MEGA = 1_000_000
KILO = 1_000
MILLI = 1 / 1_000


class SecondaryParams:
    def __init__(self, required):
        self._required = required
        self._params = None

    @property
    def params(self):
        if self._params is None:
            self._params = {
                k: v[1]['value'] for k, v in self._required.items()
            }
        return self._params

    @params.setter
    def params(self, d):
        self._params = d

    @property
    def required(self):
        return dict(**self._required)

    def load_from_config(self, file):
        self.params = load_ast_if_exists(file, default=self.params)


class InstrumentController(QObject):
    pointReady = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent=parent)

        addrs = load_ast_if_exists('instr.ini', default={
            'Анализатор': 'GPIB1::18::INSTR',
            'P LO': 'GPIB1::6::INSTR',
            'P RF': 'GPIB1::20::INSTR',
            'Источник': 'GPIB1::3::INSTR',
            'Мультиметр': 'GPIB1::22::INSTR',
        })

        self.requiredInstruments = {
            'Анализатор': AnalyzerFactory(addrs['Анализатор']),
            'P LO': GeneratorFactory(addrs['P LO']),
            'P RF': GeneratorFactory(addrs['P RF']),
            'Источник': SourceFactory(addrs['Источник']),
            'Мультиметр': MultimeterFactory(addrs['Мультиметр']),
        }

        self.deviceParams = {
            'Модулятор': {
                'F': 1,
            },
        }

        self.secondaryParams = SecondaryParams(
            required={
                'Plo': [
                    'Pгет=',
                    {'start': -30.0, 'end': 30.0, 'step': 1.0, 'value': -5.0, 'suffix': ' дБм'}
                ],
                'Pmod': [
                    'Pмод=',
                    {'start': -30.0, 'end': 30.0, 'step': 1.0, 'value': -5.0, 'suffix': ' дБм'}
                ],
                'Flo_min': [
                    'Fгет.мин=',
                    {'start': 0.0, 'end': 40.0, 'step': 1.0, 'decimals': 3, 'value': 0.6, 'suffix': ' ГГц'}
                ],
                'Flo_max': [
                    'Fгет.макс=',
                    {'start': 0.0, 'end': 40.0, 'step': 1.0, 'decimals': 3, 'value': 6.6, 'suffix': ' ГГц'}
                ],
                'Flo_delta': [
                    'ΔFгет=',
                    {'start': 0.0, 'end': 40.0, 'step': 0.1, 'decimals': 3, 'value': 1.0, 'suffix': ' ГГц'}
                ],
                'is_Flo_div2': [
                    '1/2 Fгет.',
                    {'value': False}
                ],
                'Fmod_min': [
                    'Fмод.мин=',
                    {'start': 0.0, 'end': 1000.0, 'step': 1.0, 'decimals': 3, 'value': 1.0, 'suffix': ' МГц'}
                ],
                'Fmod_max': [
                    'Fмод.макс=',
                    {'start': 0.0, 'end': 1000.0, 'step': 1.0, 'decimals': 3, 'value': 501.0, 'suffix': ' МГц'}
                ],
                'Fmod_delta': [
                    'ΔFмод=',
                    {'start': 0.0, 'end': 1000.0, 'step': 1.0, 'decimals': 3, 'value': 10.0, 'suffix': ' МГц'}
                ],
                'Uoffs': [
                    'Uсм=',
                    {'start': 0.0, 'end': 1000.0, 'step': 1, 'decimals': 1, 'value': 250.0, 'suffix': ' мВ'}
                ],
                'Usrc': [
                    'Uпит.=',
                    {'start': 4.75, 'end': 5.25, 'step': 0.25, 'value': 5.0, 'suffix': ' В'}
                ],
                'sa_rlev': [
                    'Ref. lev.=',
                    {'start': -30.0, 'end': 30.0, 'step': 1.0, 'value': 10.0, 'suffix': ' дБ'}
                ],
                'sa_scale_y': [
                    'Scale y=',
                    {'start': 0.0, 'end': 30.0, 'step': 1.0, 'value': 10.0, 'suffix': ' дБ'}
                ],
                'sa_span': [
                    'Span=',
                    {'start': 0.0, 'end': 1000.0, 'step': 1.0, 'value': 10.0, 'suffix': ' МГц'}
                ],
                'sa_avg_state': [
                    'Avg.state=',
                    {'value': False}
                ],
                'sa_avg_count': [
                    'Avg.count=',
                    {'start': 0.0, 'end': 1000.0, 'step': 1.0, 'value': 16.0, 'suffix': ''}
                ],
                'sep_1': ['', {'value': None}],
                'u_min': [
                    'Uмин.=',
                    {'start': 0.0, 'end': 30.0, 'step': 0.05, 'value': 4.75, 'suffix': ' В'}
                ],
                'u_max': [
                    'Uмакс.=',
                    {'start': 0.0, 'end': 30.0, 'step': 0.05, 'value': 5.25, 'suffix': ' В'}
                ],
                'u_delta': [
                    'ΔU=',
                    {'start': 0.0, 'end': 30.0, 'step': 0.05, 'value': 0.05, 'suffix': ' В'}
                ],
            }
        )
        self.secondaryParams.load_from_config('params.ini')

        self._calibrated_pows_lo = load_ast_if_exists('cal_lo.ini', default={})
        self._calibrated_pows_mod = load_ast_if_exists('cal_mod.ini', default={})
        self._calibrated_pows_rf = load_ast_if_exists('cal_rf.ini', default={})

        self._instruments = dict()
        self.found = False
        self.present = False
        self.hasResult = False
        self.only_main_states = False

        self.result = MeasureResult()

    def __str__(self):
        return f'{self._instruments}'

    def connect(self, addrs):
        print(f'searching for {addrs}')
        for k, v in addrs.items():
            self.requiredInstruments[k].addr = v
        self.found = self._find()

    def _find(self):
        self._instruments = {
            k: v.find() for k, v in self.requiredInstruments.items()
        }
        return all(self._instruments.values())

    def check(self, token, params):
        print(f'call check with {token} {params}')
        device, secondary = params
        self.present = self._check(token, device, secondary)
        print('sample pass')

    def _check(self, token, device, secondary):
        print(f'launch check with {self.deviceParams[device]} {self.secondaryParams}')
        self._init()
        return True

    def calibrate(self, token, params):
        print(f'call calibrate with {token} {params}')
        return self._calibrate(token, self.secondaryParams)

    def _calibrateLO(self, token, secondary):
        print('run calibrate LO with', secondary)

        gen_lo = self._instruments['P LO']
        sa = self._instruments['Анализатор']

        secondary = self.secondaryParams

        lo_pow = secondary['Plo']
        lo_f_start = secondary['Flo_min'] * GIGA
        lo_f_end = secondary['Flo_max'] * GIGA
        lo_f_step = secondary['Flo_delta'] * GIGA

        lo_f_is_div2 = secondary['is_Flo_div2']

        sa_rlev = secondary['sa_rlev']
        sa_scale_y = secondary['sa_scale_y']
        sa_span = secondary['sa_span'] * MEGA

        freq_lo_values = [round(x, 3) for x in
                          np.arange(start=lo_f_start, stop=lo_f_end + 0.0001, step=lo_f_step)]

        sa.send(':CAL:AUTO OFF')
        sa.send(':SENS:FREQ:SPAN 1MHz')
        sa.send(f'DISP:WIND:TRAC:Y:RLEV 10')
        sa.send(f'DISP:WIND:TRAC:Y:PDIV 5')

        gen_lo.send(f'SOUR:POW {lo_pow}dbm')
        gen_lo.send(f':OUTP:MOD:STAT OFF')

        sa.send(':CALC:MARK1:MODE POS')
        sa.send(f':SENS:FREQ:SPAN {sa_span}Hz')
        sa.send(f'DISP:WIND:TRAC:Y:RLEV {sa_rlev}')
        sa.send(f'DISP:WIND:TRAC:Y:PDIV {sa_scale_y}')

        gen_lo.send(f'OUTP:STAT ON')

        result = defaultdict(dict)
        for freq in freq_lo_values:

            freq_gen = freq
            if lo_f_is_div2:
                freq_gen *= 2

            if token.cancelled:
                gen_lo.send(f'OUTP:STAT OFF')
                time.sleep(0.5)

                gen_lo.send(f'SOUR:POW {lo_pow}dbm')

                gen_lo.send(f'SOUR:FREQ {lo_f_start}GHz')
                raise RuntimeError('calibration cancelled')

            gen_lo.send(f'SOUR:POW {lo_pow}dbm')
            gen_lo.send(f'SOUR:FREQ {freq_gen}Hz')

            if not mock_enabled:
                time.sleep(0.5)

            sa.send(f':SENSe:FREQuency:CENTer {freq_gen}Hz')

            if not mock_enabled:
                time.sleep(0.5)

            sa.send(f':CALCulate:MARKer1:X {freq_gen}Hz')
            pow_read = float(sa.query(':CALCulate:MARKer:Y?'))
            loss = abs(lo_pow - pow_read)
            if mock_enabled:
                loss = 10

            print('loss: ', loss)
            result[lo_pow][freq_gen] = loss

        result = {k: v for k, v in result.items()}
        pprint_to_file('cal_lo.ini', result)

        gen_lo.send(f'OUTP:STAT OFF')
        sa.send(':CAL:AUTO ON')
        self._calibrated_pows_lo = result
        return True

    def _calibrateRF(self, token, secondary):
        print('run calibrate RF')

        def set_read_marker(freq):
            sa.send(f':CALCulate:MARKer1:X {freq}Hz')
            if not mock_enabled:
                time.sleep(0.01)
            return float(sa.query(':CALCulate:MARKer:Y?'))

        secondary = self.secondaryParams

        gen_lo = self._instruments['P LO']
        src = self._instruments['Источник']
        sa = self._instruments['Анализатор']

        lo_pow = secondary['Plo']
        lo_f_start = secondary['Flo_min'] * GIGA
        lo_f_end = secondary['Flo_max'] * GIGA
        lo_f_step = secondary['Flo_delta'] * GIGA

        lo_f_is_div2 = secondary['is_Flo_div2']

        mod_f_min = secondary['Fmod_min'] * MEGA
        mod_f_max = secondary['Fmod_max'] * MEGA
        mod_f_delta = secondary['Fmod_delta'] * MEGA

        src_u = secondary['Usrc']
        src_i_max = 200  # mA

        sa_rlev = secondary['sa_rlev']
        sa_scale_y = secondary['sa_scale_y']
        sa_span = secondary['sa_span'] * MEGA
        sa_avg_state = 'ON' if secondary['sa_avg_state'] else 'OFF'
        sa_avg_count = secondary['sa_avg_count']

        mod_f_values = [
            round(x, 3) for x in
            np.arange(start=mod_f_min, stop=mod_f_max + 0.0002, step=mod_f_delta)
        ]

        freq_lo_values = [
            round(x, 3) for x in
            np.arange(start=lo_f_start, stop=lo_f_end + 0.0001, step=lo_f_step)
        ]

        gen_lo.send(f':OUTP:MOD:STAT OFF')

        src.send(f'APPLY p6v,{src_u}V,{src_i_max}mA')
        src.send('OUTPut ON')

        # gen_lo.send(f':DM:STAT ON')

        gen_lo.send(f'SOUR:POW {lo_pow}dbm')

        sa.send(':CAL:AUTO OFF')
        sa.send(f':SENS:FREQ:SPAN {sa_span}')
        sa.send(f'DISP:WIND:TRAC:Y:RLEV {sa_rlev}')
        sa.send(f'DISP:WIND:TRAC:Y:PDIV {sa_scale_y}')
        sa.send(f'AVER:COUNT {sa_avg_count}')
        sa.send(f'AVER {sa_avg_state}')
        sa.send(':CALC:MARK1:MODE POS')

        gen_lo.send(f'OUTP:STAT ON')

        result = defaultdict(dict)
        for lo_freq in freq_lo_values:

            sa_freq = lo_freq

            if lo_f_is_div2:
                lo_freq *= 2

            for mod_f in mod_f_values:

                if token.cancelled:
                    gen_lo.send(f'OUTP:STAT OFF')

                    time.sleep(0.5)

                    src.send('OUTPut OFF')

                    gen_lo.send(f':DM:IQAD OFF')
                    gen_lo.send(f':DM:STAT OFF')
                    gen_lo.send(f'SOUR:POW {lo_pow}dbm')
                    gen_lo.send(f'SOUR:FREQ {lo_f_start}')

                    sa.send(':CAL:AUTO ON')
                    raise RuntimeError('measurement cancelled')

                if lo_f_is_div2:
                    sa_center_freq = sa_freq + mod_f
                else:
                    sa_center_freq = sa_freq - mod_f

                gen_lo.send(f'SOUR:FREQ {sa_center_freq}')

                if not mock_enabled:
                    time.sleep(0.3)

                sa.send(f':SENSe:FREQuency:CENTer {sa_center_freq}')

                if not mock_enabled:
                    time.sleep(0.3)

                if lo_f_is_div2:
                    f_out = sa_freq + mod_f
                    sa_p_out = set_read_marker(f_out)
                else:
                    f_out = sa_freq - mod_f
                    sa_p_out = set_read_marker(f_out)

                pow_read = sa_p_out
                loss = abs(lo_pow - pow_read)
                if mock_enabled:
                    loss = 10

                print('loss: ', loss)
                result[lo_freq][mod_f] = loss

        gen_lo.send(f'OUTP:STAT OFF')

        time.sleep(0.5)

        src.send('OUTPut OFF')

        gen_lo.send(f'SOUR:POW {lo_pow}dbm')
        gen_lo.send(f'SOUR:FREQ {lo_f_start}')

        sa.send(':CAL:AUTO ON')

        result = {k: v for k, v in result.items()}
        pprint_to_file('cal_rf.ini', result)

        self._calibrated_pows_rf = result
        return True

    def _calibrateMod(self, token, secondary):
        print('calibrate mod gen')

        secondary = self.secondaryParams

        gen_mod = self._instruments['P RF']
        sa = self._instruments['Анализатор']

        mod_f_min = secondary['Fmod_min'] * MEGA
        mod_f_max = secondary['Fmod_max'] * MEGA
        mod_f_delta = secondary['Fmod_delta'] * MEGA
        mod_p = secondary['Pmod']

        sa_rlev = secondary['sa_rlev']
        sa_scale_y = secondary['sa_scale_y']
        sa_span = secondary['sa_span'] * MEGA

        mod_f_values = [
            round(x, 3) for x in
            np.arange(start=mod_f_min, stop=mod_f_max + 0.0002, step=mod_f_delta)
        ]

        gen_mod.send(f'SOUR:POW {mod_p}dbm')

        sa.send(':CAL:AUTO OFF')
        sa.send(f':SENS:FREQ:SPAN {sa_span}')
        sa.send(f'DISP:WIND:TRAC:Y:RLEV {sa_rlev}')
        sa.send(f'DISP:WIND:TRAC:Y:PDIV {sa_scale_y}')
        sa.send(':CALC:MARK1:MODE POS')

        gen_mod.send(f'OUTP:STAT ON')

        result = defaultdict(dict)
        for mod_f in mod_f_values:
            gen_mod.send(f'SOUR:FREQ {mod_f}')

            time.sleep(0.8)

            sa_freq = mod_f
            sa.send(f':SENSe:FREQuency:CENTer {sa_freq}')

            time.sleep(0.2)

            sa_p_out = float(sa.query(':CALCulate:MARKer:Y?'))
            loss = mod_p - sa_p_out

            result[mod_p][mod_f] = loss
            print('loss:', loss)

        gen_mod.send(f'OUTP:STAT OFF')
        gen_mod.send(f'SOUR:FREQ {mod_f_min}')

        sa.send(':CAL:AUTO ON')

        result = {k: v for k, v in result.items()}
        pprint_to_file('cal_mod.ini', result)

        self._calibrated_pows_mod = result

    def measure(self, token, params):
        print(f'call measure with {token} {params}')
        device, _ = params
        try:
            self.result.set_secondary_params(self.secondaryParams)
            self._measure(token, device)
            # self.hasResult = bool(self.result)
            self.hasResult = True  # HACK
        except RuntimeError as ex:
            print('runtime error:', ex)

    def _measure(self, token, device):
        param = self.deviceParams[device]
        secondary = self.secondaryParams.params
        print(f'launch measure with {token} {param} {secondary}')

        self._clear()
        _, i_res = self._measure_s_params(token, param, secondary)
        self.result._raw_current = i_res
        return True

    def _clear(self):
        self.result.clear()

    def _init(self):
        self._instruments['P LO'].send('*RST')
        self._instruments['P RF'].send('*RST')
        self._instruments['Источник'].send('*RST')
        self._instruments['Мультиметр'].send('*RST')
        self._instruments['Анализатор'].send('*RST')

    def _measure_s_params(self, token, param, secondary):

        def set_read_marker(freq):
            sa.send(f':CALCulate:MARKer1:X {freq}Hz')
            if not mock_enabled:
                time.sleep(0.01)
            return float(sa.query(':CALCulate:MARKer:Y?'))

        gen_lo = self._instruments['P LO']
        gen_mod = self._instruments['P RF']
        src = self._instruments['Источник']
        mult = self._instruments['Мультиметр']
        sa = self._instruments['Анализатор']

        lo_pow = secondary['Plo']
        lo_f_start = secondary['Flo_min'] * GIGA
        lo_f_end = secondary['Flo_max'] * GIGA
        lo_f_step = secondary['Flo_delta'] * GIGA

        lo_f_is_div2 = secondary['is_Flo_div2']

        mod_f_min = secondary['Fmod_min'] * MEGA
        mod_f_max = secondary['Fmod_max'] * MEGA
        mod_f_delta = secondary['Fmod_delta'] * MEGA
        mod_u_offs = secondary['Uoffs'] * MILLI
        mod_pow = secondary['Pmod']

        src_u = secondary['Usrc']
        src_i_max = 200  # mA

        sa_rlev = secondary['sa_rlev']
        sa_scale_y = secondary['sa_scale_y']
        sa_span = secondary['sa_span'] * MEGA
        sa_avg_state = 'ON' if secondary['sa_avg_state'] else 'OFF'
        sa_avg_count = secondary['sa_avg_count']

        u_start = secondary['u_min']
        u_end = secondary['u_max']
        u_step = secondary['u_delta']

        mod_f_values = [
            round(x, 3) for x in
            np.arange(start=mod_f_min, stop=mod_f_max + 0.0002, step=mod_f_delta)
        ]

        freq_lo_values = [
            round(x, 3) for x in
            np.arange(start=lo_f_start, stop=lo_f_end + 0.0001, step=lo_f_step)
        ]

        u_values = [round(x, 3) for x in np.arange(start=u_start, stop=u_end + 0.002, step=u_step)]

        # region main measure
        gen_lo.send(f':OUTP:MOD:STAT OFF')
        # gen_lo.send(f':RAD:ARB OFF')
        # gen_lo.send(f':DM:IQAD:EXT:COFF {mod_u_offs}')

        src.send(f'APPLY p25v,{0.5}V,{50}mA')
        src.send(f'APPLY p6v,{src_u}V,{src_i_max}mA')
        src.send('OUTPut ON')

        # gen_lo.send(f':DM:IQAD ON')
        # gen_lo.send(f':DM:STAT ON')

        sa.send(':CAL:AUTO OFF')
        sa.send(f':SENS:FREQ:SPAN {sa_span}')
        sa.send(f'DISP:WIND:TRAC:Y:RLEV {sa_rlev}')
        sa.send(f'DISP:WIND:TRAC:Y:PDIV {sa_scale_y}')
        sa.send(f'AVER:COUNT {sa_avg_count}')
        sa.send(f'AVER {sa_avg_state}')
        sa.send(':CALC:MARK1:MODE POS')

        gen_lo.send(f'OUTP:STAT ON')
        gen_mod.send(f'OUTP:STAT ON')

        if mock_enabled:
            with open('./mock_data/-5_1mhz.txt', mode='rt', encoding='utf-8') as f:
                index = 0
                mocked_raw_data = ast.literal_eval(''.join(f.readlines()))

        res = []
        for lo_freq in freq_lo_values:

            sa_freq = lo_freq

            if lo_f_is_div2:
                lo_freq *= 2

            gen_lo.send(f'SOUR:FREQ {lo_freq}')
            # gen_lo.send(f':DM:IQAD OFF')
            # gen_lo.send(f':DM:IQAD ON')

            for mod_f in mod_f_values:

                if token.cancelled:
                    gen_mod.send(f'OUTP:STAT OFF')
                    gen_lo.send(f'OUTP:STAT OFF')

                    time.sleep(0.5)

                    src.send('OUTPut OFF')

                    gen_lo.send(f':DM:IQAD OFF')
                    gen_lo.send(f':DM:STAT OFF')
                    gen_lo.send(f'SOUR:POW {lo_pow}dbm')
                    gen_lo.send(f'SOUR:FREQ {lo_f_start}')

                    gen_mod.send(f'SOUR:FREQ {mod_f_min}')

                    sa.send(':CAL:AUTO ON')
                    raise RuntimeError('measurement cancelled')

                lo_loss = self._calibrated_pows_lo.get(lo_pow, dict()).get(lo_freq, 0) / 2
                mod_loss = self._calibrated_pows_mod.get(mod_pow, dict()).get(mod_f, 0)
                out_loss = self._calibrated_pows_rf.get(lo_freq, dict()).get(mod_f, 0) / 2

                gen_mod.send(f'SOUR:POW {mod_pow + mod_loss}dbm')
                gen_lo.send(f'SOUR:POW {lo_pow + lo_loss}dbm')

                gen_mod.send(f'SOUR:FREQ {mod_f}')

                if not mock_enabled:
                    time.sleep(0.3)

                if lo_f_is_div2:
                    sa_center_freq = sa_freq + mod_f
                else:
                    sa_center_freq = sa_freq - mod_f

                sa.send(f':SENSe:FREQuency:CENTer {sa_center_freq}')

                if not mock_enabled:
                    time.sleep(0.3)

                if lo_f_is_div2:
                    f_out = sa_freq + mod_f
                    sa_p_out = set_read_marker(f_out)
                else:
                    f_out = sa_freq - mod_f
                    sa_p_out = set_read_marker(f_out)

                src_u_read = src_u
                src_i_read = float(mult.query('MEAS:CURR:DC? 1A,DEF'))

                raw_point = {
                    'lo_p': lo_pow,
                    'lo_f': lo_freq,
                    'mod_f': mod_f,
                    'src_u': src_u_read,  # power source voltage as set in GUI
                    'src_i': src_i_read,
                    'sa_p_out': sa_p_out,
                    'out_loss': out_loss,
                }

                if mock_enabled:
                    # TODO record new test data
                    raw_point = mocked_raw_data[index]
                    raw_point['out_loss'] = out_loss
                    index += 1

                print(raw_point)
                res.append(raw_point)
                self._add_measure_point(raw_point)

        gen_mod.send(f'OUTP:STAT OFF')
        gen_lo.send(f'OUTP:STAT OFF')

        time.sleep(0.5)

        src.send('OUTPut OFF')

        gen_lo.send(f':DM:STAT OFF')
        gen_lo.send(f'SOUR:POW {lo_pow}dbm')
        gen_lo.send(f'SOUR:FREQ {lo_f_start}')
        gen_mod.send(f'SOUR:FREQ {mod_f_min}')

        sa.send(':CAL:AUTO ON')

        if not mock_enabled:
            with open('out.txt', mode='wt', encoding='utf-8') as f:
                f.write(str(res))
        # endregion

        # region measure current
        if mock_enabled:
            with open('./mock_data/current.txt', mode='rt', encoding='utf-8') as f:
                index = 0
                mocked_raw_data = ast.literal_eval(''.join(f.readlines()))

        # gen_lo.send(f':DM:IQAD OFF')
        # gen_lo.send(f':DM:IQAD ON')

        i_res = []
        for u in u_values:
            if token.cancelled:
                src.send('OUTPut OFF')
                raise RuntimeError('measurement cancelled')

            src.send(f'APPLY p6v,{u}V,{src_i_max}mA')
            src.send('OUTPut ON')

            time.sleep(0.1)
            if not mock_enabled:
                time.sleep(0.5)

            i_mul_read = float(mult.query('MEAS:CURR:DC? 1A,DEF'))

            raw_point = {
                'u_mul': u,
                'i_mul': i_mul_read * 1_000,
            }

            if mock_enabled:
                raw_point = mocked_raw_data[index]
                raw_point['i_mul'] *= 1_000
                index += 1

            print(raw_point)
            i_res.append(raw_point)

        if not mock_enabled:
            time.sleep(0.5)

        gen_lo.send(f':DM:IQAD OFF')
        src.send('OUTPut OFF')
        # endregion
        return res, i_res

    def _add_measure_point(self, data):
        print('measured point:', data)
        self.result.add_point(data)
        self.pointReady.emit()

    def saveConfigs(self):
        pprint_to_file('params.ini', self.secondaryParams.params)

    @pyqtSlot(dict)
    def on_secondary_changed(self, params):
        self.secondaryParams.params = params

    @property
    def status(self):
        return [i.status for i in self._instruments.values()]
