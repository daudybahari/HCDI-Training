/** @odoo-module **/

import { Component, useState, onWillStart, useRef, useEffect } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class TrainingDashboard extends Component {
    static template = "hcdi_training.TrainingDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");

        this.state = useState({
            filters: {
                department_id: false,
                employee_id: false,
                channel_id: false,
                year: new Date().getFullYear(),
            },
            data: {
                kpi: {
                    total_training: 0,
                    total_participants: 0,
                    completion_rate: 0,
                    pass_rate: 0,
                },
                completion: { completed: 0, in_progress: 0 },
                result: { passed: 0, failed: 0 },
                employees: [],
                total_employees: 0,
            },
            filterOptions: {
                departments: [],
                employees: [],
                courses: [],
                years: [],
            },
            currentPage: 1,
            pageSize: 5,
            loading: true,
        });

        this.completionChartRef = useRef("completionChart");
        this.resultChartRef = useRef("resultChart");

        onWillStart(async () => {
            await this._loadFilterOptions();
            await this._loadDashboardData();
        });

        useEffect(
            () => {
                this._renderCharts();
            },
            () => [
                this.state.data.completion.completed,
                this.state.data.completion.in_progress,
                this.state.data.result.passed,
                this.state.data.result.failed,
                this.state.data.kpi.completion_rate,
                this.state.data.kpi.pass_rate,
            ]
        );
    }

    async _loadFilterOptions() {
        const opts = await this.orm.call(
            "hcdi.training.history",
            "get_filter_options",
            []
        );
        this.state.filterOptions = opts;
    }

    async _loadDashboardData() {
        this.state.loading = true;
        const payload = {
            department_id: this.state.filters.department_id || false,
            employee_id:   this.state.filters.employee_id   || false,
            channel_id:    this.state.filters.channel_id    || false,
            year:          this.state.filters.year          || false,
            page:          this.state.currentPage,
            page_size:     this.state.pageSize,
        };
        const data = await this.orm.call(
            "hcdi.training.history",
            "get_dashboard_data",
            [payload]
        );
        this.state.data = data;
        this.state.loading = false;
    }

    _renderCharts() {
        const { completion, result, kpi } = this.state.data;
        this._drawDonut(
            this.completionChartRef.el,
            [completion.completed, completion.in_progress],
            ["#4f9ef8", "#e2e8f0"],
            kpi.completion_rate + "%",
            "Completed"
        );
        this._drawDonut(
            this.resultChartRef.el,
            [result.passed, result.failed],
            ["#22c55e", "#ef4444"],
            kpi.pass_rate + "%",
            "Passed"
        );
    }

    _drawDonut(canvas, values, colors, centerText, centerLabel) {
        if (!canvas) return;
        const ctx  = canvas.getContext("2d");
        const dpr  = window.devicePixelRatio || 1;
        const size = canvas.offsetWidth || 200;
        canvas.width  = size * dpr;
        canvas.height = size * dpr;
        canvas.style.width  = size + "px";
        canvas.style.height = size + "px";
        ctx.scale(dpr, dpr);

        const cx = size / 2;
        const cy = size / 2;
        const outerR = size * 0.41;
        const innerR = size * 0.27;
        const total  = values.reduce((a, b) => a + b, 0);

        ctx.clearRect(0, 0, size, size);

        if (total === 0) {
            ctx.beginPath();
            ctx.arc(cx, cy, outerR, 0, Math.PI * 2);
            ctx.fillStyle = "#e2e8f0";
            ctx.fill();
        } else {
            let start = -Math.PI / 2;
            values.forEach((v, i) => {
                if (v === 0) return;
                const sweep = (v / total) * Math.PI * 2;
                ctx.beginPath();
                ctx.moveTo(cx, cy);
                ctx.arc(cx, cy, outerR, start, start + sweep);
                ctx.closePath();
                ctx.fillStyle = colors[i];
                ctx.fill();
                start += sweep;
            });
        }

        ctx.beginPath();
        ctx.arc(cx, cy, innerR, 0, Math.PI * 2);
        ctx.fillStyle = "#ffffff";
        ctx.fill();

        ctx.textAlign    = "center";
        ctx.textBaseline = "middle";
        ctx.fillStyle    = "#1e293b";
        ctx.font         = "bold " + Math.round(size * 0.14) + "px Inter, sans-serif";
        ctx.fillText(centerText, cx, cy - size * 0.06);
        ctx.font      = Math.round(size * 0.08) + "px Inter, sans-serif";
        ctx.fillStyle = "#64748b";
        ctx.fillText(centerLabel, cx, cy + size * 0.1);
    }

    async onFilterChange(ev) {
        const field = ev.target.dataset.field;
        const raw   = ev.target.value;
        this.state.filters[field] = raw ? (isNaN(raw) ? raw : parseInt(raw)) : false;
        this.state.currentPage = 1;
        await this._loadDashboardData();
    }

    async onYearChange(ev) {
        const val = ev.target.value;
        this.state.filters.year = val ? parseInt(val) : false;
        this.state.currentPage  = 1;
        await this._loadDashboardData();
    }

    async onResetFilter() {
        this.state.filters = {
            department_id: false,
            employee_id:   false,
            channel_id:    false,
            year:          new Date().getFullYear(),
        };
        this.state.currentPage = 1;
        await this._loadDashboardData();
    }

    async onPageChange(page) {
        if (page < 1 || page > this.totalPages) return;
        this.state.currentPage = page;
        await this._loadDashboardData();
    }

    get totalPages() {
        return Math.max(1, Math.ceil(this.state.data.total_employees / this.state.pageSize));
    }

    get pageNumbers() {
        const total   = this.totalPages;
        const current = this.state.currentPage;
        if (total <= 5) return Array.from({ length: total }, (_, i) => i + 1);
        const pages = new Set([1, total, current]);
        if (current > 1)     pages.add(current - 1);
        if (current < total) pages.add(current + 1);
        return [...pages].sort((a, b) => a - b);
    }

    get showingFrom() {
        if (this.state.data.total_employees === 0) return 0;
        return (this.state.currentPage - 1) * this.state.pageSize + 1;
    }

    get showingTo() {
        return Math.min(
            this.state.currentPage * this.state.pageSize,
            this.state.data.total_employees
        );
    }

    getStatusClass(status) {
        const map = {
            passed:      "hcdi-badge hcdi-badge-passed",
            failed:      "hcdi-badge hcdi-badge-failed",
            in_progress: "hcdi-badge hcdi-badge-inprogress",
            not_started: "hcdi-badge hcdi-badge-notstarted",
        };
        return map[status] || "hcdi-badge hcdi-badge-notstarted";
    }

    getStatusLabel(status) {
        const map = {
            passed:      "PASSED",
            failed:      "FAILED",
            in_progress: "IN PROGRESS",
            not_started: "NOT STARTED",
        };
        return map[status] || status;
    }

    getInitial(name) {
        return (name || "?").charAt(0).toUpperCase();
    }

    getAvatarColor(name) {
        const palette = ["#4f9ef8","#f97316","#22c55e","#a855f7","#ef4444","#06b6d4","#f59e0b"];
        const idx = name ? name.charCodeAt(0) % palette.length : 0;
        return palette[idx];
    }

    completionPct(value) {
        const total = this.state.data.completion.completed + this.state.data.completion.in_progress;
        if (!total) return "0%";
        return Math.round((value / total) * 100) + "%";
    }

    resultPct(value) {
        const total = this.state.data.result.passed + this.state.data.result.failed;
        if (!total) return "0%";
        return Math.round((value / total) * 100) + "%";
    }
}

registry.category("actions").add("hcdi_training.dashboard", TrainingDashboard);
