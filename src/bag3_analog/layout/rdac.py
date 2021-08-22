"""This module combines res_ladder and rdac_decoder."""

from typing import Mapping, Any, Optional, Type

from bag.util.immutable import Param
from bag.design.module import Module
from bag.layout.template import TemplateDB, TemplateBase
from bag.layout.routing.base import TrackID, TrackManager, WDictType, SpDictType

from pybag.core import Transform, BBox
from pybag.enum import MinLenMode, RoundMode, Direction, Orientation, PinMode

from xbase.layout.mos.top import GenericWrapper
from xbase.layout.array.top import ArrayBaseWrapper

from .res.ladder import ResLadder
from .rdac_decoder import RDACDecoder
from ..schematic.rdac import bag3_analog__rdac


class RDAC(TemplateBase):
    def __init__(self, temp_db: TemplateDB, params: Param, **kwargs: Any) -> None:
        TemplateBase.__init__(self, temp_db, params, **kwargs)
        tr_widths: WDictType = self.params['tr_widths']
        tr_spaces: SpDictType = self.params['tr_spaces']
        self._tr_manager = TrackManager(self.grid, tr_widths, tr_spaces)

    @classmethod
    def get_schematic_class(cls) -> Optional[Type[Module]]:
        return bag3_analog__rdac

    @classmethod
    def get_params_info(cls) -> Mapping[str, str]:
        return dict(
            tr_widths='Track widths specifications for track manager',
            tr_spaces='Track spaces specifications for track manager',
            res_params='Parameters for res_ladder',
            dec_params='Parameters for rdac_decoder',
            num_dec='Number of decoders for one res_ladder',
        )

    @classmethod
    def get_default_param_values(cls) -> Mapping[str, Any]:
        return dict(num_dec=1)

    def draw_layout(self) -> None:
        # make master
        res_params: Mapping[str, Any] = self.params['res_params']
        res_master = self.new_template(ArrayBaseWrapper, params=dict(cls_name=ResLadder.get_qualified_name(),
                                                                     params=res_params))
        res_core: ResLadder = res_master.core

        num_dec: int = self.params['num_dec']
        dec_params: Mapping[str, Any] = self.params['dec_params']
        dec_master = self.new_template(GenericWrapper, params=dict(cls_name=RDACDecoder.get_qualified_name(),
                                                                   params=dec_params))
        dec_core: RDACDecoder = dec_master.core
        num_sel_row: int = dec_params['num_sel_row']
        num_sel_col: int = dec_params['num_sel_col']
        num_sel = num_sel_col + num_sel_row
        num_in = 1 << num_sel

        xxm_layer = dec_core.top_layer
        yym_layer = xxm_layer + 1
        ym_layer = xxm_layer - 1
        xm_layer = ym_layer - 1
        vm_layer = xm_layer - 1
        vm_lp = self.grid.tech_info.get_lay_purp_list(vm_layer)[0]

        # --- Placement --- #
        res_w, res_h = res_master.bound_box.w, res_master.bound_box.h
        res_coord0 = res_core.core_coord0
        dec_w, dec_h = dec_master.bound_box.w, dec_master.bound_box.h
        dec_coord0 = dec_core.pg_coord0
        w_pitch, h_pitch = self.grid.get_size_pitch(xxm_layer)
        tot_w = res_w + num_dec * dec_w
        assert res_coord0 < dec_coord0, 'These generator assumes RDACDecoder passgates start higher than ' \
                                        'ResLadder core.'

        if num_dec == 2:
            dec1_inst = self.add_instance(dec_master, xform=Transform(dx=dec_w, mode=Orientation.MY))
            start_x = dec_w
            dec_list = [dec1_inst]
        elif num_dec == 1:
            dec1_inst = None
            start_x = 0
            dec_list = []
        else:
            raise ValueError(f'num_dec={num_dec} is not supported yet. Use 1 or 2.')

        dec0_inst = self.add_instance(dec_master, xform=Transform(dx=start_x + res_w))
        dec_list.append(dec0_inst)
        off_y = dec_coord0 - res_coord0 - h_pitch  # TODO: hack to make resistor array align with passgate array
        res_inst = self.add_instance(res_master, xform=Transform(dx=start_x, dy=off_y))
        tot_h = max(dec_h, res_h + off_y)

        self.set_size_from_bound_box(yym_layer, BBox(0, 0, tot_w, tot_h), round_up=True)

        # --- Routing --- #
        # export select signals as WireArrays
        _sel: BBox = dec0_inst.get_pin('sel<0>')
        w_sel_vm = self.find_track_width(vm_layer, _sel.w)
        for idx in range(num_sel):
            _sel0: BBox = dec0_inst.get_pin(f'sel<{idx}>')
            _vm_tidx0 = self.grid.coord_to_track(vm_layer, _sel0.xm)
            _sel0_warr = self.add_wires(vm_layer, _vm_tidx0, lower=0, upper=_sel0.yh, width=w_sel_vm)
            if num_dec == 2:
                self.add_pin(f'sel0<{idx}>', _sel0_warr, mode=PinMode.LOWER)

                _sel1: BBox = dec1_inst.get_pin(f'sel<{idx}>')
                _vm_tidx1 = self.grid.coord_to_track(vm_layer, _sel1.xm)
                _sel1_warr = self.add_wires(vm_layer, _vm_tidx1, lower=0, upper=_sel1.yh, width=w_sel_vm)
                self.add_pin(f'sel1<{idx}>', _sel1_warr, mode=PinMode.LOWER)
            else:  # num_dec == 1
                self.add_pin(f'sel<{idx}>', _sel0_warr, mode=PinMode.LOWER)

        # export output as WireArray
        _out0: BBox = dec0_inst.get_pin('out')
        w_out_ym = self.find_track_width(ym_layer, _out0.w)
        _ym_tidx0 = self.grid.coord_to_track(ym_layer, _out0.xm)
        _out0_warr = self.add_wires(ym_layer, _ym_tidx0, lower=_out0.yl, upper=self.bound_box.yh, width=w_out_ym)
        if num_dec == 2:
            self.add_pin('out0', _out0_warr, mode=PinMode.UPPER)

            _out1: BBox = dec1_inst.get_pin('out')
            _ym_tidx1 = self.grid.coord_to_track(ym_layer, _out1.xm)
            _out1_warr = self.add_wires(ym_layer, _ym_tidx1, lower=_out1.yl, upper=self.bound_box.yh, width=w_out_ym)
            self.add_pin('out1', _out1_warr, mode=PinMode.UPPER)
        else:  # num_dec == 1:
            self.add_pin('out', _out0_warr, mode=PinMode.UPPER)

        # res_ladder output to rdac_decoder input
        for idx in range(num_in):
            self.connect_bbox_to_track_wires(Direction.LOWER, vm_lp, dec0_inst.get_pin(f'in<{idx}>'),
                                             res_inst.get_pin(f'out<{idx}>'))
            if num_dec == 2:
                self.connect_bbox_to_track_wires(Direction.LOWER, vm_lp, dec1_inst.get_pin(f'in<{idx}>'),
                                                 res_inst.get_pin(f'out<{idx}>'))

        # --- Supplies
        # get res supplies on xxm_layer
        res_vss_xm = res_inst.get_all_port_pins('VSS')
        res_vdd_xm = res_inst.get_all_port_pins('VDD')
        vdd_ym_lidx = self.grid.coord_to_track(ym_layer, res_vdd_xm[0].lower, RoundMode.GREATER_EQ)
        vss_ym_lidx = self._tr_manager.get_next_track(ym_layer, vdd_ym_lidx, 'sup', 'sup', up=1)
        vdd_ym_ridx = self.grid.coord_to_track(ym_layer, res_vdd_xm[0].upper, RoundMode.LESS_EQ)
        vss_ym_ridx = self._tr_manager.get_next_track(ym_layer, vdd_ym_ridx, 'sup', 'sup', up=-1)
        w_sup_ym = self._tr_manager.get_width(ym_layer, 'sup')
        w_sup_xxm = self._tr_manager.get_width(xxm_layer, 'sup')
        vdd_ym_tid = TrackID(ym_layer, vdd_ym_lidx, w_sup_ym, 2, vdd_ym_ridx - vdd_ym_lidx)
        vss_ym_tid = TrackID(ym_layer, vss_ym_lidx, w_sup_ym, 2, vss_ym_ridx - vss_ym_lidx)
        res_vss_xxm, res_vdd_xxm = [], []
        for sup_xm, sup_xxm, tid in [(res_vss_xm, res_vss_xxm, vss_ym_tid), (res_vdd_xm, res_vdd_xxm, vdd_ym_tid)]:
            for warr in sup_xm:
                for warr_single in warr.warr_iter():
                    _ym = self.connect_to_tracks(warr_single, tid, min_len_mode=MinLenMode.MIDDLE)
                    _xxm_tidx = self.grid.coord_to_track(xxm_layer, _ym.middle, RoundMode.NEAREST)
                    sup_xxm.append(self.connect_to_tracks(_ym, TrackID(xxm_layer, _xxm_tidx, w_sup_xxm)))
        # get res supplies on yym_layer
        vdd_yym_lidx = self.grid.coord_to_track(yym_layer, res_vdd_xxm[0].lower, RoundMode.GREATER)
        vdd_yym_ridx = self.grid.coord_to_track(yym_layer, res_vdd_xxm[0].upper, RoundMode.LESS)
        yym_locs1 = self._tr_manager.spread_wires(yym_layer, ['sup', 'sup', 'sup'], vdd_yym_lidx, vdd_yym_ridx,
                                                  ('sup', 'sup'))
        w_sup_yym = self._tr_manager.get_width(yym_layer, 'sup')
        yh = self.bound_box.yh
        vdd_yym = [self.connect_to_tracks(res_vdd_xxm, TrackID(yym_layer, vdd_yym_lidx, w_sup_yym, 2,
                                                               vdd_yym_ridx - vdd_yym_lidx),
                                          track_lower=0, track_upper=yh)]
        vss_yym = [self.connect_to_tracks(res_vss_xxm, TrackID(yym_layer, yym_locs1[1], w_sup_yym), track_lower=0,
                                          track_upper=yh)]
        avail_lidx = self._tr_manager.get_next_track(yym_layer, vdd_yym_lidx, 'sup', 'sup', -1)
        avail_ridx = self._tr_manager.get_next_track(yym_layer, vdd_yym_ridx, 'sup', 'sup', 1)

        # get decoder supplies on yym_layer
        for inst in dec_list:
            if inst.bound_box.xm > res_inst.bound_box.xm:
                yym_ridx = self.grid.coord_to_track(yym_layer, inst.bound_box.xh, RoundMode.LESS)
                yym_locs = self._tr_manager.spread_wires(yym_layer, ['sup', 'sup', 'sup', 'sup'], avail_ridx, yym_ridx,
                                                         ('sup', 'sup'))
                vss_tidx, vdd_tidx = yym_locs[0], yym_locs[1]
            else:
                yym_lidx = self.grid.coord_to_track(yym_layer, inst.bound_box.xl, RoundMode.GREATER)
                yym_locs = self._tr_manager.spread_wires(yym_layer, ['sup', 'sup', 'sup', 'sup'], yym_lidx, avail_lidx,
                                                         ('sup', 'sup'))
                vdd_tidx, vss_tidx = yym_locs[0], yym_locs[1]
            vdd_yym.append(self.connect_to_tracks(inst.get_pin('VDD', layer=xxm_layer),
                                                  TrackID(yym_layer, vdd_tidx, w_sup_yym, 2, yym_locs[2] - yym_locs[0]),
                                                  track_lower=0, track_upper=yh))
            vss_yym.append(self.connect_to_tracks(inst.get_pin('VSS', layer=xxm_layer),
                                                  TrackID(yym_layer, vss_tidx, w_sup_yym, 2, yym_locs[2] - yym_locs[0]),
                                                  track_lower=0, track_upper=yh))

        self.add_pin('VDD', vdd_yym, connect=True)
        self.add_pin('VSS', vss_yym, connect=True)

        # set schematic parameters
        self.sch_params = dict(
            res_params=res_master.sch_params,
            dec_params=dec_master.sch_params,
            num_dec=num_dec,
        )
