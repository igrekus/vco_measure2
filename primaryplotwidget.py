import pyqtgraph as pg

from PyQt5.QtWidgets import QGridLayout, QWidget, QLabel
from PyQt5.QtCore import Qt


# https://www.learnpyqt.com/tutorials/plotting-pyqtgraph/
# https://pyqtgraph.readthedocs.io/en/latest/introduction.html#what-is-pyqtgraph

colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
          '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',]


class PrimaryPlotWidget(QWidget):
    label_style = {'color': 'k', 'font-size': '15px'}

    def __init__(self, parent=None, controller=None):
        super().__init__(parent)

        self._controller = controller   # TODO decouple from controller, use explicit result passing
        self.only_main_states = False

        self._grid = QGridLayout()

        self._win = pg.GraphicsLayoutWidget(show=True)
        self._win.setBackground('w')

        self._stat_label = QLabel('Mouse:')
        self._stat_label.setAlignment(Qt.AlignRight)

        self._grid.addWidget(self._stat_label, 0, 0)
        self._grid.addWidget(self._win, 1, 0)

        self._plot_00 = self._win.addPlot(row=0, col=0, colspan=1, rowspan=1)

        self._plot_01 = self._win.addPlot(row=0, col=1)

        # self._plot_dummy = self._win.addPlot(row=1, col=2)

        self._curves_00 = dict()
        self._curves_01 = dict()

        self._plot_00.setLabel('left', 'Кп', **self.label_style)
        self._plot_00.setLabel('bottom', 'Fпч, МГц', **self.label_style)
        self._plot_00.enableAutoRange('x')
        self._plot_00.enableAutoRange('y')
        self._plot_00.showGrid(x=True, y=True)
        self._vb_00 = self._plot_00.vb
        rect = self._vb_00.viewRect()
        self._plot_00.addLegend(offset=(rect.x() + 50, rect.y() + rect.height() - 50))
        self._vLine_00 = pg.InfiniteLine(angle=90, movable=False)
        self._hLine_00 = pg.InfiniteLine(angle=0, movable=False)
        self._plot_00.addItem(self._vLine_00, ignoreBounds=True)
        self._plot_00.addItem(self._hLine_00, ignoreBounds=True)
        self._proxy_00 = pg.SignalProxy(self._plot_00.scene().sigMouseMoved, rateLimit=60, slot=self.mouseMoved_00)

        self._plot_01.setLabel('left', 'Iпот, мА', **self.label_style)
        self._plot_01.setLabel('bottom', 'Uпит, В', **self.label_style)
        self._plot_01.enableAutoRange('x')
        self._plot_01.enableAutoRange('y')
        self._plot_01.showGrid(x=True, y=True)
        self._vb_01 = self._plot_01.vb
        rect = self._vb_01.viewRect()
        self._plot_01.addLegend(offset=(rect.x() + 50, rect.y() + 50))
        self._vLine_01 = pg.InfiniteLine(angle=90, movable=False)
        self._hLine_01 = pg.InfiniteLine(angle=0, movable=False)
        self._plot_01.addItem(self._vLine_01, ignoreBounds=True)
        self._plot_01.addItem(self._hLine_01, ignoreBounds=True)
        self._proxy_01 = pg.SignalProxy(self._plot_01.scene().sigMouseMoved, rateLimit=60, slot=self.mouseMoved_01)

        self.setLayout(self._grid)

    def mouseMoved_00(self, event):
        pos = event[0]
        if self._plot_00.sceneBoundingRect().contains(pos):
            mouse_point = self._vb_00.mapSceneToView(pos)
            x = mouse_point.x()
            y = mouse_point.y()
            self._vLine_00.setPos(x)
            self._hLine_00.setPos(y)
            if not self._curves_00:
                return

            self._stat_label.setText(_label_text(x, y, [
                [f, curve.yData[_find_value_index(curve.xData, x)]]
                for f, curve in self._curves_00.items()
            ]))

    def mouseMoved_01(self, event):
        pos = event[0]
        if self._plot_01.sceneBoundingRect().contains(pos):
            mouse_point = self._vb_01.mapSceneToView(pos)
            x = mouse_point.x()
            y = mouse_point.y()
            self._vLine_01.setPos(x)
            self._hLine_01.setPos(y)
            if not self._curves_01:
                return

            self._stat_label.setText(_label_text(x, y, [
                [f, curve.yData[_find_value_index(curve.xData, x)]]
                for f, curve in self._curves_01.items()
            ]))

    def clear(self):
        def _remove_curves(plot, curve_dict):
            for _, curve in curve_dict.items():
                plot.removeItem(curve)

        _remove_curves(self._plot_00, self._curves_00)
        _remove_curves(self._plot_01, self._curves_01)

        self._curves_00.clear()
        self._curves_01.clear()

    def plot(self):
        print('plotting primary stats')
        _plot_curves(self._controller.result.data, self._curves_00, self._plot_00, 'ГГц')
        _plot_curves(self._controller.result.data_i, self._curves_01, self._plot_01, '')


def _plot_curves(datas, curves, plot, unit):
    for f_lo, data in datas.items():
        curve_xs, curve_ys = zip(*data)
        try:
            curves[f_lo].setData(x=curve_xs, y=curve_ys)
        except KeyError:
            try:
                color = colors[len(curves)]
            except IndexError:
                color = colors[len(curves) - len(colors)]
            curves[f_lo] = pg.PlotDataItem(
                curve_xs,
                curve_ys,
                pen=pg.mkPen(
                    color=color,
                    width=2,
                ),
                symbol='o',
                symbolSize=5,
                symbolBrush=color,
                name=f'{f_lo} {unit}'
            )
            plot.addItem(curves[f_lo])


def _label_text(x, y, vals):
    vals_str = ''.join(f'   <span style="color:{colors[i]}">{f:0.1f}={v:0.2f}</span>' for i, (f, v) in enumerate(vals))
    return f"<span style='font-size: 8pt'>x={x:0.2f},   y={y:0.2f}   {vals_str}</span>"


def _find_value_index(freqs: list, freq):
    return min(range(len(freqs)), key=lambda i: abs(freqs[i] - freq))
