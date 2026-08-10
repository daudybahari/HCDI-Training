# -*- coding: utf-8 -*-

import base64
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class HcdiTrainingHistory(models.Model):
    _name = 'hcdi.training.history'
    _description = 'Riwayat Training & Penilaian Karyawan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'completion_date desc, id desc'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Karyawan',
        required=True,
        ondelete='cascade',
        index=True,
        tracking=True
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Divisi / Departemen',
        related='employee_id.department_id',
        store=True,
        readonly=True
    )
    job_id = fields.Many2one(
        'hr.job',
        string='Jabatan',
        related='employee_id.job_id',
        store=True,
        readonly=True
    )
    channel_id = fields.Many2one(
        'slide.channel',
        string='Course / Training',
        required=True,
        ondelete='restrict',
        tracking=True
    )
    trainer_id = fields.Many2one(
        'res.users',
        string='Trainer',
        related='channel_id.user_id',
        readonly=True
    )
    start_date = fields.Date(
        string='Tanggal Mulai',
        default=fields.Date.context_today
    )
    completion_date = fields.Date(
        string='Tanggal Selesai',
        tracking=True
    )
    score_pretest = fields.Float(
        string='Pre-test',
        default=0.0,
        readonly=True,
        tracking=True,
        help='Nilai otomatis ditarik dari hasil Ujian Pre-test di modul Survey Odoo'
    )
    score_quiz = fields.Float(
        string='Quiz',
        default=0.0,
        readonly=True,
        tracking=True,
        help='Nilai rata-rata otomatis ditarik dari pengerjaan Kuis di modul Survey Odoo'
    )
    score_posttest = fields.Float(
        string='Post-test',
        default=0.0,
        readonly=True,
        tracking=True,
        help='Nilai otomatis ditarik dari Ujian Akhir (Post-test) di modul Survey Odoo'
    )
    final_score = fields.Float(
        string='Nilai Akhir Berbobot',
        compute='_compute_final_score',
        store=True,
        tracking=True
    )
    passing_grade = fields.Float(
        string='Passing Grade',
        related='channel_id.passing_grade',
        readonly=True
    )
    execution_state = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('done', 'Selesai Pelaksanaan')
    ], string='Status Pelaksanaan', default='draft', required=True, tracking=True)

    state = fields.Selection([
        ('draft', 'Mengikuti'),
        ('passed', 'Lulus'),
        ('failed', 'Tidak Lulus')
    ], string='Status Kelulusan', compute='_compute_state', store=True, default='draft', tracking=True)

    certificate_number = fields.Char(
        string='Nomor Sertifikat',
        readonly=True,
        copy=False,
        tracking=True
    )
    certificate_file = fields.Binary(
        string='File Sertifikat (PDF)',
        attachment=True,
        readonly=True
    )
    certificate_filename = fields.Char(
        string='Nama File Sertifikat'
    )

    # 1: PERHITUNGAN NILAI AKHIR BERBOBOT
    @api.depends('score_pretest', 'score_quiz', 'score_posttest', 'channel_id.weight_pretest', 'channel_id.weight_quiz', 'channel_id.weight_posttest')
    def _compute_final_score(self):
        """Menghitung otomatis Nilai Akhir Berbobot berdasarkan persentase bobot pada Course."""
        for rec in self:
            if rec.channel_id:
                w_pre = rec.channel_id.weight_pretest or 0.0
                w_quiz = rec.channel_id.weight_quiz or 0.0
                w_post = rec.channel_id.weight_posttest or 0.0
                
                # Formula: (Pre * %Pre + Quiz * %Quiz + Post * %Post) / 100
                weighted_val = (
                    (rec.score_pretest * w_pre) +
                    (rec.score_quiz * w_quiz) +
                    (rec.score_posttest * w_post)
                ) / 100.0
                rec.final_score = round(weighted_val, 2)
            else:
                rec.final_score = 0.0

    #  2: PENENTUAN STATUS KELULUSAN
    @api.depends('final_score', 'passing_grade', 'completion_date', 'execution_state')
    def _compute_state(self):
        """Menentukan status Lulus atau Tidak Lulus secara otomatis jika pelaksanaan sudah Done."""
        for rec in self:
            if rec.execution_state != 'done':
                rec.state = 'draft'
            elif rec.final_score >= rec.passing_grade:
                rec.state = 'passed'
            else:
                rec.state = 'failed'

    #  WORKFLOW: MULAI & SELESAIKAN TRAINING
    def action_start_training(self):
        """Mengubah status pelaksanaan dari Draft menjadi In Progress."""
        for rec in self:
            if rec.execution_state != 'draft':
                raise UserError(_("Pelatihan hanya dapat dimulai dari status Draft!"))
            rec.execution_state = 'in_progress'
            rec.message_post(body=_("Pelatihan dimulai (In Progress)."))

    def action_complete_training(self):
        """Mengubah status pelaksanaan dari In Progress menjadi Done.
        Dilarang langsung dari Draft ke Done.
        Saat Done, sistem otomatis menarik nilai survey, mengevaluasi kelulusan, & menerbitkan sertifikat jika Lulus.
        """
        for rec in self:
            if rec.execution_state == 'draft':
                raise UserError(_("TIDAK BISA LANGSUNG KE DONE!\nBerdasarkan aturan fungsional, status harus diubah menjadi 'In Progress' terlebih dahulu sebelum diselesaikan ('Done')."))
            elif rec.execution_state != 'in_progress':
                raise UserError(_("Pelatihan hanya dapat diselesaikan dari status 'In Progress'!"))
            
            rec.execution_state = 'done'
            rec.action_sync_survey_scores()
            rec.message_post(body=_("Pelatihan diselesaikan (Done). Data otomatis masuk ke Riwayat Training."))

    # 3: OTOMATISASI PENARIKAN NILAI DARI SURVEY ODOO
    def _get_survey_scores(self):
        """Helper method untuk menghitung skor Pre-test, Quiz, dan Post-test dari survey Odoo."""
        self.ensure_one()
        if not self.employee_id or not self.channel_id:
            return 0.0, 0.0, 0.0, False

        partner = self.employee_id.work_contact_id or self.employee_id.user_id.partner_id
        employee_email = self.employee_id.work_email or (partner and partner.email) or False

        slides = self.env['slide.slide'].search([
            ('channel_id', '=', self.channel_id.id),
            ('survey_id', '!=', False)
        ])

        score_pre = 0.0
        quiz_scores = []
        score_post = 0.0
        latest_date = False

        for slide in slides:
            survey = slide.survey_id
            
            domain = [
                ('survey_id', '=', survey.id),
                ('state', '=', 'done')
            ]
            if partner and employee_email:
                domain.extend(['|', ('partner_id', '=', partner.id), ('email', '=', employee_email)])
            elif partner:
                domain.append(('partner_id', '=', partner.id))
            elif employee_email:
                domain.append(('email', '=', employee_email))

            user_inputs = self.env['survey.user_input'].search(domain, order='create_date desc', limit=1)

            if user_inputs:
                score = user_inputs.scoring_percentage or 0.0
                
                if user_inputs.create_date:
                    date_val = user_inputs.create_date.date()
                    if not latest_date or date_val > latest_date:
                        latest_date = date_val

                survey_name = (survey.title or slide.name or '').lower()

                if 'pre' in survey_name:
                    score_pre = score
                elif 'post' in survey_name:
                    score_post = score
                else:
                    quiz_scores.append(score)

        avg_quiz = round(sum(quiz_scores) / len(quiz_scores), 2) if quiz_scores else 0.0
        return score_pre, avg_quiz, score_post, latest_date

    @api.onchange('employee_id', 'channel_id')
    def _onchange_sync_survey_scores(self):
        """Otomatis menarik dan mengisi nilai survey saat Karyawan atau Course dipilih di form."""
        if self.employee_id and self.channel_id:
            score_pre, avg_quiz, score_post, latest_date = self._get_survey_scores()
            self.score_pretest = score_pre
            self.score_quiz = avg_quiz
            self.score_posttest = score_post
            if latest_date:
                self.completion_date = latest_date

    def action_sync_survey_scores(self):
        """Fungsi utama untuk menarik skor pengerjaan Pre-test, Quiz, dan Post-test 
        peserta langsung dari tabel hasil Ujian Odoo Survey (survey.user_input).
        """
        for rec in self:
            if not rec.employee_id or not rec.channel_id:
                continue

            score_pre, avg_quiz, score_post, latest_date = rec._get_survey_scores()
            update_vals = {}
            if score_pre > 0.0:
                update_vals['score_pretest'] = score_pre
            if avg_quiz > 0.0:
                update_vals['score_quiz'] = avg_quiz
            if score_post > 0.0:
                update_vals['score_posttest'] = score_post
            if latest_date and not rec.completion_date:
                update_vals['completion_date'] = latest_date

            if update_vals:
                rec.write(update_vals)

    #  4: PENERBITAN SERTIFIKAT AUTOMATIS PDF & EMAIL
    def action_generate_certificate(self):
        """Method untuk meng-generate nomor sertifikat, PDF, dan mengirim email otomatis."""
        for rec in self:
            if rec.state != 'passed':
                raise UserError(_("Sertifikat hanya dapat diterbitkan untuk peserta dengan status LULUS!"))

            # 1. Generate nomor sertifikat unik jika belum ada
            if not rec.certificate_number:
                rec.certificate_number = self.env['ir.sequence'].next_by_code('hcdi.training.certificate') or _('New')

            # 2. Render QWeb PDF Report (Menggunakan res_type agar tidak menimpa fungsi translation '_')
            report_action = self.env.ref('hcdi_training.action_report_hcdi_certificate')
            pdf_content, res_type = report_action._render_qweb_pdf('hcdi_training.action_report_hcdi_certificate', [rec.id])
            
            filename = f"Sertifikat_{rec.certificate_number.replace('/', '_')}_{rec.employee_id.name}.pdf"
            rec.write({
                'certificate_file': base64.b64encode(pdf_content),
                'certificate_filename': filename,
            })

            # 3. Kirim Email Otomatis dengan Attachment PDF
            template = self.env.ref('hcdi_training.email_template_hcdi_certificate', raise_if_not_found=False)
            if template:
                attachment = self.env['ir.attachment'].create({
                    'name': filename,
                    'type': 'binary',
                    'datas': base64.b64encode(pdf_content),
                    'res_model': 'hcdi.training.history',
                    'res_id': rec.id,
                    'mimetype': 'application/pdf',
                })
                template.send_mail(rec.id, force_send=True, email_values={'attachment_ids': [(6, 0, [attachment.id])]})
                
            rec.message_post(body=_("Sertifikat %s berhasil diterbitkan dan dikirim via email.") % rec.certificate_number)

    @api.model_create_multi
    def create(self, vals_list):
        records = super(HcdiTrainingHistory, self).create(vals_list)
        for rec in records:
            # Otomatis mendaftarkan partner karyawan sebagai anggota resmi Course eLearning agar bisa mengerjakan ujian di portal
            if rec.employee_id and rec.channel_id:
                partner = rec.employee_id.work_contact_id or (rec.employee_id.user_id and rec.employee_id.user_id.partner_id)
                if partner:
                    rec.channel_id._action_add_members(partner)

            # Otomatis sinkronkan nilai saat record dibuat
            rec.action_sync_survey_scores()
            if rec.state == 'passed' and not rec.certificate_number:
                rec.action_generate_certificate()
        return records

    def write(self, vals):
        res = super(HcdiTrainingHistory, self).write(vals)
        for rec in self:
            if rec.state == 'passed' and not rec.certificate_number:
                rec.action_generate_certificate()
        return res


class SurveyUserInput(models.Model):
    _inherit = 'survey.user_input'

    def _mark_done(self):
        """Otomatis meng-update status pelaksanaan dan nilai pada hcdi.training.history saat survey/ujian selesai."""
        res = super(SurveyUserInput, self)._mark_done()
        for user_input in self:
            if user_input.state == 'done' and user_input.survey_id:
                slides = self.env['slide.slide'].search([('survey_id', '=', user_input.survey_id.id)])
                for slide in slides:
                    partner = user_input.partner_id
                    email = user_input.email
                    employee = False
                    if partner:
                        employee = self.env['hr.employee'].search(['|', ('work_contact_id', '=', partner.id), ('user_id.partner_id', '=', partner.id)], limit=1)
                    if not employee and email:
                        employee = self.env['hr.employee'].search([('work_email', '=', email)], limit=1)

                    if employee:
                        history = self.env['hcdi.training.history'].search([
                            ('employee_id', '=', employee.id),
                            ('channel_id', '=', slide.channel_id.id)
                        ], limit=1)
                        if history:
                            if history.execution_state == 'draft':
                                history.execution_state = 'in_progress'
                            history.action_sync_survey_scores()
                            
                            survey_name = (user_input.survey_id.title or slide.name or '').lower()
                            if 'post' in survey_name:
                                history.execution_state = 'done'
                                history.action_sync_survey_scores()
        return res
