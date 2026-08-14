# -*- coding: utf-8 -*-

import base64
import datetime
from io import BytesIO
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class HcdiTrainingHistory(models.Model):
    _name = 'hcdi.training.history'
    _description = 'Riwayat Training & Penilaian Karyawan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'completion_date desc, id desc'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        ondelete='cascade',
        index=True,
        tracking=True
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        related='employee_id.department_id',
        store=True,
        readonly=True
    )
    job_id = fields.Many2one(
        'hr.job',
        string='Job Position',
        related='employee_id.job_id',
        store=True,
        readonly=True
    )
    channel_id = fields.Many2one(
        'slide.channel',
        string='Course',
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
        string='Start Date',
        default=fields.Date.context_today
    )
    completion_date = fields.Date(
        string='End Date',
        tracking=True
    )
    score_pretest = fields.Float(
        string='Pre-test',
        default=0.0,
        readonly=True,
        tracking=True,
        help='Score automatically pulled from Pre-test Survey'
    )
    score_quiz = fields.Float(
        string='Quiz',
        default=0.0,
        readonly=True,
        tracking=True,
        help='Average score automatically pulled from Quizzes'
    )
    score_posttest = fields.Float(
        string='Post-test',
        default=0.0,
        readonly=True,
        tracking=True,
        help='Score automatically pulled from Post-test Survey'
    )
    final_score = fields.Float(
        string='Weighted Final Score',
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
        ('draft', 'Not Started'),
        ('in_progress', 'In Progress'),
        ('done', 'Done')
    ], string='Status', default='draft', required=True, tracking=True)

    state = fields.Selection([
        ('draft', 'Enrolled'),
        ('passed', 'Passed'),
        ('failed', 'Failed')
    ], string='Training Result', compute='_compute_state', store=True, default='draft', tracking=True)

    certificate_number = fields.Char(
        string='Certificate Number',
        readonly=True,
        copy=False,
        tracking=True
    )
    certificate_file = fields.Binary(
        string='Certificate File (PDF)',
        attachment=True,
        readonly=True
    )
    certificate_filename = fields.Char(
        string='Certificate Filename'
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

    def _generate_reportlab_certificate_pdf(self):
        """Meng-generate PDF Sertifikat A4 Landscape secara 100% presisi dengan ReportLab Python."""
        self.ensure_one()
        buffer = BytesIO()
        width, height = landscape(A4)
        c = canvas.Canvas(buffer, pagesize=landscape(A4))
        
        # 1. Background Fill (#FAF9F6)
        c.setFillColor(colors.HexColor('#FAF9F6'))
        c.rect(0, 0, width, height, stroke=0, fill=1)
        
        # 2. Bingkai Luar Navy Blue (#0F2C59) - Margin 6mm
        m_outer = 6 * mm
        c.setStrokeColor(colors.HexColor('#0F2C59'))
        c.setLineWidth(5)
        c.rect(m_outer, m_outer, width - 2 * m_outer, height - 2 * m_outer, stroke=1, fill=0)
        
        # 3. Bingkai Dalam Gold (#C5A059) - Margin 10mm
        m_inner = 10 * mm
        c.setStrokeColor(colors.HexColor('#C5A059'))
        c.setLineWidth(2)
        c.rect(m_inner, m_inner, width - 2 * m_inner, height - 2 * m_inner, stroke=1, fill=0)
        
        center_x = width / 2.0
        
        # --- Header: Nama Perusahaan ---
        c.setFillColor(colors.HexColor('#0F2C59'))
        c.setFont("Helvetica-Bold", 16)
        c.drawCentredString(center_x, height - 28 * mm, "PT HUMAN CAPITAL DEVELOPMENT INDONESIA")
        
        # Garis emas di bawah nama perusahaan
        c.setStrokeColor(colors.HexColor('#C5A059'))
        c.setLineWidth(1.5)
        c.line(center_x - 30 * mm, height - 32 * mm, center_x + 30 * mm, height - 32 * mm)
        
        # --- Judul: SERTIFIKAT KELULUSAN ---
        c.setFillColor(colors.HexColor('#0F2C59'))
        c.setFont("Times-Bold", 34)
        c.drawCentredString(center_x, height - 50 * mm, "SERTIFIKAT KELULUSAN")
        
        # --- Nomor Sertifikat ---
        cert_num = self.certificate_number or ''
        c.setFillColor(colors.HexColor('#555555'))
        c.setFont("Helvetica", 11)
        c.drawCentredString(center_x, height - 59 * mm, f"Nomor Sertifikat: {cert_num}")
        
        # --- Subtitle ---
        c.setFillColor(colors.HexColor('#444444'))
        c.setFont("Times-Italic", 14)
        c.drawCentredString(center_x, height - 76 * mm, "Diberikan secara resmi kepada:")
        
        # --- Nama Peserta ---
        emp_name = self.employee_id.name or ''
        c.setFillColor(colors.HexColor('#0F2C59'))
        c.setFont("Times-Bold", 30)
        c.drawCentredString(center_x, height - 92 * mm, emp_name)
        
        # Garis emas di bawah nama peserta
        c.setStrokeColor(colors.HexColor('#C5A059'))
        c.setLineWidth(1)
        c.line(center_x - 45 * mm, height - 96 * mm, center_x + 45 * mm, height - 96 * mm)
        
        # --- Program Pelatihan ---
        c.setFillColor(colors.HexColor('#444444'))
        c.setFont("Helvetica", 13)
        c.drawCentredString(center_x, height - 110 * mm, "Atas keberhasilan dan kelulusan dalam mengikuti program pelatihan:")
        
        # --- Nama Course ---
        course_name = self.channel_id.name or ''
        c.setFillColor(colors.HexColor('#1A365D'))
        c.setFont("Times-Bold", 24)
        c.drawCentredString(center_x, height - 124 * mm, f'{course_name}')
        
        
        # --- Tanda Tangan ---
        sig_y = 25 * mm
        
        # Kiri: Trainer
        left_x = 75 * mm
        c.setFillColor(colors.HexColor('#555555'))
        c.setFont("Helvetica", 11)
        c.drawCentredString(left_x, sig_y + 24 * mm, "Trainer / Instruktur,")
        
        trainer_name = (self.trainer_id and self.trainer_id.name) or (self.channel_id and self.channel_id.user_id and self.channel_id.user_id.name) or ''
        c.setFillColor(colors.HexColor('#0F2C59'))
        c.setFont("Helvetica-Bold", 12)
        c.drawCentredString(left_x, sig_y, trainer_name)
        if trainer_name:
            t_width = c.stringWidth(trainer_name, "Helvetica-Bold", 12)
            c.setStrokeColor(colors.HexColor('#0F2C59'))
            c.setLineWidth(0.8)
            c.line(left_x - t_width/2.0, sig_y - 2, left_x + t_width/2.0, sig_y - 2)
        
        # Kanan: HR Head
        right_x = width - 75 * mm
        date_val = self.completion_date or datetime.date.today()
        date_str = date_val.strftime('%d %B %Y') if hasattr(date_val, 'strftime') else str(date_val)
        
        c.setFillColor(colors.HexColor('#555555'))
        c.setFont("Helvetica", 11)
        c.drawCentredString(right_x, sig_y + 30 * mm, f"Malang, {date_str}")
        c.drawCentredString(right_x, sig_y + 24 * mm, "Head of HR L&D,")
        
        hr_name = "Ahmad Fauzi"
        c.setFillColor(colors.HexColor('#0F2C59'))
        c.setFont("Helvetica-Bold", 12)
        c.drawCentredString(right_x, sig_y, hr_name)
        h_width = c.stringWidth(hr_name, "Helvetica-Bold", 12)
        c.setStrokeColor(colors.HexColor('#0F2C59'))
        c.setLineWidth(0.8)
        c.line(right_x - h_width/2.0, sig_y - 2, right_x + h_width/2.0, sig_y - 2)
        
        c.showPage()
        c.save()
        
        pdf_data = buffer.getvalue()
        buffer.close()
        return pdf_data

    #  4: PENERBITAN SERTIFIKAT AUTOMATIS PDF & EMAIL
    def action_generate_certificate(self):
        """Method untuk meng-generate nomor sertifikat, PDF via ReportLab, dan mengirim email otomatis."""
        for rec in self:
            if rec.state != 'passed':
                raise UserError(_("Sertifikat hanya dapat diterbitkan untuk peserta dengan status LULUS!"))

            # 1. Hapus attachment lama jika ada
            old_attachments = self.env['ir.attachment'].search([
                ('res_model', '=', 'hcdi.training.history'),
                ('res_id', '=', rec.id)
            ])
            if old_attachments:
                old_attachments.sudo().unlink()

            # 2. Generate nomor sertifikat unik jika belum ada
            if not rec.certificate_number:
                rec.certificate_number = self.env['ir.sequence'].next_by_code('hcdi.training.certificate') or _('New')

            # 3. Render PDF Sertifikat dengan ReportLab (100% presisi A4 Landscape full page)
            pdf_content = rec._generate_reportlab_certificate_pdf()
            
            filename = f"Sertifikat_{rec.certificate_number.replace('/', '_')}_{rec.employee_id.name}.pdf"
            rec.write({
                'certificate_file': base64.b64encode(pdf_content),
                'certificate_filename': filename,
            })

            # 4. Kirim Email Otomatis dengan Attachment PDF
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


    # ─────────────────────────────────────────────────────────
    #  DASHBOARD DATA METHODS
    # ─────────────────────────────────────────────────────────

    @api.model
    def get_dashboard_data(self, filters=None):
        """Return all data needed by the Training Management Dashboard."""
        if filters is None:
            filters = {}

        domain = []
        department_id = filters.get('department_id')
        employee_id   = filters.get('employee_id')
        channel_id    = filters.get('channel_id')
        year          = filters.get('year')
        page          = int(filters.get('page', 1))
        page_size     = int(filters.get('page_size', 5))

        if department_id:
            domain.append(('department_id', '=', int(department_id)))
        if employee_id:
            domain.append(('employee_id', '=', int(employee_id)))
        if channel_id:
            domain.append(('channel_id', '=', int(channel_id)))
        if year:
            domain.extend([
                ('start_date', '>=', '%s-01-01' % year),
                ('start_date', '<=', '%s-12-31' % year),
            ])

        records = self.search(domain)
        total_participants = len(records)
        total_training = len(records.mapped('channel_id'))

        done_records        = records.filtered(lambda r: r.execution_state == 'done')
        in_progress_records = records.filtered(lambda r: r.execution_state == 'in_progress')
        not_started_records = records.filtered(lambda r: r.execution_state == 'draft')

        completion_rate = round((len(done_records) / total_participants * 100)
                                if total_participants else 0)

        passed_records = records.filtered(lambda r: r.state == 'passed')
        failed_records = records.filtered(lambda r: r.state == 'failed')

        pass_rate = round((len(passed_records) / len(done_records) * 100)
                          if done_records else 0)

        # Paginate employee table
        offset           = (page - 1) * page_size
        paginated        = records[offset: offset + page_size]
        employees_data   = []
        for rec in paginated:
            if rec.execution_state == 'done':
                display_state = rec.state          # 'passed' / 'failed'
            elif rec.execution_state == 'in_progress':
                display_state = 'in_progress'
            else:
                display_state = 'not_started'

            employees_data.append({
                'employee': rec.employee_id.name or '',
                'course':   rec.channel_id.name   or '',
                'score':    rec.final_score,
                'state':    display_state,
            })

        return {
            'kpi': {
                'total_training':    total_training,
                'total_participants': total_participants,
                'completion_rate':   completion_rate,
                'pass_rate':         pass_rate,
            },
            'completion': {
                'completed':   len(done_records),
                'in_progress': len(in_progress_records) + len(not_started_records),
            },
            'result': {
                'passed': len(passed_records),
                'failed': len(failed_records),
            },
            'employees':       employees_data,
            'total_employees': total_participants,
        }

    @api.model
    def get_filter_options(self):
        """Return dropdown options for the dashboard filter bar."""
        departments = self.env['hr.department'].search_read(
            [], ['id', 'name'], order='name asc'
        )
        employees = self.env['hr.employee'].search_read(
            [('active', '=', True)], ['id', 'name', 'department_id'], order='name asc'
        )
        courses = self.env['slide.channel'].search_read(
            [], ['id', 'name'], order='name asc'
        )

        all_records  = self.search([('start_date', '!=', False)])
        years_set    = set(r.start_date.year for r in all_records)
        current_year = datetime.date.today().year
        years_set.add(current_year)
        years = sorted(years_set, reverse=True)

        return {
            'departments': departments,
            'employees':   employees,
            'courses':     courses,
            'years':       years,
        }


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

