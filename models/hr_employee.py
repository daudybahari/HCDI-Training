# -*- coding: utf-8 -*-

from odoo import models, fields, api

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    training_history_ids = fields.One2many(
        'hcdi.training.history',
        'employee_id',
        string='Riwayat Training & Sertifikasi'
    )
    training_count = fields.Integer(
        string='Jumlah Training',
        compute='_compute_training_stats'
    )
    passed_training_count = fields.Integer(
        string='Training Lulus',
        compute='_compute_training_stats'
    )

    @api.depends('training_history_ids', 'training_history_ids.state')
    def _compute_training_stats(self):
        for employee in self:
            employee.training_count = len(employee.training_history_ids)
            employee.passed_training_count = len(employee.training_history_ids.filtered(lambda t: t.state == 'passed'))

    def action_view_training_history(self):
        self.ensure_one()
        return {
            'name': f'Riwayat Training - {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'hcdi.training.history',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
        }
