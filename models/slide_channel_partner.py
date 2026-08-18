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
                # 1. Jangan masukkan Trainer/Responsible course ke dalam progress training
                if employee.user_id and employee.user_id == record.channel_id.user_id:
                    continue
                
                # 2. Jika course dibuat dari TNA Request, hanya masukkan yang memang terdaftar sebagai peserta
                tna_request_id = self.env.context.get('from_tna_request_id')
                if tna_request_id:
                    tna_request = self.env['hcdi.training.request'].sudo().browse(tna_request_id)
                else:
                    tna_request = self.env['hcdi.training.request'].sudo().search([
                        ('course_id', '=', record.channel_id.id)
                    ], limit=1)
                if tna_request and employee.id not in tna_request.target_participant_ids.ids:
                    continue

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
