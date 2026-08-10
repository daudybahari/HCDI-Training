# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError

class SlideChannel(models.Model):
    _inherit = 'slide.channel'

    weight_pretest = fields.Float(
        string='Bobot Pre-test (%)',
        default=10.0,
        help='Persentase bobot nilai Pre-test terhadap Nilai Akhir (0 - 100%)'
    )
    weight_quiz = fields.Float(
        string='Bobot Quiz (%)',
        default=30.0,
        help='Persentase bobot rata-rata Quiz terhadap Nilai Akhir (0 - 100%)'
    )
    weight_posttest = fields.Float(
        string='Bobot Post-test (%)',
        default=60.0,
        help='Persentase bobot Ujian Akhir (Post-test) terhadap Nilai Akhir (0 - 100%)'
    )
    passing_grade = fields.Float(
        string='Passing Grade (Nilai Kelulusan Minimal)',
        default=70.0,
        help='Nilai minimal untuk dinyatakan Lulus training (default: 70)'
    )

    @api.constrains('weight_pretest', 'weight_quiz', 'weight_posttest')
    def _check_weights_total(self):
        for record in self:
            total_weight = record.weight_pretest + record.weight_quiz + record.weight_posttest
            if round(total_weight, 2) != 100.0:
                raise ValidationError(
                    f"Total bobot penilaian harus sama dengan 100%!\n"
                    f"Saat ini: Pre-test ({record.weight_pretest}%) + Quiz ({record.weight_quiz}%) + Post-test ({record.weight_posttest}%) = {total_weight}%"
                )
