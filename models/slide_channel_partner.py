# -*- coding: utf-8 -*-

from odoo import models, fields, api

class SlideChannelPartner(models.Model):
    _inherit = 'slide.channel.partner'

    @api.model_create_multi
    def create(self, vals_list):
        records = super(SlideChannelPartner, self).create(vals_list)
        for record in records:
            if not record.partner_id or not record.channel_id:
                continue
            # Cari employee yang cocok dengan partner_id ini
            employee = self.env['hr.employee'].search([
                '|',
                ('work_contact_id', '=', record.partner_id.id),
                ('user_id.partner_id', '=', record.partner_id.id)
            ], limit=1)
            if employee:
                # Daftarkan ke hcdi.training.history jika belum ada
                history_obj = self.env['hcdi.training.history']
                existing = history_obj.search([
                    ('employee_id', '=', employee.id),
                    ('channel_id', '=', record.channel_id.id)
                ], limit=1)
                if not existing:
                    history_obj.create({
                        'employee_id': employee.id,
                        'channel_id': record.channel_id.id,
                        'execution_state': 'draft',
                    })
        return records
