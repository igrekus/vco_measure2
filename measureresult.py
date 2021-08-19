import os
import datetime

from collections import defaultdict
from subprocess import Popen
from textwrap import dedent

import pandas as pd

from util.file import load_ast_if_exists, pprint_to_file, make_dirs, open_explorer_at
from util.const import *
from util.string import now_timestamp


class MeasureResult:
    def __init__(self):
        self._secondaryParams = None
        self._raw = list()
        self._raw_x2 = list()
        self._raw_x3 = list()

        self._report = dict()

        self._processed = list()
        self._processed_x2 = list()
        self._processed_x3 = list()

        self.ready = False

        self.data1 = defaultdict(list)
        self.data2 = defaultdict(list)

        self.data3 = dict()
        self.data4 = dict()

        self.adjustment = load_ast_if_exists('adjust.ini', default=None)

    def __bool__(self):
        return self.ready

    def _process(self):
        harm_x2 = [list(d.values()) for d in self._raw_x2]
        self.data3[1] = harm_x2
        self._processed_x2 = harm_x2

        harm_x3 = [list(d.values()) for d in self._raw_x3]
        self.data4[1] = harm_x3
        self._processed_x3 = harm_x3

        self.ready = True

    def _process_point(self, data):

        u_src = data['u_src']
        u_control = data['u_control']

        f_tune = data['read_f']
        p_out = data['read_p']
        i_src = data['read_i']

        if self.adjustment is not None:
            point = self.adjustment[len(self._processed)]
            f_tune += point['f_tune']
            p_out += point['p_out']
            i_src += point['i_src']

        self._report = {
            'u_src': u_src,
            'u_control': u_control,
            'f_tune': f_tune,
            'p_out': p_out,
            'i_src': i_src,
        }

        self.data1[u_src].append([u_control, f_tune])
        self.data2[u_src].append([u_control, p_out])
        self._processed.append({**self._report})

    def clear(self):
        self._secondaryParams.clear()
        self._raw.clear()
        self._raw_x2.clear()
        self._raw_x3.clear()

        self._report.clear()

        self._processed.clear()
        self._processed_x2.clear()
        self._processed_x3.clear()

        self.data1.clear()
        self.data2.clear()
        self.data3.clear()
        self.data4.clear()

        self.ready = False

    def set_secondary_params(self, params):
        self._secondaryParams = dict(**params.params)

    def add_point(self, data):
        self._raw.append(data)
        self._process_point(data)

    def save_adjustment_template(self):
        if self.adjustment is None:
            print('measured, saving template')
            self.adjustment = [{
                'u_src': p['u_src'],
                'u_control': p['u_control'],
                'f_tune': 0,
                'p_out': 0,
                'i_src': 0,

            } for p in self._processed]
            pprint_to_file('adjust.ini', self.adjustment)

    @property
    def report(self):
        return dedent("""        Источник питания:
        Uпит, В={u_src}
        Uупр, В={u_control}
        Iпот, mA={i_src}

        Анализатор:
        Fвых, МГц={f_tune:0.3f}
        Pвых, дБм={p_out:0.3f}
        """.format(**self._report))

    def export_excel(self):
        device = 'mod'
        path = 'xlsx'

        make_dirs(path)

        file_name = f'./{path}/{device}-pout-{now_timestamp()}.xlsx'
        df = pd.DataFrame(self._processed)

        df.columns = [
            'Pгет, дБм', 'Fгет, ГГц', 'Pпот, дБ',
            'Loss rf, дБм',
            'Uпит, В', 'Iпит, мА',
        ]
        df.to_excel(file_name, engine='openpyxl', index=False)

        self._export_current()

        open_explorer_at(os.path.abspath(file_name))

    def _export_current(self):
        device = 'mod'
        path = 'xlsx'

        file_name = f'./{path}/{device}-curr-{now_timestamp()}.xlsx'
        df = pd.DataFrame(self._processed_x2, columns=['Uпит, В', 'Iпот, мА'])

        df.to_excel(file_name, engine='openpyxl', index=False)
