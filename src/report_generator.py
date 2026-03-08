import os
import json
from datetime import datetime
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER

from src.models import CodeReviewResult, Severity


# â”€â”€ Colour palette â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
DARK_BG      = colors.HexColor('#1E1E2E')
ACCENT_BLUE  = colors.HexColor('#89B4FA')
ACCENT_GREEN = colors.HexColor('#A6E3A1')
ACCENT_YELLOW= colors.HexColor('#F9E2AF')
ACCENT_RED   = colors.HexColor('#F38BA8')
TEXT_WHITE   = colors.HexColor('#CDD6F4')
TEXT_MUTED   = colors.HexColor('#6C7086')
SURFACE      = colors.HexColor('#313244')
SURFACE2     = colors.HexColor('#45475A')


def _score_color(score: int) -> colors.HexColor:
    if score >= 90:
        return ACCENT_GREEN
    elif score >= 70:
        return ACCENT_BLUE
    elif score >= 50:
        return ACCENT_YELLOW
    return ACCENT_RED


def _score_label(score: int) -> str:
    if score >= 90:
        return 'EXCELLENT'
    elif score >= 70:
        return 'GOOD'
    elif score >= 50:
        return 'NEEDS WORK'
    return 'CRITICAL ISSUES'


def _severity_color(severity: Severity) -> colors.HexColor:
    return {
        Severity.CRITICAL:   ACCENT_RED,
        Severity.WARNING:    ACCENT_YELLOW,
        Severity.SUGGESTION: ACCENT_BLUE,
    }.get(severity, ACCENT_BLUE)


def _build_styles():
    base = getSampleStyleSheet()

    styles = {}

    styles['title'] = ParagraphStyle(
        'title',
        fontName='Helvetica-Bold',
        
        textColor=TEXT_WHITE,
        alignment=TA_LEFT,
        spaceAfter=4,
    )
    styles['subtitle'] = ParagraphStyle(
        'subtitle',
        fontName='Helvetica',
        fontSize=10,
        textColor=TEXT_MUTED,
        alignment=TA_LEFT,
        spaceAfter=2,
    )
    styles['section_header'] = ParagraphStyle(
        'section_header',
        fontName='Helvetica-Bold',
        fontSize=13,
        textColor=ACCENT_BLUE,
        spaceBefore=16,
        spaceAfter=6,
    )
    styles['body'] = ParagraphStyle(
        'body',
        fontName='Helvetica',
        fontSize=9,
        textColor=TEXT_WHITE,
        leading=14,
        spaceAfter=4,
    )
    styles['muted'] = ParagraphStyle(
        'muted',
        fontName='Helvetica',
        fontSize=8,
        textColor=TEXT_MUTED,
        leading=12,
    )
    styles['code'] = ParagraphStyle(
        'code',
        fontName='Courier',
        fontSize=8,
        textColor=ACCENT_GREEN,
        leading=12,
        leftIndent=8,
    )
    styles['badge'] = ParagraphStyle(
        'badge',
        fontName='Helvetica-Bold',
        fontSize=8,
        textColor=DARK_BG,
        alignment=TA_CENTER,
    )

    return styles


def _header_block(result: CodeReviewResult, repo_name: str, styles: dict):
    elements = []

    # Title row
    elements.append(Paragraph('Code Review Report', styles['title']))
    elements.append(Paragraph(
        f'Repository: <b>{repo_name}</b> &nbsp;|&nbsp; '
        f'Language: <b>{result.detected_language.value.upper()}</b> &nbsp;|&nbsp; '
        f'Generated: <b>{datetime.now().strftime("%B %d, %Y %H:%M")}</b>',
        styles['subtitle']
    ))
    elements.append(HRFlowable(width='100%', thickness=1, color=SURFACE2, spaceAfter=12))

    # Score + breakdown cards in one table
    score_color = _score_color(result.score)
    score_label = _score_label(result.score)

    score_data = [[
        Paragraph(f'<font size=36><b>{result.score}</b></font>', ParagraphStyle(
            'sc', fontName='Helvetica-Bold', fontSize=36,
            textColor=score_color, alignment=TA_CENTER
        )),
        Paragraph(f'<b>{score_label}</b>', ParagraphStyle(
            'sl', fontName='Helvetica-Bold', fontSize=11,
            textColor=score_color, alignment=TA_CENTER
        )),
        _stat_cell(str(result.critical_count),   'CRITICAL',   ACCENT_RED,    styles),
        _stat_cell(str(result.warning_count),    'WARNINGS',   ACCENT_YELLOW, styles),
        _stat_cell(str(result.suggestion_count), 'SUGGESTIONS',ACCENT_BLUE,   styles),
        _stat_cell(str(result.total_issues),     'TOTAL ISSUES',TEXT_WHITE,   styles),
    ]]

    score_table = Table(score_data, colWidths=[3.5*cm, 4.5*cm, 2.5*cm, 2.5*cm, 3*cm, 2.5*cm])
    score_table.setStyle(TableStyle([
        ('BACKGROUND',  (0, 0), (-1, -1), SURFACE),
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [SURFACE]),
        ('BOX',         (0, 0), (-1, -1), 1, SURFACE2),
        ('INNERGRID',   (0, 0), (-1, -1), 0.5, SURFACE2),
        ('VALIGN',      (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',  (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING',(0,0), (-1, -1), 12),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING',(0, 0), (-1, -1), 8),
        ('ROUNDEDCORNERS', (0,0), (-1,-1), [4,4,4,4]),
    ]))

    elements.append(score_table)
    elements.append(Spacer(1, 12))
    return elements


def _stat_cell(value: str, label: str, color: colors.HexColor, styles: dict):
    return Table([
        [Paragraph(f'<b>{value}</b>', ParagraphStyle(
            'sv', fontName='Helvetica-Bold', fontSize=20,
            textColor=color, alignment=TA_CENTER
        ))],
        [Paragraph(label, ParagraphStyle(
            'sl', fontName='Helvetica', fontSize=7,
            textColor=TEXT_MUTED, alignment=TA_CENTER
        ))],
    ], colWidths=[None])


def _summary_block(result: CodeReviewResult, styles: dict):
    elements = []
    elements.append(Paragraph('Summary', styles['section_header']))
    elements.append(Paragraph(result.summary or 'No summary available.', styles['body']))
    elements.append(Spacer(1, 6))
    return elements


def _issues_block(result: CodeReviewResult, styles: dict):
    elements = []
    elements.append(Paragraph('Issues', styles['section_header']))

    if not result.issues:
        elements.append(Paragraph(
            'âœ“ No issues found. Code matches your personal coding patterns perfectly.',
            ParagraphStyle('ok', fontName='Helvetica', fontSize=10, textColor=ACCENT_GREEN)
        ))
        return elements

    # Group by severity
    order = [Severity.CRITICAL, Severity.WARNING, Severity.SUGGESTION]
    severity_labels = {
        Severity.CRITICAL:   'Critical',
        Severity.WARNING:    'Warning',
        Severity.SUGGESTION: 'Suggestion',
    }

    for sev in order:
        group = [i for i in result.issues if i.severity == sev]
        if not group:
            continue

        sev_color = _severity_color(sev)
        elements.append(Paragraph(
            f'â— {severity_labels[sev]} ({len(group)})',
            ParagraphStyle('sh', fontName='Helvetica-Bold', fontSize=10,
                           textColor=sev_color, spaceBefore=10, spaceAfter=4)
        ))

        for issue in group:
            block_data = [
                # Row 1: line + category
                [
                    Paragraph(f'Line {issue.line_number}', ParagraphStyle(
                        'ln', fontName='Helvetica-Bold', fontSize=8, textColor=sev_color
                    )),
                    Paragraph(issue.category.upper(), ParagraphStyle(
                        'cat', fontName='Helvetica-Bold', fontSize=7,
                        textColor=TEXT_MUTED, alignment=TA_LEFT
                    )),
                ],
                # Row 2: message
                [
                    Paragraph(issue.message, styles['body']),
                    '',
                ],
                # Row 3: suggestion
                [
                    Paragraph(f'<b>Fix:</b> {issue.suggestion}', styles['muted']),
                    '',
                ],
            ]

            # Add diff row if present
            if issue.diff:
                block_data.append([
                    Paragraph(issue.diff.replace('\n', '<br/>'), styles['code']),
                    '',
                ])

            issue_table = Table(block_data, colWidths=[3*cm, 14.5*cm])
            issue_table.setStyle(TableStyle([
                ('BACKGROUND',   (0, 0), (-1, -1), SURFACE),
                ('BOX',          (0, 0), (-1, -1), 1, sev_color),
                ('LINEAFTER',    (0, 0), (0, -1),  1, sev_color),
                ('VALIGN',       (0, 0), (-1, -1), 'TOP'),
                ('TOPPADDING',   (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING',(0, 0), (-1, -1), 6),
                ('LEFTPADDING',  (0, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                ('SPAN',         (0, 1), (-1, 1)),
                ('SPAN',         (0, 2), (-1, 2)),
            ]))

            elements.append(KeepTogether([issue_table, Spacer(1, 6)]))

    return elements


def _footer_style():
    return ParagraphStyle(
        'footer',
        fontName='Helvetica',
        fontSize=7,
        textColor=TEXT_MUTED,
        alignment=TA_CENTER,
    )


def generate_pdf(
    result: CodeReviewResult,
    repo_name: str,
    output_dir: str = 'reports',
) -> str:
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_name = repo_name.replace('/', '_').replace(' ', '_')
    filename = f'review_{safe_name}_{timestamp}.pdf'
    filepath = os.path.join(output_dir, filename)

    doc = SimpleDocTemplate(
        filepath,
        pagesize=A4,
        leftMargin=2*cm,
        rightMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2.5*cm,
    )

    styles = _build_styles()
    story = []

    story += _header_block(result, repo_name, styles)
    story += _summary_block(result, styles)
    story += _issues_block(result, styles)

    story.append(Spacer(1, 20))
    story.append(HRFlowable(width='100%', thickness=0.5, color=SURFACE2))
    story.append(Paragraph(
        f'Generated by Code Review Agent - github.com/vaishnavi1064 - {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        _footer_style()
    ))

    # Dark background on every page
    def dark_canvas(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(DARK_BG)
        canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
        canvas.restoreState()

    doc.build(story, onFirstPage=dark_canvas, onLaterPages=dark_canvas)
    return filepath


def generate_json(
    result: CodeReviewResult,
    repo_name: str,
    output_dir: str = 'reports',
) -> str:
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_name = repo_name.replace('/', '_').replace(' ', '_')
    filename = f'review_{safe_name}_{timestamp}.json'
    filepath = os.path.join(output_dir, filename)

    report = {
        'repo': repo_name,
        'generated_at': datetime.now().isoformat(),
        'language': result.detected_language.value,
        'score': result.score,
        'score_label': _score_label(result.score),
        'summary': result.summary,
        'counts': {
            'total':       result.total_issues,
            'critical':    result.critical_count,
            'warnings':    result.warning_count,
            'suggestions': result.suggestion_count,
        },
        'issues': [
            {
                'line_number': issue.line_number,
                'severity':    issue.severity.value,
                'category':    issue.category,
                'message':     issue.message,
                'suggestion':  issue.suggestion,
                'diff':        issue.diff,
            }
            for issue in result.issues
        ],
    }

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    return filepath


def generate_report(
    result: CodeReviewResult,
    repo_name: str,
    output_dir: str = 'reports',
    export_pdf: bool = True,
    export_json: bool = True,
) -> dict:
    paths = {}
    if export_pdf:
        paths['pdf'] = generate_pdf(result, repo_name, output_dir)
    if export_json:
        paths['json'] = generate_json(result, repo_name, output_dir)
    return paths


